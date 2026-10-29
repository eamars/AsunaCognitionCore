"""The audit chain (ADR-067, ADR-074), where records are rewritten and removed. A commit leaves out a memory's embedding
and the document check still holds and still finds a change made outside a commit; past retention, and over the size
cap, records go while the chain still verifies, its gaps explained by the retention run's record, which stays; a
turn's audit replays into an empty database to the same state. On the unit run's store (conftest.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import audit, state
from asuna.records import memories as memory_records
from asuna.store.words import Set


def test_a_memorys_embedding_is_left_out_of_its_commit_and_the_document_check_still_holds(store):
    unit = {'_id': 'mu-x', 'kind': 'chat_chunk', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'status': 'active',
            'body_markdown': '周末去爬山', 'character_id': 'c'}
    first = memory_records.save(store, unit, stream='mu-x')
    memory_records.save(store, {**first, 'embedding': [0.1] * 768, 'embedding_status': 'READY'},
                        expected=first['revision'], stream='mu-x')
    commits = audit.events(store, 'state.commit', stream='mu-x', by='seq').rows()
    assert [c['payload'].get('derived_left_out') for c in commits] == [None, ['embedding']]
    assert 'embedding' not in commits[1]['payload']['document']
    assert len(state.canonical(commits[1]['payload'])) < 2000                 # the vector is not copied
    assert store.collection('memory_units').get('mu-x')['embedding'][:2] == [0.1, 0.1]
    events = audit.events(store, stream='mu-x', by=None).rows()
    assert audit.verify_documents(events, store) == 1                       # compared without it, not "tampered"
    store.collection('memory_units').update({'_id': 'mu-x'}, Set({'body_markdown': '改过'}))
    with pytest.raises(ValueError, match='AUDIT_DOCUMENT_TAMPERED'):
        audit.verify_documents(events, store)


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
    left = [(e['stream_id'], e['type'])
            for e in audit.events(store, streams=['ep-older', 'ep-old', 'review:p'], by='stream').rows()]
    assert left == [('ep-old', 'role_tool'), ('ep-old', 'context.prepared'), ('review:p', 'review.map')]
    [mark] = audit.events(store, 'audit.pruned').rows()
    assert mark['payload']['deleted'] == 6 and mark['payload']['by'] == {'time': 6} and mark['payload']['before'] < moment.isoformat()
    assert mark['payload']['records'][0] > mark['payload']['records'][1] and mark['payload']['seconds'] >= 0
    everything = audit.events(store, by=None).rows()
    audit.verify(everything)                                                 # gaps where retention cut: accepted
    with pytest.raises(ValueError, match='AUDIT_HASH_CHAIN_INVALID'):
        audit.verify([e for e in everything if e['type'] != 'audit.pruned'])  # the same gaps unexplained: not
    # A run that deletes nothing says so too (her ask, 2026-10-20): otherwise it reads as no run at all.
    assert audit.prune(store, moment) == 0
    latest = audit.events(store, 'audit.pruned', by='seq').first(newest_first=True)
    assert latest['payload']['deleted'] == 0 and latest['payload']['by'] == {}
    assert audit.count(store, 'audit.pruned') == 2


def test_the_latest_run_record_stays_past_retention_so_the_chain_gaps_stay_explained(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    real_now = state.now
    monkeypatch.setattr(state, 'now', lambda: (moment - timedelta(days=audit.RETENTION_DAYS + 5)).isoformat())
    store.audit('audit-retention', 'audit.pruned', {'before': '2000-01-01', 'deleted': 1, 'by': {'time': 1}})
    monkeypatch.setattr(state, 'now', real_now)
    audit.prune(store, moment)
    assert audit.count(store, 'audit.pruned') == 2, 'the old latest stays this run'


def test_over_its_cap_the_oldest_go_first_whatever_their_kind_and_the_latest_showing_stays(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    real_now = state.now
    for hours in range(40, 0, -1):                                           # 40 records, oldest first, all recent
        monkeypatch.setattr(state, 'now', lambda h=hours: (moment - timedelta(hours=h)).isoformat())
        store.audit('ep-%d' % hours, 'role_tool', {'tool': 'think', 'pad': 'x' * 400})
        if hours == 39:
            store.audit('review:p', 'review.exchanges', {'persona': 'p'})
    monkeypatch.setattr(state, 'now', real_now)
    stats = store.collection('audit_events').size()
    size, count = stats.bytes, stats.records
    deleted = audit.prune(store, moment, cap=size // 2)
    assert abs(deleted - count // 2) <= 2                                   # about half, by the average record size
    assert audit.events(store, 'review.exchanges').first()                  # the only showing stays
    tools = audit.events(store, 'role_tool').rows()
    oldest_left = min(e['occurred_at'] for e in tools)
    assert all(e['occurred_at'] >= oldest_left for e in tools)
    assert not audit.events(store, stream='ep-40').first()                  # the oldest went first
    [mark] = audit.events(store, 'audit.pruned').rows()
    # Deleted by size alone: the record says size, not time (her ask, 2026-10-20).
    assert mark['payload']['by'] == {'size': deleted} and mark['payload']['cap_bytes'] == size // 2
    assert mark['payload']['bytes'][1] < mark['payload']['bytes'][0]
    audit.verify(audit.events(store, by=None).rows())


def test_E23_state_replay_and_tamper(world, tmp_path):
    """A turn's audit verifies, replays into an empty database to the same state, and a changed record breaks it; its
    trace page carries no script (ADR-009 E23)."""
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from conftest import memory_store
    store = world
    Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': 'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})],
                                                 '回来了。')])).ingest(
        {'event_id': 'e', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '我回来了。'})
    events = audit.events(store, by=None).rows()
    audit.verify(events)
    with memory_store() as target:
        target_events = audit.trace_contents(events, store)
        assert audit.replay(events, target, target_events)['sha256'] == audit.projection(store)['sha256']
    modified = [dict(event) for event in events]
    modified[0] = {**modified[0], 'payload': {**modified[0]['payload'], 'changed': True}}
    with pytest.raises(ValueError):
        audit.verify(modified)
    audit.render_html(events, tmp_path / 'trace.html')
    assert '<script' not in (tmp_path / 'trace.html').read_text(encoding='utf-8')
