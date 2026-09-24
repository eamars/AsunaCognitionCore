"""Transient, read-only text projection while a UI session is open."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time


class UiStreamHub:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0
        self.calls = {}

    def _prune(self):
        expired = [key for key, call in self.calls.items()
                   if call['_ended'] and ((call['_durable_at'] and time.monotonic() - call['_durable_at'] > 300)
                                          or time.monotonic() - call['_ended'] > 7200)]
        for key in expired:
            del self.calls[key]
        return bool(expired)

    def __call__(self, kind, call_id, **value):
        with self.condition:
            if kind == 'start':
                self.calls[call_id] = {**value, 'id': call_id, 'parts': [],
                                       'createdAt': datetime.now(timezone.utc).isoformat(),
                                       'status': 'running', '_ended': 0, '_durable_at': 0}
            elif call_id in self.calls:
                call = self.calls[call_id]
                if kind == 'text':
                    field, part = value['field'], value['text']
                    if field not in ('content', 'reasoning_content') or not isinstance(part, str):
                        return
                    if call['parts'] and call['parts'][-1]['field'] == field:
                        call['parts'][-1]['text'] += part
                    else:
                        call['parts'].append({'field': field, 'text': part})
                elif kind == 'end':
                    call['status'] = value.get('status', 'settling')
                    call['_ended'] = time.monotonic()
                else:
                    return
            else:
                return
            # Settled entries remain briefly so the durable audit row can replace
            # them in place, including after a browser reconnect.
            self._prune()
            self.version += 1
            self.condition.notify_all()

    def mark_durable(self, operations):
        """Retain long-running step text until its existing audit output arrives."""
        with self.condition:
            now = time.monotonic()
            for call in self.calls.values():
                if call['_ended'] and call.get('operation') in operations and not call['_durable_at']:
                    call['_durable_at'] = now
            if self._prune():
                self.version += 1
                self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            if self._prune():
                self.version += 1
            return self.version, [{key: [part.copy() for part in value] if key == 'parts' else value
                                   for key, value in call.items() if not key.startswith('_')}
                                  for call in self.calls.values()]

    def wait(self, version, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.version != version, timeout)
            return self.version
