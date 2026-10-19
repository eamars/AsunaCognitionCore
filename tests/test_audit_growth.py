"""ADR-067 MongoDB tests: the audit keeps what it is for and stops copying what is kept elsewhere. A commit leaves out a
memory's embedding (and says so), a write has no intent record, a turn's prepared context is recorded by its manifest
and who it is with, and past retention the bulky diagnostic records go while the chain still verifies. ADR-074: the audit is bounded
by time and by size."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import audit, state
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_engineering_m1 import THINK


def test_a_memorys_embedding_is_left_out_of_its_commit_and_the_document_check_still_holds(store):
    unit = {'_id': 'mu-x', 'kind': 'chat_chunk', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'status': 'active',
            'body_markdown': '周末去爬山', 'character_id': 'c'}
    first = store.put('memory_units', unit, stream='mu-x')
    store.put('memory_units', {**first, 'embedding': [0.1] * 1024, 'embedding_status': 'READY'},
              expected=first['revision'], stream='mu-x')
    commits = list(store.db.audit_events.find({'type': 'state.commit', 'stream_id': 'mu-x'}).sort('seq', 1))
    assert [c['payload'].get('derived_left_out') for c in commits] == [None, ['embedding']]
    assert 'embedding' not in commits[1]['payload']['document']
    assert len(state.canonical(commits[1]['payload'])) < 2000                 # the vector is not copied
    assert store.db.memory_units.find_one({'_id': 'mu-x'})['embedding'][:2] == [0.1, 0.1]
    events = list(store.db.audit_events.find({'stream_id': 'mu-x'}))
    assert audit.verify_documents(events, store) == 1                       # compared without it, not "tampered"
    store.db.memory_units.update_one({'_id': 'mu-x'}, {'$set': {'body_markdown': '改过'}})
    with pytest.raises(ValueError, match='AUDIT_DOCUMENT_TAMPERED'):
        audit.verify_documents(events, store)


def test_a_write_has_no_intent_record_and_a_turn_records_its_manifest_not_its_context(store):
    store.put('memory_units', {'_id': 'mu-y', 'kind': 'chat_chunk', 'scope_key': 'scene:dm-a', 'policy_epoch': 1,
                               'status': 'active', 'body_markdown': 'x', 'character_id': 'c'}, stream='mu-y')
    assert not store.db.audit_events.find_one({'type': 'state.intent'})
    ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '好')])).ingest(
        {'event_id': 'e-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    [row] = store.db.audit_events.find({'type': 'context.prepared', 'stream_id': ep['_id']})
    assert set(row['payload']) == {'manifest', 'context'}
    assert row['payload']['context'] == {'person_id': 'A', 'policy_epoch': ep['policy_epoch']}
    assert row['payload']['manifest']['context_sha256'] == ep['manifest']['context_sha256']
    assert 'selected' in row['payload']['manifest']


def test_past_retention_every_record_goes_but_her_tool_calls_and_the_latest_showing_and_the_chain_verifies(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    real_now = state.now
    def at(days):
        monkeypatch.setattr(state, 'now', lambda: (moment - timedelta(days=days)).isoformat())
    at(audit.KEPT_DAYS['role_tool'] + 1)
    store.audit('ep-older', 'role_tool', {'tool': 'think'})                  # past its year: goes
    at(audit.RETENTION_DAYS + 3)
    store.audit('review:p', 'review.map', {'persona': 'p'})                   # an older showing: goes
    at(audit.RETENTION_DAYS + 2)
    store.audit('review:p', 'review.map', {'persona': 'p'})                   # the latest showing: stays, whatever its age
    store.audit('ep-old', 'context.prepared', {'manifest': {}, 'context': {}})
    store.audit('ep-old', 'role_tool', {'tool': 'think'})                    # her action: kept a year
    store.audit('ep-old', 'state.commit', {'operation': 'o1', 'collection': 'messages', 'document': {'_id': 'm', 'revision': 2}})
    store.audit('ep-old', 'state.commit', {'operation': 'o2', 'collection': 'memory_units', 'document': {'_id': 'u', 'revision': 1}})
    store.audit('ep-old', 'state.commit', {'operation': 'o4', 'collection': 'state_revisions', 'document': {'_id': 'r', 'revision': 1}})
    monkeypatch.setattr(state, 'now', real_now)
    store.audit('ep-old', 'context.prepared', {'manifest': {}, 'context': {}})       # recent: kept
    assert audit.prune(store, moment) == 6
    mine = {'stream_id': {'$in': ['ep-older', 'ep-old', 'review:p']}}
    left = [(e['stream_id'], e['type']) for e in store.db.audit_events.find(mine).sort([('stream_id', 1), ('seq', 1)])]
    assert left == [('ep-old', 'role_tool'), ('ep-old', 'context.prepared'), ('review:p', 'review.map')]
    [mark] = store.db.audit_events.find({'type': 'audit.pruned'})
    assert mark['payload']['deleted'] == 6 and mark['payload']['by'] == {'time': 6} and mark['payload']['before'] < moment.isoformat()
    assert mark['payload']['records'][0] > mark['payload']['records'][1] and mark['payload']['seconds'] >= 0
    everything = list(store.db.audit_events.find({}))
    audit.verify(everything)                                                 # gaps where retention cut: accepted
    with pytest.raises(ValueError, match='AUDIT_HASH_CHAIN_INVALID'):
        audit.verify([e for e in everything if e['type'] != 'audit.pruned'])  # the same gaps unexplained: not
    # A run that deletes nothing says so too (her ask, 2026-10-20): otherwise it reads as no run at all.
    assert audit.prune(store, moment) == 0
    latest = store.db.audit_events.find_one({'type': 'audit.pruned'}, sort=[('seq', -1)])
    assert latest['payload']['deleted'] == 0 and latest['payload']['by'] == {}
    assert store.db.audit_events.count_documents({'type': 'audit.pruned'}) == 2


def test_the_latest_run_record_stays_past_retention_so_the_chain_gaps_stay_explained(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    real_now = state.now
    monkeypatch.setattr(state, 'now', lambda: (moment - timedelta(days=audit.RETENTION_DAYS + 5)).isoformat())
    store.audit('audit-retention', 'audit.pruned', {'before': '2000-01-01', 'deleted': 1, 'by': {'time': 1}})
    monkeypatch.setattr(state, 'now', real_now)
    audit.prune(store, moment)
    assert store.db.audit_events.count_documents({'type': 'audit.pruned'}) == 2, 'the old latest stays this run'


def test_over_its_cap_the_oldest_go_first_whatever_their_kind_and_the_latest_showing_stays(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    real_now = state.now
    for hours in range(40, 0, -1):                                           # 40 records, oldest first, all recent
        monkeypatch.setattr(state, 'now', lambda h=hours: (moment - timedelta(hours=h)).isoformat())
        store.audit('ep-%d' % hours, 'role_tool', {'tool': 'think', 'pad': 'x' * 400})
        if hours == 39:
            store.audit('review:p', 'review.exchanges', {'persona': 'p'})
    monkeypatch.setattr(state, 'now', real_now)
    stats = store.db.command('collStats', 'audit_events')
    size, count = stats['size'], stats['count']
    deleted = audit.prune(store, moment, cap=size // 2)
    assert abs(deleted - count // 2) <= 2                                   # about half, by the average record size
    assert store.db.audit_events.find_one({'type': 'review.exchanges'})     # the only showing stays
    oldest_left = min(e['occurred_at'] for e in store.db.audit_events.find({'type': 'role_tool'}))
    assert all(e['occurred_at'] >= oldest_left for e in store.db.audit_events.find({'type': 'role_tool'}))
    assert not store.db.audit_events.find_one({'stream_id': 'ep-40'})       # the oldest went first
    [mark] = store.db.audit_events.find({'type': 'audit.pruned'})
    # Deleted by size alone: the record says size, not time (her ask, 2026-10-20).
    assert mark['payload']['by'] == {'size': deleted} and mark['payload']['cap_bytes'] == size // 2
    assert mark['payload']['bytes'][1] < mark['payload']['bytes'][0]
    audit.verify(list(store.db.audit_events.find({})))
