"""One process of ADR-009 E14 (test_engineering_m1_on_mongodb.py): a turn on the test's throwaway database, in the
test's own settings (the environment's ASUNA_CRASH_CONFIG, JSON), killed after her line is sent and before its
receipt is written (exit 77).

  python crash_worker.py <database>
"""
import json
import os
import sys

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import Store

store = Store(json.loads(os.environ['ASUNA_CRASH_CONFIG']), sys.argv[1])
lane = FakeLane(store, [FakeTurn([('think', {'thought': '内部。'})], '回来啦。')])


def crash(point):
    if point == 'after_send_before_receipt':
        os._exit(77)


Coordinator(store, lane, crash=crash).ingest({'event_id': 'crash', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
