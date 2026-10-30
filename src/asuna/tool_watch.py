"""Every tool call of both brains, timed where the worker dispatches it (native_worker.py): the calls in flight, one
`tool.time` audit row as each ends, and a watchdog that records a call running past its limit, once.

- `Calls.timed` is around one call. When the call ends, in its `finally`, the store's audit gets `tool.time` on the
  task's stream (the action brain) or the episode's (the character brain), in the scope those calls' own rows have:
  the call id, the tool, `duration_s` (3 decimals) and the outcome, `done`, `failed` (the tool's own failure: an
  action call closed FAILED, a refusal of hers) or `raised` (any other exception). A failure to write it never
  changes the call (`host.tool_time_failed` in the evidence says so).
- The watchdog, one daemon thread, looks every LOOK_SECONDS. A call running longer than OVERRUN_SECONDS, or than its
  own `timeout` argument plus TIMEOUT_SLACK_SECONDS for a tool that takes one (TIMED_TOOLS), gets one evidence record
  `host.tool_overrun` (the call id, brain, tool, stream, seconds, limit and the call thread's STACK_DEPTH innermost
  frames, file names and code only), one lane fault (lane `tools`, stage the tool, error `overrun`) and one warning
  line in the Host log. It only records: the call goes on, and is never released or restarted from here.
- `Calls.holding` counts the calls in flight within their limit; every check that a worker restart waits on reads it
  (the publication restart, her quiet restart, a settings apply), since a call can outlive its task.
- Before `attach` (no worker running: tests, tools) calls are timed and nothing is written.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager

OVERRUN_SECONDS = 600
TIMEOUT_SLACK_SECONDS = 120
TIMED_TOOLS = ('sandbox_run', 'development_run')
LOOK_SECONDS = 10
STACK_DEPTH = 60


def limit_of(tool, args):
    """The seconds a call may run before it is recorded as an overrun."""
    given = args.get('timeout') if isinstance(args, dict) and tool in TIMED_TOOLS else None
    return given + TIMEOUT_SLACK_SECONDS if type(given) is int and given > 0 else OVERRUN_SECONDS


def stack_of(frame):
    """A thread's innermost frames as `file:line function`; empty when the thread is gone."""
    if frame is None:
        return []
    return ['%s:%d %s' % (os.path.basename(f.filename), f.lineno, f.name)
            for f in traceback.extract_stack(frame)[-STACK_DEPTH:]]


class Calls:
    """The worker's tool calls in flight, and their watchdog."""

    def __init__(self):
        self.lock = threading.Lock()
        self.flight = {}
        self.store = self.evidence = self.fault = None
        self.stopping = threading.Event()

    def attach(self, store, evidence, fault):
        """Write from now on, and start the watchdog."""
        self.store, self.evidence, self.fault = store, evidence, fault
        threading.Thread(target=self._watch, name='asuna-tool-watch', daemon=True).start()
        return self

    def close(self):
        self.stopping.set()

    @contextmanager
    def timed(self, brain, call_id, tool, args, row, failed=()):
        """Around one call of `brain` ('action' or 'character') for `row` (its task or its episode); `failed`: the
        exception classes that are the tool's own failure."""
        key = uuid.uuid4().hex
        entry = {'call_id': call_id, 'brain': brain, 'tool': tool, 'stream': (row or {}).get('_id'),
                 'thread': threading.get_ident(), 'started': time.monotonic(), 'limit': limit_of(tool, args),
                 'reported': False}
        with self.lock:
            self.flight[key] = entry
        outcome = 'raised'
        try:
            yield
            outcome = 'done'
        except failed:
            outcome = 'failed'
            raise
        finally:
            with self.lock:
                self.flight.pop(key, None)
            self._time(entry, row, outcome, time.monotonic() - entry['started'])

    def _time(self, entry, row, outcome, seconds):
        store = self.store
        if store is None:
            return
        try:
            store.audit(row['_id'], 'tool.time', {'call_id': entry['call_id'], 'tool': entry['tool'],
                                                  'duration_s': round(seconds, 3), 'outcome': outcome},
                        row['scope_key'])
        except Exception as exc:                     # noqa: BLE001 the call's answer stands
            try:
                self.evidence.record('host.tool_time_failed', {'call_id': entry['call_id'], 'tool': entry['tool'],
                                                                'error': type(exc).__name__})
            except Exception:                        # noqa: BLE001
                pass

    def holding(self, now=None):
        """The calls in flight not yet past their limit: each holds a worker restart, even when its task or turn has
        ended (a stage cut at its limit leaves its call running). A call past its limit holds nothing: it is already
        recorded as an overrun, and the restart is what ends it."""
        now = time.monotonic() if now is None else now
        with self.lock:
            return sum(1 for entry in self.flight.values() if now - entry['started'] <= entry['limit'])

    def look(self, now=None):
        """Record each call past its limit not yet recorded; the calls recorded."""
        now = time.monotonic() if now is None else now
        with self.lock:
            due = [entry for entry in self.flight.values()
                   if not entry['reported'] and now - entry['started'] > entry['limit']]
            for entry in due:
                entry['reported'] = True
        if not due:
            return []
        frames = sys._current_frames()
        for entry in due:
            seconds = round(now - entry['started'], 1)
            payload = {key: entry[key] for key in ('call_id', 'brain', 'tool', 'stream')}
            payload.update(seconds=seconds, limit_s=entry['limit'], stack=stack_of(frames.get(entry['thread'])))
            try:
                if self.evidence is not None:
                    self.evidence.record('host.tool_overrun', payload)
            except Exception:                        # noqa: BLE001 the next record still goes out
                pass
            if self.fault is not None:
                self.fault(entry['tool'], 'overrun')
            print('ASUNA_TOOL_OVERRUN: %s call %s (%s, %s) has run %d s, past %d s; evidence host.tool_overrun'
                  % (entry['brain'], entry['call_id'], entry['tool'], entry['stream'], seconds, entry['limit']),
                  file=sys.stderr, flush=True)
        return due

    def _watch(self):
        while not self.stopping.wait(LOOK_SECONDS):
            try:
                self.look()
            except Exception:                        # noqa: BLE001 the watchdog never stops on a fault of its own
                pass
