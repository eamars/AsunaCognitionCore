"""Her own mute in each admitted group, told to the host (`POST /v1/channels/<id>/own_mute`).

It is learnt three ways, each posted at once from this module's own thread:
- a `group_ban` notice (`ban` / `lift_ban`) about her own account, or about the whole group (`user_id` 0), in an
  admitted group: `notice_body` turns it into a state report (until = notice time + duration, the operator's
  account); every other notice is still dropped;
- a send the platform refused because she is muted (`outbound.platform_muted`): that group is looked at at once;
- at start and on reconnect, each admitted group not looked at within CHECK_EVERY_SECONDS is looked at, one at a time
  with GROUP_PAUSE between, so the platform sees no burst. When each group was last looked at is kept in
  `<data>/mutes/checked.json`, so frequent restarts do not ask again.

A look is two read-only calls: `get_group_member_info` for her own account (`no_cache`; `shut_up_timestamp` is when
her mute ends, 0 when there is none) and `get_group_info` (`no_cache`; `group_all_shut` is nonzero while the whole
group is muted). Nothing here sends, mutes or unmutes. The log carries counts, outcomes and seconds.
"""
import json
import os
import queue
import threading
import time

CHECK_EVERY_SECONDS = 6 * 3600    # a group looked at this recently is not asked again at start or reconnect
GROUP_PAUSE = 1.0                 # seconds between two groups' looks
CALL_TIMEOUT = 10.0
POST_TRIES = 5
RETRY_WAIT = 5.0


def notice_body(event, cfg):
    """The state report for a mute notice about her (or the whole group) in an admitted group, else None."""
    if not isinstance(event, dict) or event.get("post_type") != "notice" or event.get("notice_type") != "group_ban":
        return None
    account = str(cfg.napcat["account_id"])
    if str(event.get("self_id")) != account or event.get("sub_type") not in ("ban", "lift_ban"):
        return None
    group = str(event.get("group_id") or "")
    user = str(event.get("user_id") if event.get("user_id") is not None else "")
    if user not in (account, "0") or cfg.route_for_group(group) is None:
        return None
    whole = user == "0"
    body = {"group_id": group, "source": "notice", "muted": event["sub_type"] == "ban", "whole_group": whole}
    operator = str(event.get("operator_id") or "")
    if operator.isdigit() and operator not in ("0", account):
        body["operator_id"] = operator
    at, duration = event.get("time"), event.get("duration")
    if type(at) is int and at > 0:
        body["at"] = at
        if body["muted"] and not whole and type(duration) is int and duration > 0:
            body["until"] = at + duration
    return body


def look_body(group, member, info, now):
    """The state report from one look, or None when either answer is missing."""
    if not (isinstance(member, dict) and member.get("retcode") == 0 and isinstance(member.get("data"), dict)):
        return None
    if not (isinstance(info, dict) and info.get("retcode") == 0 and isinstance(info.get("data"), dict)):
        return None
    try:
        ends = int(member["data"].get("shut_up_timestamp") or 0)
    except (TypeError, ValueError):
        return None
    body = {"group_id": group, "source": "lookup", "muted": False, "whole_group": False}
    if ends > now:
        body.update(muted=True, until=ends)
    elif info["data"].get("group_all_shut") not in (None, 0, False, "0"):
        body.update(muted=True, whole_group=True)
    return body


