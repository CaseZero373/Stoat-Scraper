import requests
import time
import random

RATE_LIMIT_SAFETY_DELAY = 0.35

def paced_sleep():
    time.sleep(RATE_LIMIT_SAFETY_DELAY + random.uniform(0, 0.15)) # adding a small time between the requests to be "polite"


# mainly revolt rest api handler for auth headers and retries on rate limit
class StoatClient:
    def __init__(self, token, token_type, api_base):
        self.token = token
        self.token_type = token_type
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        if token_type == "bot":
            self.session.headers["x-bot-token"] = token
        else:
            self.session.headers["x-session-token"] = token
        self.session.headers["Content-Type"] = "application/json"

    def request(self, method, path, **kwargs):
        url = f"{self.api_base}{path}"
        attempt = 0
        while True:
            try:
                resp = self.session.request(method, url, timeout=(10, 60), **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                attempt += 1
                if attempt > max_retries:
                    raise
                wait = min(2 ** attempt, 30)  # exponential backoff, capped at 30s
                print(f"  network error ({e.__class__.__name__}), retrying in {wait}s... ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 429:
                retry_after = 1.0
                try:
                    body = resp.json()
                    retry_after = float(body.get("retry_after", 1000)) / 1000.0
                except Exception:
                    pass
                time.sleep(max(retry_after, 0.5))
                continue
            return resp

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def delete(self, path):
        return self.request("DELETE", path)

    def whoami(self):
        r = self.get("/users/@me")
        r.raise_for_status()
        return r.json()

    def fetch_msgs(self, channel_id, before=None, limit=100):
        params = {"limit": limit, "sort": "Latest"}
        if before:
            params["before"] = before
        r = self.get(f"/channels/{channel_id}/messages", params=params)
        r.raise_for_status()
        return r.json()

    # revolt only goes backwards with "before" so this keeps asking for the next 100 older msgs till it runs out, start_before optionally seeds the initial cursor (used by --before to skip to past newer pages)
    def iter_msgs(self, channel_id, hard_limit=None, start_before=None):
        before = start_before
        fetched = 0
        first = True
        while True:
            if not first:
                time.sleep(RATE_LIMIT_SAFETY_DELAY)
            first = False
            batch = self.fetch_msgs(channel_id, before=before)
            if not batch:
                return
            for msg in batch:
                yield msg
                fetched += 1
                if hard_limit and fetched >= hard_limit:
                    return
            before = batch[-1]["_id"]
            if len(batch) < 100:
                return

    def delete_msg(self, channel_id, message_id):
        return self.delete(f"/channels/{channel_id}/messages/{message_id}")

    def fetch_server_members(self, server_id):
        r = self.get(f"/servers/{server_id}/members")
        r.raise_for_status()
        return r.json()

    def fetch_server_member(self, server_id, user_id):
        r = self.get(f"/servers/{server_id}/members/{user_id}")
        r.raise_for_status()
        return r.json()

    def fetch_server(self, server_id):
        r = self.get(f"/servers/{server_id}")
        r.raise_for_status()
        return r.json()

    def fetch_channel(self, channel_id):
        r = self.get(f"/channels/{channel_id}")
        r.raise_for_status()
        return r.json()

    def fetch_user(self, user_id):
        r = self.get(f"/users/{user_id}")
        r.raise_for_status()
        return r.json()

    def fetch_user_profile(self, user_id):
        r = self.get(f"/users/{user_id}/profile")
        r.raise_for_status()
        return r.json()

    # server object returns channel ID, this fetches each channel individually to get name and type, obvs slow on big servers
    def fetch_server_channels(self, server_id):
        server = self.fetch_server(server_id)
        channel_ids = server.get("channels", [])
        channels = []
        for cid in channel_ids:
            try:
                channels.append(self.fetch_channel(cid))
            except requests.HTTPError as e:
                channels.append({"_id": cid, "name": "(inaccessible)", "channel_type": "?", "_error": str(e)})
            paced_sleep()
        return channels

    # instamces can self host their CDN other than the default autumn.revolt.chat, this pulls the real url from the instance config so attachment links resolves
    def detect_cdn(self):
        r = self.get("/")
        r.raise_for_status()
        config = r.json()
        features = config.get("features", {})
        autumn = features.get("autumn", {})
        url = autumn.get("url")
        if not url:
            raise ValueError("instance config has no features.autumn.url")
        return url.rstrip("/")
