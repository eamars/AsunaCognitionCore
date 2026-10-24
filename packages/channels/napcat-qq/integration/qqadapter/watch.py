"""Who is doing what, and the watchdog (ADR-095 §5.5, §5.7).

Each worker records the item in its hands: its lane (`inbound`, `chat`, `bulk`, `receipts`), its conversation, the
item's id, the stage it is in, when it started and its budget. The budget is the sum of the item's own steps'
deadlines plus a margin, so an item still inside its deadlines never reaches it: only a bug can.

A watchdog pass (`check`, from the health loop every few seconds) marks an item past its budget stuck: one log line,
one fault (lane, the stage it is in, `stuck`), one row in `stuck.jsonl`. Its place in its lane's pool is freed, so the
other conversations keep their workers. The item itself is held: a Python thread can't be killed, so its thread goes
on and its conversation waits for it; setting it aside would let an inbound line arrive after the lines behind it, or
mark failed a line that QQ shows. When the thread comes back, `stuck.jsonl` gets a second row with how long it took.

Stage times: `end` returns how long each stage took, for the line's journal row.
"""
import threading
import time

INBOUND_BASE = 120.0         # the peer (two lookups, 3 s each), forwards (forward.MAX_FETCHES x 8 s), her role (5 s),
                             # the post 12 s and its one repost, and a margin
PER_MENTION = 3.0            # each person a line mentions is looked up (3 s)
PER_VOICE = 210.0            # each voice: fetched from NapCat (10 s), then the host's answer (POST_TIMEOUT 200 s)
CHAT_BUDGET = 150.0          # fetch 30 s, send 15 s, verify about 12 s, the receipt's tries about 43 s; under the host's 300 s
FILE_MARGIN = 60.0           # on top of a file's own deadlines (outbound.file_budget)
RECEIPT_BUDGET = 15.0        # one receipt posted to the host (12 s)


def inbound_budget(envelope, voices):
    """One try of an inbound line: its base, its mentions and its voices."""
    mentions = envelope.get("mentioned_account_ids") if isinstance(envelope, dict) else None
    return INBOUND_BASE + PER_MENTION * len(mentions or []) + PER_VOICE * voices


def duration(seconds):
    """Seconds for reading: 42s, 1m40s, 2h5m."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%ds" % (seconds // 60, seconds % 60)
    return "%dh%dm" % (seconds // 3600, seconds % 3600 // 60)


class Job:
    __slots__ = ("lane", "conversation", "item", "budget", "started", "stage", "stage_at", "stages", "stuck", "size")

    def __init__(self, lane, conversation, item, budget, now, size=None):
        self.lane, self.conversation, self.item, self.budget = lane, conversation, item, budget
        self.started = self.stage_at = now
        self.stage, self.stages, self.stuck, self.size = "start", {}, False, size


class Watch:
    def __init__(self, journal, faults, counters, log=print, clock=time.monotonic):
        self.journal, self.faults, self.counters, self.log, self.clock = journal, faults, counters, log, clock
        self._jobs = {}              # thread ident -> its Job
        self._lock = threading.Lock()
        self.stuck_total = 0
        self.last_stuck = None       # the latest stuck item, for the STATUS line

    def begin(self, lane, conversation, item, budget, size=None):
        """The calling thread takes up an item; `end` puts it down."""
        with self._lock:
            self._jobs[threading.get_ident()] = Job(lane, conversation, item, budget, self.clock(), size)

    def stage(self, name):
        """The calling thread's item enters a stage (nothing when it has none)."""
        with self._lock:
            job = self._jobs.get(threading.get_ident())
            if job is not None:
                self._close_stage(job, self.clock())
                job.stage = name

    def stages(self):
        """How long each stage of the calling thread's item took so far, in seconds."""
        with self._lock:
            job = self._jobs.get(threading.get_ident())
            if job is None:
                return {}
            now = self.clock()
            return dict(job.stages, **{job.stage: round(job.stages.get(job.stage, 0.0) + now - job.stage_at, 3)})

    def end(self):
        """The calling thread puts its item down; returns its stage times. A stuck item that comes back is told."""
        with self._lock:
            job = self._jobs.pop(threading.get_ident(), None)
            if job is None:
                return {}
            now = self.clock()
            self._close_stage(job, now)
        if job.stuck:
            self.log("STUCK_ENDED lane=%s item=%s after=%s" % (job.lane, job.item, duration(now - job.started)))
            self._journal({"event": "ended", "lane": job.lane, "conversation": job.conversation, "item": job.item,
                           "after_s": round(now - job.started, 1), "stages": job.stages})
        return dict(job.stages)

    @staticmethod
    def _close_stage(job, now):
        job.stages[job.stage] = round(job.stages.get(job.stage, 0.0) + now - job.stage_at, 3)
        job.stage_at = now

    def check(self):
        """The watchdog pass: each item past its budget is marked stuck, once. Returns the newly stuck ones."""
        now, found = self.clock(), []
        with self._lock:
            for job in self._jobs.values():
                if not job.stuck and now - job.started > job.budget:
                    job.stuck = True
                    found.append((job, now - job.started))
        for job, age in found:
            self.stuck_total += 1
            self.last_stuck = (job.lane, job.conversation, job.item, job.stage)
            try:
                self.counters.inc("lane_stuck")
                self.faults.add(job.lane, job.stage, "stuck")
                self.log("STUCK lane=%s item=%s stage=%s age=%s budget=%s (its place is freed; the item is held)"
                         % (job.lane, job.item, job.stage, duration(age), duration(job.budget)))
            except Exception:
                pass                     # telling it never stops the watchdog from freeing the place
            self._journal({"event": "stuck", "lane": job.lane, "conversation": job.conversation, "item": job.item,
                           "stage": job.stage, "age_s": round(age, 1), "budget_s": job.budget})
        return [job for job, _age in found]

    def _journal(self, row):
        try:
            self.journal.append("stuck.jsonl", dict(row, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        except Exception as exc:
            self.log("STUCK_JOURNAL_ERROR type=%s" % type(exc).__name__)

    def thread_stuck(self, ident):
        """Whether the item of this thread is stuck (its place in the pool is free)."""
        with self._lock:
            job = self._jobs.get(ident)
            return bool(job and job.stuck)

    def stuck_count(self, lane):
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.lane == lane and job.stuck)

    def conversation_stuck(self, lane, conversation):
        with self._lock:
            return any(job.stuck for job in self._jobs.values()
                       if job.lane == lane and job.conversation == conversation)

    def view(self, lane=None):
        """The items in hand, oldest first: dicts with lane, conversation, item, stage, age_s, budget_s, stuck."""
        now = self.clock()
        with self._lock:
            jobs = [job for job in self._jobs.values() if lane is None or job.lane == lane]
            return [{"lane": job.lane, "conversation": job.conversation, "item": job.item, "stage": job.stage,
                     "age_s": round(now - job.started, 1), "budget_s": job.budget, "stuck": job.stuck,
                     **({"bytes": job.size} if job.size is not None else {})}
                    for job in sorted(jobs, key=lambda job: job.started)]
