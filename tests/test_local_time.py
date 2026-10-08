"""What a model reads is on the local clock (owner 2026-10-08): stored records keep UTC; every turn context and tool
result handed to a model has its timestamp fields on the conversation's time zone, and free text is left alone."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from asuna import local_time
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn

ZONE = {'tz': ZoneInfo('Pacific/Auckland'), 'name': 'Pacific/Auckland'}
UTC_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|\+00:00)')


def test_timestamp_fields_turn_local_and_free_text_does_not():
    shown = local_time.for_model({
        'created_at': '2026-10-08T03:39:00.123456+00:00', 'next_fire_at': '2026-10-09T07:00:00Z',
        'at': datetime(2026, 10, 8, 2, 8), 'alive_until': '2026-10-08T01:50:39+00:00',
        'items': [{'occurred_at': '2026-04-08T03:39:00Z'}],
        'text': '这句话里写着 2026-10-08T03:39:00Z，不是字段', 'scene_seq': 12, 'at_least': '2026-10-08T03:39:00Z'}, ZONE)
    assert shown['created_at'] == '2026-10-08 16:39' and shown['next_fire_at'] == '2026-10-09 20:00'
    assert shown['at'] == '2026-10-08 15:08' and shown['alive_until'] == '2026-10-08 14:50'
    assert shown['items'][0]['occurred_at'] == '2026-04-08 15:39', 'standard time in April: +12'
    assert shown['text'].endswith('不是字段') and '03:39:00Z' in shown['text'] and shown['scene_seq'] == 12
    assert shown['at_least'] == '2026-10-08T03:39:00Z', 'only keys that name a time'


def test_a_turn_reaches_the_model_without_utc_timestamps(store):
    store.config['timezone'] = 'Pacific/Auckland'
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '看看。'})], '在。')])
    Coordinator(store, lane).ingest({'event_id': 'lt-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    delivered = str(lane.calls[0]['messages'])
    stored = str(store.db.episodes.find_one({'source_event_id': 'lt-1'})['context'])
    assert UTC_STAMP.search(stored), 'the stored context keeps UTC for the program'
    assert not UTC_STAMP.search(delivered), UTC_STAMP.search(delivered)
