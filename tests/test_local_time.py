"""What a model reads is on the local clock (owner 2026-10-08): stored records keep UTC; every turn context and tool
result handed to a model has its timestamp fields on the conversation's time zone, and free text is left alone."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from asuna import local_time

ZONE = {'tz': ZoneInfo('Pacific/Auckland'), 'name': 'Pacific/Auckland'}


def test_timestamp_fields_turn_local_and_free_text_does_not():
    shown = local_time.for_model({
        'created_at': '2026-10-08T03:39:00.123456+00:00', 'next_fire_at': '2026-10-09T07:00:00Z',
        'at': datetime(2026, 10, 8, 2, 8), 'alive_until': '2026-10-08T01:50:39+00:00',
        'items': [{'occurred_at': '2026-04-08T03:39:00Z'}],
        'text': '这句话里写着 2026-10-08T03:39:00Z，不是字段', 'scene_seq': 12, 'at_least': '2026-10-08T03:39:00Z'},
        ZONE, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert shown['created_at'] == '10/8 16:39' and shown['next_fire_at'] == '10/9 20:00'
    assert shown['at'] == '10/8 15:08' and shown['alive_until'] == '10/8 14:50'
    assert shown['items'][0]['occurred_at'] == '2026/4/8 15:39', 'standard time in April: +12; over 90 days: the year'
    assert shown['text'].endswith('不是字段') and '03:39:00Z' in shown['text'] and shown['scene_seq'] == 12
    assert shown['at_least'] == '2026-10-08T03:39:00Z', 'only keys that name a time'


def test_one_face_with_the_year_only_when_it_is_another_year_or_far_from_when_it_is_written():
    tz = ZONE['tz']
    now = datetime(2027, 1, 2, tzinfo=timezone.utc)
    assert local_time.face(datetime(2027, 1, 1, 22, tzinfo=timezone.utc), tz, now) == '1/2 11:00'
    assert local_time.face(datetime(2026, 12, 20, 1, tzinfo=timezone.utc), tz, now) == '2026/12/20 14:00', \
        'a date written in the new year about the old one carries its year'
    assert local_time.face(datetime(2027, 5, 1, tzinfo=timezone.utc), tz, now) == '2027/5/1 12:00', 'over 90 days ahead'
    assert local_time.face(datetime(2027, 1, 1, 22, tzinfo=timezone.utc), tz, now, year=True) == '2027/1/2 11:00'
    assert local_time.for_model({'at': '10/8 16:39'}, ZONE) == {'at': '10/8 16:39'}, 'the face is never read as a time'


