"""Transient, read-only display of provider bytes while a UI session is open."""
from __future__ import annotations

import codecs
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
                   if call['_ended'] and time.monotonic() - call['_ended'] > 300]
        for key in expired:
            del self.calls[key]
        return bool(expired)

    def __call__(self, kind, call_id, **value):
        with self.condition:
            if kind == 'start':
                self.calls[call_id] = {**value, 'id': call_id, 'body_utf8': '',
                                       'createdAt': datetime.now(timezone.utc).isoformat(),
                                       'status': 'running', '_decoder': codecs.getincrementaldecoder('utf-8')(),
                                       '_ended': 0}
            elif call_id in self.calls:
                call = self.calls[call_id]
                if kind == 'chunk':
                    call['body_utf8'] += call['_decoder'].decode(value['chunk'])
                elif kind == 'end':
                    call['body_utf8'] += call['_decoder'].decode(b'', final=True)
                    call['status'] = value.get('status', 'settling')
                    call['_ended'] = time.monotonic()
            else:
                return
            # Settled entries remain briefly so the durable audit row can replace
            # them in place, including after a browser reconnect.
            self._prune()
            self.version += 1
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            if self._prune():
                self.version += 1
            return self.version, [{key: value for key, value in call.items() if not key.startswith('_')}
                                  for call in self.calls.values()]

    def wait(self, version, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.version != version, timeout)
            return self.version
