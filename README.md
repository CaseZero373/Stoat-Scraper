# Stoat-Scraper

A command-line tool for [Stoat](https://stoat.chat/)/[Revolt](https://revolt.chat) that can:
- **scrape** — messages and attachments from a channel or server
- **member** — extract the member list from a server or group
- **delete** — delete messages sent on a channel or across a server

It talks to the official Revolt REST API using your own session token or a bot token.

## Requirements

- Python 3.9+
- `requests` (`pip install requests`)

## Authentication

You need either:
- a **session token** from your own account, or
- a **bot token** with the `ManageMessages` permission enabled to delete messages from other users

To get your session token:
1. Open Stoat web client
2. Press F12 to open Developer Tools
3. Go to the Network tab
4. Click on the HXR filter
5. Refresh the page
6. By clicking on a request a Details tab will open in a Headers filter by default, in the Request Headers look at the last line for the "X-Session-Token", if not there click on another request
6. Once found right click to "Copy Value"

to get your bot token:
1. Open your Stoat client
2. Go in Settings > My Bots > select your bot > Copy Token

Provide it by either using --token and --token-type everytime:

```bash
python main.py --token YOUR_TOKEN --token-type session scrape --channel ...
```

or by editing `main.py` so you can skip it:

```python
TOKEN = None # replace None with "your_token"
TOKEN_TYPE = "session"  # replace 'session' with 'bot' if your token is a bot one 
```

## Commands

In order to get the IDs you have to enable this:
1. Enable "Show 'copy ID' in context menus" in Settings > Advanced
2. Right click on the target name and select "Copy Server ID"

### `scrape` — export messages and media from a single channel, or across the server

```bash
# a single channel
python main.py scrape --channel CHANNEL_ID --output messages.json

# every channel in a server, outputs one file each
python main.py scrape --server SERVER_ID

# list all channel IDs in a server
python main.py scrape --server SERVER_ID --list

# the 200 newest messages, downloading their attachments, sent before 30m that are also after 24h
python main.py scrape --channel CHANNEL_ID --limit 200 --download --after 24h --before 30m
```

| Flag | Description |
|---|---|
| `--server` | Scrape all the channels across the whole server. |
| `--channel` | Scrape a single channel. |
| `--user-id` | Only includes messages sent from this user. |
| `--limit` | Max messages to fetch, if using `--server` it applies per channel. |
| `--list` | When used with `--server` list all channel names and IDs instead of scraping. |
| `--match` | Only include messages whose content matches this. |
| `--count` | Add an author message count, requires walking the full channel (ignores `--limit` while counting, then trims after). Resets per channel on server scrapes. |
| `--download` | Download matched attachments into a `<output>_media/` folder. |
| `--only` | Filter messages containing matching attachment type (images, videos, audio, files, links). |
| `--cdn` | Manually set the CDN base URL (auto-detected from the instance by default). |
| `--after` | Filter messages sent after a point set by message ID, date (2025.05.20) or time (30m, 24h, 7d). |
| `--before` | Filter messages sent before a point set by message ID, date (2025.05.20) or time (30m, 24h, 7d). |
| `--combine` | Merge all channels into the single `--output` file (tagged with `channel_id`/`channel_name`) instead of one file per channel. |
| `--output` | Outputs file in `.json` or `.csv`, if not used returns `messages.json`. When scraping a server, output is used as the base name for each file per channel. |

### `member` — extracts the member list from a server or group

```bash
# every member of a server
python main.py member --server SERVER_ID

# just one member and downloading its pfp, banner and server pfp if present (works with briged users too)
python main.py member --server SERVER_ID --user-id USER_ID --download

# every member in a group
python main.py member --channel CHANNEL_ID

# every member who joined in the last 24h
python main.py member --channel CHANNEL_ID --after 24h
```

| Flag | Description |
|---|---|
| `--server` | Scrape a server member list. |
| `--channel` | Scrape a group recipient list. |
| `--user-id` | Only scrape this one user. |
| `--limit` | Max members to scrape. |
| `--download` | Download avatar, banner, and server avatar into a folder named after `--output`. |
| `--cdn` | Manually set the CDN base URL (auto-detected from the instance by default). |
| `--after` | Filter members who joined after a date (2025.05.20) or time (30m, 24h, 7d). |
| `--before` | Filter members who joined before a date (2025.05.20) or time (30m, 24h, 7d). |
| `--output` | Outputs file in `.json` or `.csv`, if not used returns `members.json`. |

### `delete` — delete messages sent in a server, channel, group or dm

Warning: if the session token of your account has perms to delete messages in a server you are targetting, be sure to specify the user

```bash
# delete messages in the channel
python main.py delete --channel CHANNEL_ID

# delete messages in the server
python main.py delete --server SERVER_ID

# delete the 20 newest messages sent before 30m that are also after 24h
python main.py delete --channel CHANNEL_ID --limit 20 --after 24h --before 30m

# delete messages sent by a user across an entire server (needs a bot token and ManageMessages perms)
python main.py delete --server SERVER_ID --user-id USER_ID
```

| Flag | Description |
|---|---|
| `--server` | Delete across every channel in the server. |
| `--channel` | Delete messages in one channel, DM or group. |
| `--user-id` | Whose messages to delete, with a session token you can delete your own messages or the ones you are permitted by a server, same thing with a bot token with `ManageMessages` permission enabled. |
| `--limit` | Set how many messages to delete. |
| `--after` | Filter messages to delete after a message ID, date (2025.05.20) or time (30m, 24h, 7d). |
| `--before` | Filter messages to delete before a message ID, date (2025.05.20) or time (30m, 24h, 7d). |
| `--dry` | Show a preview of what would be deleted without actually deleting anything. |
| `--y` | Skip the confirmation prompt, recommended for `--server` runs since otherwise you're prompted once per channel. |

## Output format

- **JSON** (default): one object per row, fields grouped and ordered for readability.
- **CSV**: same data but each written in different strings.

`scrape` json:

```bash
  {
    "message_id": "...", "author_id": "...",
    "author_username": "user#1234", "author_display_name": "john", "author_server_nickname": "john stoat",
    "author_bot": false, "is_masquerade": false, "masquerade_name": "", "masquerade_avatar": "",
    "content": "Hello World",
    "attachments": [],
    "links": [],
    "reactions": [],
    "referenced_message_ids": [],
    "approx_timestamp": "2025-05-20T12:30:00.580000+00:00", "was_edited": false, "edited_at": "", "scraped_at": "2025-05-20T15:30:00.580000+00:00"
  }
```

`member` json:

```bash
  {
    "user_id": "", "bot": false,
    "username": "user#1234", "display_name": "john", "server_nickname": "john stoat",
    "status_text": "", "status_presence": "Online",
    "bio": "Hello World",
    "roles": "",
    "account_created": "2025-05-20T12:30:00.580000+00:00", "joined_server": "",
    "scraped_at": "2025-05-20T15:30:00.580000+00:00"
  }
```

## Donations

For XMR donations: 46PwgZ2m49rfpAQzXdoPcx4tbUnXS7VKpDToESwcFZrLdQADP5Cdn3HFGLqibzrYs3ene1s5sVpNtBEc7WvdjJb8Cm4MURU

## License

[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.fr.html)

Built for educational purposes only.
