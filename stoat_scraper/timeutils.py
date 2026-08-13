import argparse
import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone

ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{26}$")
RELATIVE_TIME_RE = re.compile(r"^(\d+)([dhm])$", re.IGNORECASE)


# result of parsing a --after and --before value
TimeBound = namedtuple("TimeBound", ["dt", "ulid"])


# message and user id are ulids, this encodes ts in the first 10 base32 chars
def ulid_to_dt(_id):
    try:
        ms = 0
        for c in _id[:10]:
            ms = ms * 32 + ULID_ALPHABET.index(c.upper())
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except Exception:
        return None


def ts_ulid(_id):
    dt = ulid_to_dt(_id)
    return dt.isoformat() if dt else ""


# builds a ulid to seed pagination when --after and --before receive a date instead of message id
def ulid_to_ms(ms, randomness_char="Z"):
    ms = max(int(ms), 0)
    chars = []
    val = ms
    for _ in range(10):
        chars.append(ULID_ALPHABET[val % 32])
        val //= 32
    return "".join(reversed(chars)) + (randomness_char * 16)


def parse_iso_dt(value):
    if not value:
        return None
    text = value.strip()
    body = text[:-1] + "+00:00" if text.upper().endswith("Z") else text
    try:
        dt = datetime.fromisoformat(body)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --after and --before value parses to timebound so it can use message id, date and time
def parse_timebound(value, flag_name):
    text = value.strip()

    if ULID_RE.match(text):
        dt = ulid_to_dt(text)
        if dt is None:
            raise argparse.ArgumentTypeError(f"{flag_name}: couldn't decode '{value}' as a message ID.")
        return TimeBound(dt=dt, ulid=text)

    m = RELATIVE_TIME_RE.match(text)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        delta = {"d": timedelta(days=amount), "h": timedelta(hours=amount), "m": timedelta(minutes=amount)}[unit]
        return TimeBound(dt=datetime.now(timezone.utc) - delta, ulid=None)

    dt = parse_iso_dt(text)
    if dt is None:
        raise argparse.ArgumentTypeError(f"'{value}' isn't a message ID, date (2025.05.20), or time (30m, 24h, 7d)")
    return TimeBound(dt=dt, ulid=None)


# if timestamp isnt determined, it is not excluded
def within_time_bounds(dt, after_bound, before_bound):
    if dt is None:
        return True
    if after_bound and dt < after_bound.dt:
        return False
    if before_bound and dt > before_bound.dt:
        return False
    return True