class Mutes:
    def __init__(self, cfg, data_dir, onebot, host, counters, groups, log=print, clock=time.time, sleep=time.sleep):
        self.cfg, self.onebot, self.host, self.counters, self.log = cfg, onebot, host, counters, log
        self.groups, self.clock, self.sleep = groups, clock, sleep
        self.account = str(cfg.napcat["account_id"])
        self.path = os.path.join(data_dir, "mutes", "checked.json")
        self.jobs = queue.Queue()
        self._lock = threading.Lock()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self.checked = {str(k): float(v) for k, v in (json.load(handle).get("groups") or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            self.checked = {}

    # ---- requests (any thread) ------------------------------------------
    def notice(self, body):
        self.jobs.put(("post", body, 0))

    def look_now(self, group):
        self.jobs.put(("look", str(group), 0))

    def sweep(self, reason):
        self.jobs.put(("sweep", reason, 0))

    # ---- the thread -------------------------------------------------------
    def loop(self, stop):
        while not stop.is_set():
            try:
                job = self.jobs.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.run(job)
            except Exception as exc:
                self.counters.inc("mutes_error")
                self.log("MUTES_ERROR type=%s" % type(exc).__name__)

    def run(self, job):
        kind, value, tries = job
        if kind == "post":
            return self.post(value, tries)
        if kind == "look":
            return self.look(value)
        return self.sweep_now(value)

    def _mark(self, group):
        with self._lock:
            self.checked[group] = self.clock()
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "groups": self.checked}, handle, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, self.path)

    def post(self, body, tries=0):
        """'posted', 'refused' (the host will not take it: nothing to do there) or 'retry'."""
        res = self.host.post_own_mute(body)
        if res.kind == "accepted":
            self.counters.inc("mutes_posted")
            self._mark(body["group_id"])
            self.log("OWN_MUTE group=%s source=%s muted=%s whole_group=%s until=%s status=%s"
                     % (body["group_id"], body["source"], body["muted"], body.get("whole_group"),
                        body.get("until", "-"), (res.obj or {}).get("status")))
            return "posted"
        if res.kind == "reject":
            self.counters.inc("mutes_refused")
            self._mark(body["group_id"])
            self.log("OWN_MUTE_REFUSED group=%s http=%s error=%s"
                     % (body["group_id"], res.code, str((res.obj or {}).get("error", "") if isinstance(res.obj, dict)
                                                        else "")[:160]))
            return "refused"
        if body["source"] == "notice" and tries + 1 < POST_TRIES:
            self.sleep(RETRY_WAIT)
            self.jobs.put(("post", body, tries + 1))
        self.counters.inc("mutes_post_retry")
        self.log("OWN_MUTE_RETRY group=%s http=%s error=%s" % (body["group_id"], res.code, res.error))
        return "retry"

    def look(self, group):
        """Read her mute in one group and post it; 'muted', 'free', or why it could not."""
        meta = {"mutes": group}
        try:
            member = self.onebot.api_call("get_group_member_info", {"group_id": int(group), "user_id": int(self.account),
                                                                   "no_cache": True}, timeout=CALL_TIMEOUT, meta=meta)
            info = self.onebot.api_call("get_group_info", {"group_id": int(group), "no_cache": True},
                                        timeout=CALL_TIMEOUT, meta=meta)
        except Exception as exc:
            self.counters.inc("mutes_look_failed")
            self.log("OWN_MUTE_LOOK_FAILED group=%s type=%s" % (group, type(exc).__name__))
            return "failed"
        body = look_body(group, member, info, self.clock())
        if body is None:
            self.counters.inc("mutes_look_failed")
            self.log("OWN_MUTE_LOOK_REFUSED group=%s retcode=%s/%s"
                     % (group, (member or {}).get("retcode"), (info or {}).get("retcode")))
            return "failed"
        posted = self.post(body)
        if posted != "posted":
            return posted
        return "muted" if body["muted"] else "free"

    def sweep_now(self, reason):
        started, now = self.clock(), self.clock()
        totals = {"groups": 0, "looked": 0, "skipped": 0, "muted": 0, "failed": 0}
        first = True
        for group in self.groups():
            totals["groups"] += 1
            if now - self.checked.get(group, 0.0) < CHECK_EVERY_SECONDS:
                totals["skipped"] += 1
                continue
            if not first:
                self.sleep(GROUP_PAUSE)
            first = False
            outcome = self.look(group)
            totals["looked"] += 1
            if outcome == "muted":
                totals["muted"] += 1
            elif outcome not in ("free", "refused"):
                totals["failed"] += 1
        for key, value in totals.items():
            self.counters.inc("mutes_sweep_" + key, value)
        self.log("OWN_MUTE_SWEEP reason=%s groups=%d looked=%d skipped=%d muted=%d failed=%d seconds=%.1f"
                 % (reason, totals["groups"], totals["looked"], totals["skipped"], totals["muted"], totals["failed"],
                    self.clock() - started))
        return totals
