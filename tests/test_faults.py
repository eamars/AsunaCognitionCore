"""A turn of hers that fails in the program is told to the developer (once a day per failure, counted) and to her
(once, at her next turn there) (ADR-076 R4)."""
from datetime import datetime, timezone

from asuna import faults
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr082_people import THINK, event

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
    faults.told(store, {'scene_id': scene['_id'], 'manifest': {'told': {'fault': moment.isoformat()}}})
    assert faults.her_line(store, store.db.scenes.find_one({'_id': scene['_id']}), zone) is None, 'once'
    faults.turn_failed(store, ep, TRACE, now=datetime(2026, 10, 20, 1, 0, tzinfo=timezone.utc))
    assert store.db.developer_inbox.count_documents({'source.kind': 'turn_failed'}) == 2, 'a new day, a new note'


def test_the_line_stays_until_a_turn_that_showed_it_runs_to_its_end(store):
    """A turn prepared with the line and then failing must not take the line with it."""
    faults.turn_failed(store, {'_id': 'ep-x', 'scene_id': 'g1', 'persona': 'P1', 'episode_kind': 'external'}, TRACE)
    broken = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '在。', finish_reason='error')]))
    try:
        failed = broken.ingest(event('f-1'))
    except Exception:  # noqa: BLE001  (however the failure surfaces, the mark must survive it)
        failed = None
    assert not failed or failed['state'] != 'COMMITTED'
    assert store.db.scenes.find_one({'_id': 'g1'}).get('fault'), 'kept: the turn that showed it did not run'
    ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '在。')])).ingest(event('f-2'))
    assert ep['state'] == 'COMMITTED' and ep['context']['fault_from_program'].startswith('你在这里')
    assert not store.db.scenes.find_one({'_id': 'g1'}).get('fault'), 'cleared once a turn showed it to the end'
    again = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '在。')])).ingest(event('f-3'))
    assert 'fault_from_program' not in again['context']


def test_a_newer_mark_set_meanwhile_is_not_cleared_by_an_older_showing(store):
    faults.turn_failed(store, {'_id': 'ep-x', 'scene_id': 'g1', 'persona': 'P1'}, TRACE,
                       now=datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))
    faults.told(store, {'scene_id': 'g1', 'manifest': {'told': {'fault': '2026-10-18T00:00:00+00:00'}}})
    assert store.db.scenes.find_one({'_id': 'g1'}).get('fault')
