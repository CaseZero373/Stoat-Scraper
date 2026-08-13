import csv
import json

SCRAPE_LAYOUT = [
    ("channel_id", "channel_name"),
    ("message_id", "author_id"),
    ("author_username", "author_display_name", "author_server_nickname"),
    ("author_bot", "is_masquerade", "masquerade_name", "masquerade_avatar"),
    "content",
    "attachments",
    "links",
    "reactions",
    "referenced_message_ids",
    "message_count",
    ("approx_timestamp", "was_edited", "edited_at", "scraped_at"),
]

MEMBER_LAYOUT = [
    ("user_id", "bot"),
    ("username", "display_name", "server_nickname"),
    ("status_text", "status_presence"),
    "bio",
    "roles",
    ("account_created", "joined_server"),
    "downloaded_media",
    "scraped_at",
]

# forces objects to next line 
MULTILINE_LAYOUT = {"attachments", "links", "reactions"}


def write_json(rows, path, layout):
    with open(path, "w", encoding="utf-8") as f:
        f.write(layout_json(rows, layout))


def layout_json(rows, layout, indent=2):
    pad = " " * indent
    pad2 = " " * (indent * 2)
    out = ["["]

    for i, row in enumerate(rows):
        out.append(pad + "{")
        line_parts = []

        for group in layout:
            keys = group if isinstance(group, tuple) else (group,)
            parts = []
            for key in keys:
                if key not in row:
                    continue
                value_str = format_value(key, row[key], pad2, indent)
                parts.append(f"{json.dumps(key, ensure_ascii=False)}: {value_str}")
            if parts:
                line_parts.append(pad2 + ", ".join(parts))

        out.append(",\n".join(line_parts))
        out.append(pad + "}" + ("," if i < len(rows) - 1 else ""))

    out.append("]")
    return "\n".join(out)


def format_value(key, value, pad2, indent):
    pad3 = " " * (indent * 2 + indent)  # one level deeper than the row's fields

    if key in MULTILINE_LAYOUT and isinstance(value, list) and value:
        items = [json.dumps(v, ensure_ascii=False, separators=(", ", ": ")) for v in value]
        inner = (",\n" + pad3).join(items)
        return "[\n" + pad3 + inner + "\n" + pad2 + "]"

    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def write_csv(rows, path, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
