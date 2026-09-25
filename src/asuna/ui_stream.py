"""Bounded, transient semantic deltas for the Web observation channel."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import threading
import time


class UiStreamHub:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0
        self.calls = {}
        self.events = deque()
        self.event_bytes = 0

    def _emit(self, kind, call, **value):
        self.version += 1
        event = {key: call[key] for key in ('id', 'operation', 'scope_key', 'lane', 'phase', 'request_ref', 'createdAt')
                 if key in call}
        event.update(kind=kind, sequence=self.version, **value)
        self.events.append(event)
        self.event_bytes += len(value.get('text', '').encode('utf-8'))
        while len(self.events) > 512 or self.event_bytes > 262144:
            old = self.events.popleft()
            self.event_bytes -= len(old.get('text', '').encode('utf-8'))
        self.condition.notify_all()

    def _prune(self):
        now = time.monotonic()
        expired = [key for key, call in self.calls.items()
                   if call['_ended'] and now - call['_ended'] > 30]
        for key in expired:
            del self.calls[key]

    def __call__(self, kind, call_id, **value):
        with self.condition:
            if kind == 'start':
                call = {**value, 'id': call_id, 'createdAt': datetime.now(timezone.utc).isoformat(),
                        'status': 'running', '_ended': 0}
                self.calls[call_id] = call
                self._emit('start', call, status='running')
            elif call_id in self.calls:
                call = self.calls[call_id]
                if kind == 'text':
                    field, part = value.get('field'), value.get('text')
                    if field not in ('content', 'reasoning_content') or not isinstance(part, str) or not part:
                        return
                    self._emit('delta', call, field=field, text=part)
                elif kind == 'end':
                    call['status'] = value.get('status', 'settling')
                    call['_ended'] = time.monotonic()
                    self._emit('end', call, status=call['status'])
                else:
                    return
            self._prune()

    def mark_durable(self, operations):
        with self.condition:
            keys = {key for key, call in self.calls.items()
                    if call['_ended'] and call.get('operation') in operations}
            for key in keys:
                del self.calls[key]
            if keys:
                self.events = deque(event for event in self.events if event.get('id') not in keys)
                self.event_bytes = sum(len(event.get('text', '').encode('utf-8')) for event in self.events)
            self._prune()

    def reset(self):
        with self.condition:
            self.calls.clear()
            self.events.clear()
            self.event_bytes = 0
            self.version += 1
            self.events.append({'kind': 'reset', 'sequence': self.version})
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            self._prune()
            return self.version, [{key: value for key, value in call.items() if not key.startswith('_')}
                                  for call in self.calls.values()]

    def events_since(self, version):
        with self.condition:
            return self.version, [event.copy() for event in self.events if event['sequence'] > version]

    def wait(self, version, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.version != version, timeout)
            return self.version
