import requests
import os
import re
from urllib.parse import quote


def att_url(att, cdn):
    tag = att.get("tag", "attachments")
    file_id = att.get("_id", "")
    filename = att.get("filename", file_id)
    return f"{cdn.rstrip('/')}/{tag}/{file_id}/{quote(filename)}"


# turns the avatar, banner, serveravatar objects into output
def profile_media(user, profile, member, cdn):
    def to_record(asset, kind):
        return {
            "id": asset.get("_id", ""),
            "filename": asset.get("filename", asset.get("_id", kind)),
            "content_type": asset.get("content_type", ""),
            "kind": kind,
            "url": att_url(asset, cdn),
        }

    # api field is background and not banner, why 
    records = []
    avatar = user.get("avatar")
    if avatar:
        records.append(to_record(avatar, "avatar"))
    background = (profile or {}).get("background")
    if background:
        records.append(to_record(background, "banner"))
    if member:
        server_avatar = member.get("avatar")
        if server_avatar:
            records.append(to_record(server_avatar, "server_avatar"))
    return records


def att_downloads(attachments, media_dir, message_id, session=None):
    os.makedirs(media_dir, exist_ok=True)
    getter = session.get if session else requests.get
    for att in attachments:
        
        # sanitizing the filename
        raw_name = os.path.basename(att['filename'])  # drop any directory parts first
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', raw_name).lstrip('.') or "file"
        ok_name = f"{message_id}_{att['id']}_{safe_name}"
        dest = os.path.join(media_dir, ok_name)


        # just in case
        if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(media_dir):
            raise ValueError("refusing to write outside media_dir")

        tmp_dest = dest + ".part"
        try:
            resp = getter(att["url"], stream=True, timeout=(10, 120))
            resp.raise_for_status()

            # since sometimes expired attachment links returns html error or a json error, this should help if img is broken
            resp_content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            expected_type = (att.get("content_type") or "").split(";")[0].strip()
            if resp_content_type in ("text/html", "application/json") and \
               expected_type and expected_type not in (resp_content_type,):
                snippet = resp.text[:200] if hasattr(resp, "text") else ""
                raise ValueError(f"expected {expected_type or 'binary'} but server returned {resp_content_type or 'unknown'}: {snippet!r}")

            bytes_written = 0
            with open(tmp_dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)

            content_length = resp.headers.get("content-length")
            if content_length is not None and bytes_written != int(content_length):
                raise ValueError("incomplete download.")
            if bytes_written == 0:
                raise ValueError("Nothing was downloaded.")

            os.replace(tmp_dest, dest)
            att["local_path"] = dest
        except Exception as e:
            att["local_path"] = ""
            att["download_error"] = str(e)
            if os.path.exists(tmp_dest):
                os.remove(tmp_dest)
