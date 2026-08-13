import requests


# to avoid getting the display name as the username
def format_username(user):
    username = user.get("username", "")
    discriminator = user.get("discriminator")
    if discriminator:
        return f"{username}#{discriminator}"
    return username


# caches user and member lookups to avoid fetching the same author for every msg sent
class AuthorInfoCache:
    def __init__(self, client, server_id=None):
        self.client = client
        self.server_id = server_id
        self._users = {}
        self.member_map = None # remember

    def member_mapping(self):
        if self.member_map is not None:
            return
        self.member_map = {}
        if not self.server_id:
            return
        try:
            data = self.client.fetch_server_members(self.server_id)
            members = data.get("members", data if isinstance(data, list) else [])
            for m in members:
                member_id = m.get("_id", {})
                user_id = member_id.get("user") if isinstance(member_id, dict) else m.get("id")
                if user_id:
                    self.member_map[user_id] = m
        except requests.HTTPError:
            pass

    def get(self, user_id):
        if user_id in self._users:
            return self._users[user_id]

        info = {
            "id": user_id,
            "username": "",
            "plain_username": "",
            "display_name": "",
            "server_nickname": "",
            "bot": False,
        }

        try:
            user = self.client.fetch_user(user_id)
            info["username"] = format_username(user)
            info["plain_username"] = user.get("username", "")
            info["display_name"] = user.get("display_name") or ""
            info["bot"] = bool(user.get("bot"))
        except requests.HTTPError:
            pass

        self.member_mapping()
        member = self.member_map.get(user_id)
        if member:
            info["server_nickname"] = member.get("nickname") or ""

        self._users[user_id] = info
        return info
