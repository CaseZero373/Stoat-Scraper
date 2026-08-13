import requests
import sys
import time
import os
import re
from datetime import datetime, timezone

from .authors import AuthorInfoCache, format_username
#from .client import RATE_LIMIT_SAFETY_DELAY
from .client import paced_sleep
from .media import att_downloads, att_url, profile_media
from .output import MEMBER_LAYOUT, SCRAPE_LAYOUT, write_csv, write_json
from .timeutils import parse_iso_dt, ts_ulid, ulid_to_ms, ulid_to_dt, within_time_bounds

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def cmd_list_channels(client, args):
    channels = client.fetch_server_channels(args.server)
    if not channels:
        print("No channels found.")
        return
    print(f"Channels in server {args.server}:")
    for ch in channels:
        cid = ch.get("_id", "?")
        name = ch.get("name", "(unnamed)")
        ctype = ch.get("channel_type", "")
        print(f"  {name}  [{ctype}]  {cid}")



def scrape_channel(client, channel_id, args, author_cache, scraped_at, only_types, media_dir, match=None):
    fetch_limit = None if args.count else args.limit

    # --before seeds cursor so never fetcges newer pages
    start_before = None
    if args.before:
        start_before = args.before.ulid or ulid_to_ms(args.before.dt.timestamp() * 1000)
 
    all_msgs = []
    for msg in client.iter_msgs(channel_id, hard_limit=fetch_limit, start_before=start_before):
        if args.after:
            msg_dt = ulid_to_dt(msg.get("_id", ""))

            # walking newest to oldest, so once we're older than --after everything left is too
            if msg_dt is not None and msg_dt < args.after.dt:
                break
        all_msgs.append(msg)
    all_msgs.reverse()
    author_total_msg = {}
    if args.count:
        counters = {}
        for msg in all_msgs: # count bridged user msgs under the masquerade name to avoid dumping on the bridge bot
            masquerade = msg.get("masquerade")
            key = f"masquerade:{masquerade['name']}" if masquerade and masquerade.get("name") else msg.get("author")
            counters[key] = counters.get(key, 0) + 1
            author_total_msg[msg.get("_id")] = counters[key]

        # to let --limit trim the output otherwise it gets ignored
        if args.limit:
            all_msgs = all_msgs[-args.limit:]

    meta_kind = {"Image": "image", "Video": "video", "Audio": "audio"}
    kind_plural = {"image": "images", "video": "videos", "audio": "audio", "file": "files"}

    rows = []
    for msg in all_msgs:
        author = msg.get("author")
        if args.user_id and author != args.user_id:
            continue
        if match and not match.search(msg.get("content") or ""):
            continue

        # building attachment from api attachment objects working out file type from metadata or falling back mime type
        attachments = []
        for att in msg.get("attachments") or []:
            meta_type = (att.get("metadata") or {}).get("type", "")
            kind = meta_kind.get(meta_type)
            if not kind:
                content_type = (att.get("content_type") or "").lower()
                if content_type.startswith("image/"):
                    kind = "image"
                elif content_type.startswith("video/"):
                    kind = "video"
                elif content_type.startswith("audio/"):
                    kind = "audio"
                else:
                    kind = "file"
            attachments.append({
                "id": att.get("_id", ""),
                "filename": att.get("filename", ""),
                "content_type": att.get("content_type", ""),
                "kind": kind,
                "url": att_url(att, args.cdn),
            })

        links = URL_RE.findall(msg.get("content") or "")

        # --only filters on attachment kind or "links", skip the message entirely if nothing matches
        if only_types:
            has_match = ("links" in only_types and links) or any(
                kind_plural.get(a["kind"], a["kind"]) in only_types for a in attachments
            )
            if not has_match:
                continue

        if media_dir and attachments:
            att_downloads(attachments, media_dir, msg.get("_id", ""))

        author_info = author_cache.get(author) if author else {"id": "", "username": "", "plain_username": "", "display_name": "", "server_nickname": "", "bot": False,}

        # masquerade is how bridged users show a "fake" name and avatar, fall back to the real author otherwise
        masquerade = msg.get("masquerade")
        if masquerade and masquerade.get("name"):
            display_name = masquerade["name"]
        else:
            display_name = author_info["display_name"] or author_info.get("plain_username") or author_info["username"]

        reactions = msg.get("reactions") or {}
        reactions = [{"emoji": emoji, "count": len(uids), "user_ids": list(uids)} for emoji, uids in reactions.items()]

        # revolt stores only the content and last edited ts
        edited_at = msg.get("edited") or ""

        # what revolt uses for replies, this lists all msgs IDs and msgs is replying to
        referenced_ids = msg.get("replies") or []

        row = {
            "message_id": msg.get("_id"),
            "author_id": author,
            "author_username": author_info["username"],
            "author_display_name": display_name,
            "author_server_nickname": author_info["server_nickname"],
            "author_bot": author_info["bot"],
            "is_masquerade": bool(masquerade),
            "masquerade_name": (masquerade or {}).get("name", ""),
            "masquerade_avatar": (masquerade or {}).get("avatar", ""),
            "content": msg.get("content", ""),
            "approx_timestamp": ts_ulid(msg.get("_id", "")),
            "was_edited": bool(edited_at),
            "edited_at": edited_at,
            "attachments": attachments,
            "links": links,
            "reactions": reactions,
            "referenced_message_ids": referenced_ids,
            "scraped_at": scraped_at,
        }
        if args.count:
            row["message_count"] = author_total_msg.get(msg.get("_id"), "")
        rows.append(row)
    return rows


