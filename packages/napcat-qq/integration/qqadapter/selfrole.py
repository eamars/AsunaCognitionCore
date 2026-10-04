"""Her own role in each group (owner / admin / member), so the host knows what she may do there.

Asked from NapCat with get_group_member_info for the logged-in account only, cached per group for a few
minutes, and carried inside `raw` as `asuna_self: {"role": ...}` on that group's events.  A platform
that does not answer leaves the last known role (or none); the message is never held for it.
"""
import time

ROLES = ("owner", "admin", "member")
TTL_SECONDS = 600


class SelfRoles:
    def __init__(self, account, ttl=TTL_SECONDS, api_timeout=5.0, counters=None):
        self.account = str(account)
        self.ttl = float(ttl)
        self.api_timeout = float(api_timeout)
        self.counters = counters
        self.cache = {}

    def role(self, api, group_id):
        group_id = str(group_id or "")
        if not group_id.isdigit():
            return None
        known = self.cache.get(group_id)
        now = time.monotonic()
        if known and now - known[1] < self.ttl:
            return known[0]
        try:
            resp = api.api_call("get_group_member_info",
                                {"group_id": int(group_id), "user_id": int(self.account), "no_cache": False},
                                timeout=self.api_timeout)
        except Exception:
            if self.counters is not None:
                self.counters.inc("self_role_errors")
            return known[0] if known else None
        data = resp.get("data") if isinstance(resp, dict) and resp.get("retcode") == 0 else None
        role = str((data or {}).get("role") or "").strip().lower()
        if role in ROLES and str((data or {}).get("user_id") or "") == self.account:
            self.cache[group_id] = (role, now)
            return role
        return known[0] if known else None

    def attach(self, envelope, api):
        """Put her current role in this group into the event's raw block (group events only)."""
        role = self.role(api, envelope.get("group_id"))
        if role:
            raw = envelope.get("raw")
            if not isinstance(raw, dict):
                raw = envelope["raw"] = {}
            raw["asuna_self"] = {"role": role}
        return role
