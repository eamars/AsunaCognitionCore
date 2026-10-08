"""Group member lists for the host (0.7.1): who is in each admitted group, not only who spoke.

When the adapter is READY and every EVERY_SECONDS after, it asks the platform which groups this account is in
(`get_group_list`), keeps those the admission policy admits (`Config.route_for_group`: configured routes, or
automatic admission, never a blocked group), fetches each one's members (`get_group_member_list`), keeps only
user_id / nickname / card / role / last_sent_time / join_time, and posts the list to the host
(`POST /v1/channels/<id>/members`) only when it differs from the last one posted (a hash in
`<data>/members/posted.json`). One call per group per round, a pause between groups, no retry loop: a failure is
logged and the next round tries again. The log carries counts, never names.
"""
import hashlib
import json
import os
import threading
import time

EVERY_SECONDS = 6 * 3600
GROUP_PAUSE = 1.0
FIELDS = ("user_id", "nickname", "card", "role", "last_sent_time", "join_time")
MAX_MEMBERS = 5000


def _project(raw):
    out = {key: raw.get(key) for key in FIELDS if isinstance(raw, dict) and raw.get(key) not in (None, "")}
    return out if str(out.get("user_id", "")).isdigit() else None


class Members:
    def __init__(self, cfg, data_dir, onebot, host, counters, log=print, clock=time.time):
        self.cfg, self.onebot, self.host, self.counters, self.log, self.clock = cfg, onebot, host, counters, log, clock
        self.path = os.path.join(data_dir, "members", "posted.json")
        self._lock = threading.Lock()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self.posted = json.load(handle).get("groups") or {}
        except (OSError, ValueError, AttributeError):
            self.posted = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "groups": self.posted}, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def loop(self, stop):
        while not stop.is_set():
            try:
                self.run()
            except Exception as exc:
                self.counters.inc("members_error")
                self.log("MEMBERS_ERROR type=%s" % type(exc).__name__)
            stop.wait(EVERY_SECONDS)

    def groups(self):
        resp = self.onebot.api_call("get_group_list", {}, timeout=20, meta={"members": "groups"})
        data = resp.get("data") if isinstance(resp, dict) else None
        if resp.get("retcode") != 0 or not isinstance(data, list):
            self.log("MEMBERS_GROUPS_REFUSED retcode=%s" % (resp.get("retcode") if isinstance(resp, dict) else "-"))
            return []
        found = []
        for row in data:
            group = str((row or {}).get("group_id") or "")
            if group.isdigit() and self.cfg.route_for_group(group) is not None:
                found.append(group)
        return sorted(set(found))

    def run(self):
        totals = {"groups": 0, "posted": 0, "same": 0, "failed": 0}
        for group in self.groups():
            totals["groups"] += 1
            try:
                resp = self.onebot.api_call("get_group_member_list", {"group_id": int(group)}, timeout=30,
                                            meta={"members": group})
            except Exception as exc:
                totals["failed"] += 1
                self.log("MEMBERS_API_ERROR group=%s type=%s" % (group, type(exc).__name__))
                continue
            data = resp.get("data") if isinstance(resp, dict) else None
            if resp.get("retcode") != 0 or not isinstance(data, list):
                totals["failed"] += 1
                self.log("MEMBERS_API_REFUSED group=%s retcode=%s" % (group, resp.get("retcode")))
                continue
            members = sorted((m for m in map(_project, data) if m), key=lambda m: str(m["user_id"]))[:MAX_MEMBERS]
            digest = hashlib.sha256(json.dumps(members, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if self.posted.get(group) == digest:
                totals["same"] += 1
            else:
                res = self.host.post_members({"group_id": group, "members": members,
                                              "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))})
                if res.kind == "accepted":
                    with self._lock:
                        self.posted[group] = digest
                        self._save()
                    totals["posted"] += 1
                else:
                    totals["failed"] += 1
                    self.log("MEMBERS_POST_FAILED group=%s http=%s body=%s"
                             % (group, res.code, json.dumps(res.obj, ensure_ascii=False)[:200]))
            time.sleep(GROUP_PAUSE)
        for key, value in totals.items():
            self.counters.inc("members_" + key, value)
        self.log("MEMBERS groups=%d posted=%d unchanged=%d failed=%d"
                 % (totals["groups"], totals["posted"], totals["same"], totals["failed"]))
        return totals