def write_scrape_output(rows, output_path, args, include_channel_fields=False):
    if output_path.endswith(".csv"):
        fields = ["message_id", "author_id", "author_username", "author_display_name",
                  "author_server_nickname", "author_bot", "is_masquerade", "masquerade_name",
                  "content", "approx_timestamp", "was_edited", "edited_at",
                  "attachment_kinds", "attachment_urls", "links", "reactions",
                  "referenced_message_ids"]
        if include_channel_fields:
            fields = ["channel_id", "channel_name"] + fields
        if args.count:
            fields.append("message_count")

        # csv flattens
        flat_rows = []
        for r in rows:
            flat = {
                "message_id": r["message_id"],
                "author_id": r["author_id"],
                "author_username": r["author_username"],
                "author_display_name": r["author_display_name"],
                "author_server_nickname": r["author_server_nickname"],
                "author_bot": r["author_bot"],
                "is_masquerade": r["is_masquerade"],
                "masquerade_name": r["masquerade_name"],
                "content": r["content"],
                "approx_timestamp": r["approx_timestamp"],
                "was_edited": r["was_edited"],
                "edited_at": r["edited_at"],
                "attachment_kinds": ", ".join(a["kind"] for a in r["attachments"]),
                "attachment_urls": ", ".join(a["url"] for a in r["attachments"]),
                "links": ", ".join(r["links"]),
                "reactions": ", ".join(f"{rec['emoji']}:{rec['count']}" for rec in r["reactions"]),
                "referenced_message_ids": ", ".join(r["referenced_message_ids"]),
            }
            if include_channel_fields:
                flat["channel_id"] = r.get("channel_id", "")
                flat["channel_name"] = r.get("channel_name", "")
            if args.count:
                flat["message_count"] = r["message_count"]
            flat_rows.append(flat)

        write_csv(flat_rows, output_path, fields)
    else:
        write_json(rows, output_path, SCRAPE_LAYOUT)


