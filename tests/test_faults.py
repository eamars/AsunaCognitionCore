"""A turn of hers that fails in the program is told to the developer (once a day per failure, counted) and to her
(once, at her next turn there) (ADR-076 R4)."""
from datetime import datetime, timezone

from asuna import faults

TRACE = 'Traceback (most recent call last):\n  File "x.py", line 1\nasuna.state.Denied: NATIVE_BINDING_IDENTITY_CHANGED'


def test_a_failure_is_named_by_its_code_or_else_by_its_class():
    assert faults.cause(TRACE) == 'NATIVE_BINDING_IDENTITY_CHANGED'
    assert faults.cause('Traceback\nKeyError: \'x\'') == 'KeyError'
    assert faults.cause('') == 'unknown'


def test_the_developer_hears_once_a_day_with_a_count_and_she_reads_it_once_where_it_happened(store):
    scene = store.db.scenes.find_one()
    ep = {'_id': 'ep-x', 'scene_id': scene['_id'], 'persona': 'P1', 'episode_kind': 'self_development'}
    moment = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)
    faults.turn_failed(store, ep, TRACE, now=moment)
    faults.turn_failed(store, {**ep, '_id': 'ep-y'}, TRACE, now=moment)
    [row] = list(store.db.developer_inbox.find({'source.kind': 'turn_failed'}))
    assert row['count'] == 2 and row['source']['by'] == 'program' and 'NATIVE_BINDING_IDENTITY_CHANGED' in row['text']
    assert '自我改进' in row['text']
    zone = {'tz': timezone.utc, 'name': 'UTC', 'source': 'test'}
    line = faults.her_line(store, store.db.scenes.find_one({'_id': scene['_id']}), zone)
    assert line.startswith('你在这里') and '不是你做错了什么' in line and '已经报给开发者' in line
    assert faults.her_line(store, store.db.scenes.find_one({'_id': scene['_id']}), zone) is None, 'once'
    faults.turn_failed(store, ep, TRACE, now=datetime(2026, 10, 20, 1, 0, tzinfo=timezone.utc))
    assert store.db.developer_inbox.count_documents({'source.kind': 'turn_failed'}) == 2, 'a new day, a new note'
