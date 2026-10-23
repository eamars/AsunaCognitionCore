"""This adapter's lane faults, counted by signature and hour and posted to the host (ADR-095 §5.6, step 1).

A signature is what failed, never the message: the lane (`inbound`, `chat`, `bulk`, `receipts`), the stage and the
error class, each a name of A-Z a-z 0-9 _ . : - only (anything else becomes `_`, so no text of a line or an answer
gets in). `add` counts one where a line or a receipt is set aside or a send fails in this adapter, and never raises;
the counts not yet taken by the host are kept in `faults_pending.json` beside the journal, so a restart loses none;
`loop` posts them every EVERY_SECONDS (RETRY_SECONDS after a failed post). A batch the host refuses (its shape or
fields out of what it takes) is written to `journal/faults_rejected.jsonl` and dropped, so it never holds the ones
after it. Only metadata reaches the host.
"""
import json
import os
import re
import threading
import time

EVERY_SECONDS = 300
RETRY_SECONDS = 60
NAME_CHARS = 80
MAX_ROWS = 200
MAX_COUNT = 100000
NOT_A_NAME = re.compile(r"[^A-Za-z0-9_.:-]")
FIELDS = ("lane", "stage", "error", "hour", "count")


def name(value):
    """A class name from any value: only A-Z a-z 0-9 _ . : -, at most NAME_CHARS."""
    return NOT_A_NAME.sub("_", str(value))[:NAME_CHARS] or "_"


def code(error):
    """An error's code alone (`CODE` of `CODE: words`), never its words."""
    return name(str(error or "-").split(":", 1)[0].strip() or "-")


class Faults:
    def __init__(self, data_dir, host, counters, log=print, clock=time.time, journal=None):
        self.path = os.path.join(data_dir, "faults_pending.json")
        self.host, self.counters, self.log, self.clock, self.journal = host, counters, log, clock, journal
        self.lock = threading.Lock()
        self.pending = {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, ValueError):
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if (isinstance(row, dict) and set(row) == set(FIELDS) and all(isinstance(row[f], str) for f in FIELDS[:4])
                    and isinstance(row["count"], int) and row["count"] > 0):
                self.pending[self._key(row)] = dict(row)

    @staticmethod
    def _key(row):
        return (row["lane"], row["stage"], row["error"], row["hour"])

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(list(self.pending.values()), handle, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add(self, lane, stage, error):
        """Count one fault of this signature in the current UTC hour. Counting never stops what counts it."""
        try:
            row = {"lane": name(lane), "stage": name(stage), "error": name(error),
                   "hour": time.strftime("%Y-%m-%dT%H", time.gmtime(self.clock()))}
            with self.lock:
                kept = self.pending.setdefault(self._key(row), dict(row, count=0))
                kept["count"] += 1
                try:
                    self._save()
                except OSError:
                    pass                   # still counted in memory; the next change writes it
            self.counters.inc("faults_counted")
        except Exception:                  # noqa: BLE001 a fault count is never a fault of the lane
            self.counters.inc("faults_count_failed")

    def post(self):
        """Post the pending counts; the host's answer takes them off. True when nothing is left to post."""
        with self.lock:
            rows = [dict(row, count=min(row["count"], MAX_COUNT)) for row in list(self.pending.values())[:MAX_ROWS]]
        if not rows:
            return True
        res = self.host.post_faults({"counts": rows})
        error = res.obj.get("error") if isinstance(res.obj, dict) else None
        refused = res.kind == "reject" and res.code not in (403, 404) and error != "CHANNEL_AUTH_REQUIRED"
        if res.kind not in ("ok", "accepted") and not refused:
            self.counters.inc("faults_post_failed")
            return False
        if refused:
            # the host does not take this batch as it is: it is kept in the journal, and the rest goes on
            self.counters.inc("faults_rejected")
            self.log("FAULTS_REJECTED rows=%d http=%s error=%s" % (len(rows), res.code, code(error)))
            if self.journal is not None:
                self.journal.append("faults_rejected.jsonl", {"rows": rows, "http": res.code, "error": code(error)})
        with self.lock:
            for row in rows:
                kept = self.pending.get(self._key(row))
                if kept is None:
                    continue
                kept["count"] -= row["count"]             # what came meanwhile stays for the next post
                if kept["count"] <= 0:
                    del self.pending[self._key(row)]
            try:
                self._save()
            except OSError:
                pass
        if not refused:
            self.counters.inc("faults_posted", len(rows))
        return not self.pending

    def loop(self, stop):
        while not stop.is_set():
            try:
                ok = self.post()
            except Exception as exc:
                ok = False
                self.counters.inc("faults_post_failed")
                self.log("FAULTS_POST_ERROR type=%s" % type(exc).__name__)
            stop.wait(EVERY_SECONDS if ok else RETRY_SECONDS)