def cmd_scrape(client, args):
    only_types = set(args.only) if args.only else None
    #match = re.compile(args.match, re.IGNORECASE) if args.match else None
    match = re.compile(rf"\b{re.escape(args.match)}\b", re.IGNORECASE) if args.match else None

    if args.after:
        print(f"Filtering messages after {args.after.dt.isoformat()}")
    if args.before:
        print(f"Filtering messages before {args.before.dt.isoformat()}")

    # single channel
    if args.channel:
        media_dir = None
        if args.download:
            base, _ = os.path.splitext(args.output)
            media_dir = f"{base}_media"

        # find server context to pull servr nicknames
        server_id = args.server
        if not server_id:
            try:
                channel_info = client.fetch_channel(args.channel)
                server_id = channel_info.get("server") or channel_info.get("server_id")
            except requests.HTTPError:
                server_id = None

        scraped_at = datetime.now(timezone.utc).isoformat()
        author_cache = AuthorInfoCache(client, server_id=server_id)

        rows = scrape_channel(client, args.channel, args, author_cache, scraped_at, only_types, media_dir, match)
        write_scrape_output(rows, args.output, args)

        print(f"Saved {len(rows)} messages to {args.output}")
        if media_dir:
            print(f"Downloaded matched attachments to {media_dir}/")
        return

    # server loop over every channel
    channels = client.fetch_server_channels(args.server)
    if not channels:
        print("No channels found in that server.")
        return

    scraped_at = datetime.now(timezone.utc).isoformat()
    author_cache = AuthorInfoCache(client, server_id=args.server)  # shared across all channels

    base, ext = os.path.splitext(args.output)
    ext = ext or ".json"

    combined_rows = []
    total_saved = 0
    scraped_channels = 0

    for ch in channels:
        cid = ch.get("_id")
        cname = ch.get("name", "(unnamed)")

        if ch.get("_error"):
            print(f"  skipping #{cname} ({cid}): inaccessible")
            continue

        if args.combine:
            chan_output = None
            media_dir = None
            if args.download:
                media_dir = f"{base}_media"
        else:
            # turn the channel name into something filesystem safe for its own output file
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", cname or "").strip("_") or "channel"
            chan_output = f"{base}_{safe_name}_{cid}{ext}"
            media_dir = None
            if args.download:
                media_dir = f"{os.path.splitext(chan_output)[0]}_media"

        print(f"Scraping #{cname} ({cid})...")
        try:
            rows = scrape_channel(client, cid, args, author_cache, scraped_at, only_types, media_dir, match)
        except requests.HTTPError as e:
            print(f"  failed to scrape #{cname} ({cid}): {e}")
            continue

        scraped_channels += 1
        total_saved += len(rows)

        if args.combine:
            for r in rows:
                r["channel_id"] = cid
                r["channel_name"] = cname
            combined_rows.extend(rows)
        else:
            write_scrape_output(rows, chan_output, args)
            print(f"  saved {len(rows)} messages to {chan_output}")
            if media_dir:
                print(f"  downloaded matched attachments to {media_dir}/")
        paced_sleep()

    if args.combine:
        write_scrape_output(combined_rows, args.output, args, include_channel_fields=True)
        print(f"Saved {total_saved} messages across {scraped_channels} channels to {args.output}")
    else:
        print(f"Saved {total_saved} messages across {scraped_channels} channels.")


