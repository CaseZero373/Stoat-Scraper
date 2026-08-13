import argparse
import sys
import requests

from .client import StoatClient
from .commands import cmd_delete_msgs, cmd_list_channels, cmd_scrape, cmd_scrape_members
from .timeutils import parse_timebound

# leave None to use --token your_token, or replace it with "your-token"
TOKEN = None

# "session" or "bot"
TOKEN_TYPE = "session"

DEFAULT_API_BASE = "https://api.revolt.chat"
DEFAULT_CDN = "https://autumn.revolt.chat"


def main():
    parser = argparse.ArgumentParser(formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=30))
    parser.add_argument("--token", default=None, help="Use the x-session-token or bot token, if omitted uses default.")
    parser.add_argument("--token-type", choices=["bot", "session"], default=None, help="Required if using a different token-type from default.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="API base URL.")

    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("scrape", help="Export messages and media from a single channel, or across the server.", formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=30))
    p1.add_argument("--server", default=None, help="Scrape all the channels across the whole server.")
    p1.add_argument("--channel", default=None, help="Scrape a single channel.")
    p1.add_argument("--user-id", default=None, help="Only includes messages sent from this user.")
    p1.add_argument("--limit", type=int, default=None, help="Max messages to fetch, if using --server it applies per channel.")
    p1.add_argument("--list", dest="list_channels", action="store_true", help="When used with --server list all channel names and IDs instead of scraping.")
    p1.add_argument("--match", default=None, help="Only include messages whose content matches this.")
    p1.add_argument("--count", action="store_true", help="Add an author message count, requires walking the full channel (ignores --limit while counting, then trims after). Resets per channel on server scrapes.")
    p1.add_argument("--download", action="store_true", help="Download matched attachments into a <output>_media/ folder.")
    p1.add_argument("--only", default=None, nargs="+", choices=["images", "videos", "audio", "files", "links"], metavar="", help="Filter messages containing matching attachment type (images, videos, audio, files, links), no brackets needed.")
    p1.add_argument("--cdn", default=None, help="Manually set the CDN base URL (auto-detected from the instance by default).")
    p1.add_argument("--after", type=lambda v: parse_timebound(v, "--after"), default=None, metavar="ID OR TIME", help="Filter messages sent after a point set by message ID, date (2025.05.20) or time (30m, 24h, 7d).")
    p1.add_argument("--before", type=lambda v: parse_timebound(v, "--before"), default=None, metavar="ID OR TIME", help="Filter messages sent before a point set by message ID, date (2025.05.20) or time (30m, 24h, 7d).")
    p1.add_argument("--combine", action="store_true", help="Merge all channels into the single --output file (tagged with channel_id/channel_name) instead of one file per channel.")
    p1.add_argument("--output", default="messages.json", help="Outputs file in .json or .csv, if not used returns messages.json. When scraping a server, output is used as the base name for each file per channel.")

    p2 = sub.add_parser("member", help="Extracts the member list from a server, dm, or group.", formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=30))
    p2.add_argument("--server", default=None, help="Scrape a server member list.")
    p2.add_argument("--channel", default=None, help="Scrape a group recipient list.")
    p2.add_argument("--user-id", default=None, help="Only scrape this one user.")
    p2.add_argument("--limit", type=int, default=None, help="Max members to scrape.")
    p2.add_argument("--download", action="store_true", help="Download avatar, banner, and server avatar into a folder named after --output.")
    p2.add_argument("--cdn", default=None, help="Manually set the CDN base URL (auto-detected from the instance by default).")
    p2.add_argument("--after", type=lambda v: parse_timebound(v, "--after"), default=None, metavar="TIME OR DATE", help="Filter members who joined after a date (2025.05.20) or time (30m, 24h, 7d).")
    p2.add_argument("--before", type=lambda v: parse_timebound(v, "--before"), default=None, metavar="TIME OR DATE", help="Filter members who joined before a date (2025.05.20) or time (30m, 24h, 7d).")
    p2.add_argument("--output", default="members.json", help="Outputs file in .json or .csv, if not used returns members.json.")

    p3 = sub.add_parser("delete", help="Delete messages in a server, channel, dm, or group.")
    p3.add_argument("--server", default=None, help="Delete across every channel in the server.")
    p3.add_argument("--channel", default=None, help="Delete messages in one channel, DM or group.")
    p3.add_argument("--user-id", default=None, help="Whose messages to delete, with a session token you can delete your own messages or the ones you are permitted by a server, same thing with a bot token with ManageMessages permission enabled.")
    p3.add_argument("--limit", type=int, default=None, help="Set how many messages to delete.")
    p3.add_argument("--after", type=lambda v: parse_timebound(v, "--after"), default=None, metavar="ID OR TIME", help="Filter messages to delete after a message ID, date (2025.05.20) or time (30m, 24h, 7d).")
    p3.add_argument("--before", type=lambda v: parse_timebound(v, "--before"), default=None, metavar="ID OR TIME", help="Filter messages to delete before a message ID, date (2025.05.20) or time (30m, 24h, 7d).")
    p3.add_argument("--dry", action="store_true", help="Show a preview of what would be deleted without actually deleting anything.")
    p3.add_argument("--y", action="store_true", help="Skip the confirmation prompt, recommended for --server runs since otherwise you're prompted once per channel.")

    args = parser.parse_args()


    if args.command == "scrape":
        if args.list_channels:
            if not args.server:
                parser.error("scrape -h to view instructions.")
        else:
            if not args.channel and not args.server:
                parser.error("scrape -h to view instructions.")

    if args.command == "member":
        if not args.channel and not args.server:
            parser.error("member -h to view instructions.")

    if args.command == "delete":
        if not args.channel and not args.server:
            parser.error("delete -h to view instructions.")

    token = args.token or TOKEN
    token_type = args.token_type or TOKEN_TYPE
    if not token:
        parser.error("No token provided. Use --token your_token, or replace None with 'your_token' in cli.py.")
    if token_type not in ("bot", "session"):
        parser.error("--token-type must be 'session' or 'bot', or set the desidered one to make it default in cli.py.")

    client = StoatClient(token, token_type, args.api_base)

    try:
        me = client.whoami()
        whoami_id = me.get("_id")
        print(f"Authenticated as {me.get('username', '?')} ({whoami_id}) [{token_type} token]")
    except requests.HTTPError as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    if args.command == "scrape":
        if args.list_channels:
            cmd_list_channels(client, args)
            return
        if not args.cdn:
            try:
                args.cdn = client.detect_cdn()
                print(f"Detected CDN: {args.cdn}")
            except Exception as e:
                args.cdn = DEFAULT_CDN
                print(f"Could not detect this CDN instance ({e}), falling back to {DEFAULT_CDN}. Otherwise try --cdn.")
        cmd_scrape(client, args)
    elif args.command == "member":
        if args.download and not args.cdn:
            try:
                args.cdn = client.detect_cdn()
                print(f"Detected CDN: {args.cdn}")
            except Exception as e:
                args.cdn = DEFAULT_CDN
                print(f"Could not detect this CDN instance ({e}), falling back to {DEFAULT_CDN}. Otherwise try --cdn.")
        cmd_scrape_members(client, args)
    elif args.command == "delete":
        if not args.user_id:
            args.user_id = whoami_id
        cmd_delete_msgs(client, args, whoami_id)


if __name__ == "__main__":
    main()