# does get profile and server member info
def get_profile(client, user_id, member=None, role_names=None, cdn=None, media_dir=None):
    try:
        user = client.fetch_user(user_id)
    except requests.HTTPError as e:
        print(f"  could not fetch user {user_id}: {e}")
        user = {}

    bio = ""
    profile = None
    try:
        profile = client.fetch_user_profile(user_id)
        bio = profile.get("content") or ""
    except requests.HTTPError:
        pass 

    status = user.get("status") or {}
    username = format_username(user)
    plain_username = user.get("username", "")
    display_name = user.get("display_name") or plain_username

    row = {
        "user_id": user_id,
        "username": username,
        "display_name": display_name,
        "server_nickname": "",
        "bot": bool(user.get("bot")),
        "bio": bio,
        "status_text": status.get("text") or "",
        "status_presence": status.get("presence") or "",
        "roles": "",
        "account_created": ts_ulid(user_id),
        "joined_server": "",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

    if member is not None:
        role_ids = member.get("roles") or []
        role_names = role_names or {}
        row["server_nickname"] = member.get("nickname") or ""
        row["roles"] = ", ".join(role_names.get(rid, rid) for rid in role_ids) or "@everyone"
        row["joined_server"] = member.get("joined_at") or ""

    if media_dir and cdn:
        media_records = profile_media(user, profile, member, cdn)
        if media_records:
            att_downloads(media_records, media_dir, user_id)
        row["downloaded_media"] = [m["kind"] for m in media_records if m.get("local_path")]
    return row


def cmd_scrape_members(client, args):
    media_dir = None
    if args.download:
        base, _ = os.path.splitext(args.output)
        media_dir = f"{base}_media"

    if args.after:
        print(f"Filtering: members after {args.after.dt.isoformat()}")
    if args.before:
        print(f"Filtering: members before {args.before.dt.isoformat()}")

    # treats channel recipients as member lists for groups
    if args.channel:
        channel = client.fetch_channel(args.channel)
        ctype = channel.get("channel_type", "")
        if ctype not in ("DirectMessage", "Group"):
            print(f"Error: channel {args.channel} has type '{ctype}', not 'DirectMessage' or 'Group'.")

        recipient_ids = channel.get("recipients", [])

        if args.user_id:
            if args.user_id not in recipient_ids:
                print(f"Error: user {args.user_id} is not a recipient of channel {args.channel}.")
                return
            recipient_ids = [args.user_id]

        # dm and group recipients have no join date so this filters by account creation date instead
        if args.after or args.before:
            recipient_ids = [uid for uid in recipient_ids if within_time_bounds(ulid_to_dt(uid), args.after, args.before)]

        if not args.user_id and args.limit:
            recipient_ids = recipient_ids[:args.limit]

        rows = [get_profile(client, uid, cdn=args.cdn, media_dir=media_dir) for uid in recipient_ids]
        for _ in recipient_ids:
            paced_sleep()
    else:
        server = client.fetch_server(args.server)
        role_names = {rid: r.get("name", rid) for rid, r in (server.get("roles") or {}).items()}

        if args.user_id:
            try:
                member = client.fetch_server_member(args.server, args.user_id)
            except requests.HTTPError as e:
                print(f"Error: could not fetch member {args.user_id} in server {args.server}: {e}")
                return
            member_dt = parse_iso_dt(member.get("joined_at")) or ulid_to_dt(args.user_id)
            if (args.after or args.before) and not within_time_bounds(member_dt, args.after, args.before):
                print(f"User {args.user_id} falls outside the given time window, nothing to scrape.")
                return
            rows = [get_profile(client, args.user_id, member=member, role_names=role_names, cdn=args.cdn, media_dir=media_dir)]
        else:
            data = client.fetch_server_members(args.server)
            members = data.get("members", data if isinstance(data, list) else [])

            # filter by join date before fetching full profiles so no extra api calls, if joined_at is missing it falls back on account creation 
            if args.after or args.before:
                filtered = []
                for m in members:
                    member_id = m.get("_id", {})
                    uid = member_id.get("user") if isinstance(member_id, dict) else m.get("id")
                    member_dt = parse_iso_dt(m.get("joined_at")) or ulid_to_dt(uid)
                    if within_time_bounds(member_dt, args.after, args.before):
                        filtered.append(m)
                members = filtered

            if args.limit:
                members = members[:args.limit]

            rows = []
            for m in members:
                member_id = m.get("_id", {})
                user_id = member_id.get("user") if isinstance(member_id, dict) else m.get("id")
                rows.append(get_profile(client, user_id, member=m, role_names=role_names, cdn=args.cdn, media_dir=media_dir))
                paced_sleep()

    fields = ["user_id", "username", "display_name", "bot", "bio", "status_text", "status_presence", "account_created", "server_nickname", "roles", "scraped_at", "joined_server"]
    if args.download:
        fields.append("downloaded_media")
        csv_rows = []
        for r in rows:
            flat = dict(r)
            flat["downloaded_media"] = ", ".join(r.get("downloaded_media", []))
            csv_rows.append(flat)
    else:
        csv_rows = rows

    if args.output.endswith(".csv"):
        write_csv(csv_rows, args.output, fields)
    else:
        write_json(rows, args.output, MEMBER_LAYOUT)
    print(f"Saved {len(rows)} members to {args.output}")
    if media_dir:
        print(f"Downloaded profile assets to {media_dir}/")


def delete_msgs(client, channel_id, user_id, max_delete, skip_confirm, after_bound=None, before_bound=None, dry=False):
    print(f"Scanning channel {channel_id} for messages sent from {user_id}...")

    start_before = None
    if before_bound:
        start_before = before_bound.ulid or ulid_to_ms(before_bound.dt.timestamp() * 1000)

    targets = []
    for m in client.iter_msgs(channel_id, start_before=start_before):
        if after_bound:
            msg_dt = ulid_to_dt(m.get("_id", ""))
            if msg_dt is not None and msg_dt < after_bound.dt: # newest to oldest so once it is older than --after, everything left is too
                break
        if m.get("author") == user_id:
            targets.append(m)
            if max_delete is not None and len(targets) >= max_delete:
                break
    print(f"Found {len(targets)} messages in {channel_id}.")

    if not targets:
        return 0, 0

    if dry:
        for msg in targets:
            preview = (msg.get("content") or "").replace("\n", " ")[:80]
            print(f"  {msg['_id']}  {ts_ulid(msg['_id'])}  {preview!r}")
        return len(targets), 0
    
    if not skip_confirm:
        ans = input(f"Permanently delete {len(targets)} messages from user {user_id} in channel {channel_id} ? Enter 'y' to continue: ").strip().lower()
        if ans != "y":
            return 0, 0

    deleted, failed = 0, 0
    for msg in targets:
        r = client.delete_msg(channel_id, msg["_id"])
        if r.status_code in (200, 202, 204, 404):
            deleted += 1
        else:
            failed += 1
            print(f"  failed to delete {msg['_id']}: {r.status_code} {r.text[:200]}")
        paced_sleep()
    return deleted, failed


def cmd_delete_msgs(client, args, whoami_id):
    if args.after:
        print(f"Filtering messages after {args.after.dt.isoformat()}")
    if args.before:
        print(f"Filtering messages before {args.before.dt.isoformat()}")

    remaining = args.limit

    if args.server:
        channels = client.fetch_server_channels(args.server)
        channel_ids = [c.get("_id") for c in channels if c.get("_id")]
        if not channel_ids:
            print("No channels found in that server.")
            return
        total_deleted, total_failed = 0, 0
        for cid in channel_ids:
            if remaining is not None and remaining <= 0:
                print("Reached --limit, stopping.")
                break
            try:
                deleted, failed = delete_msgs(client, cid, args.user_id, remaining, args.y, args.after, args.before, args.dry)
            except requests.HTTPError as e:
                print(f"  skipping channel {cid}: {e}")
                continue
            total_deleted += deleted
            total_failed += failed
            if remaining is not None:
                remaining -= deleted
            if args.dry:
                print(f"Across server: Preview of {total_deleted} messages completed, nothing was deleted.")
            else:
                print(f"Across server: Deleted {total_deleted}, failed {total_failed}.")
    else:
        deleted, failed = delete_msgs(client, args.channel, args.user_id, remaining, args.y, args.after, args.before, args.dry)
        if args.dry:
            print(f"Preview of {deleted} messages completed, nothing was deleted.")
        else:
            print(f"Deleted {deleted}, failed {failed}.")
