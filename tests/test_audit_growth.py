"""ADR-067 MongoDB tests: the audit keeps what it is for and stops copying what is kept elsewhere. A commit leaves out a
memory's embedding (and says so), a write has no intent record, a turn's prepared context is recorded by its manifest
and who it is with, and past retention the bulky diagnostic records go while the chain still verifies."""
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


def test_past_retention_the_bulky_records_go_and_the_chain_still_verifies(store, monkeypatch):
    moment = datetime.now(timezone.utc)
    old = (moment - timedelta(days=audit.RETENTION_DAYS + 2)).isoformat()
    real_now = state.now
    monkeypatch.setattr(state, 'now', lambda: old)
    store.audit('ep-old', 'context.prepared', {'manifest': {}, 'context': {}})
    store.audit('ep-old', 'role_tool', {'tool': 'think'})                    # kept whatever its age
    store.audit('ep-old', 'state.commit', {'operation': 'o1', 'collection': 'messages', 'document': {'_id': 'm', 'revision': 2}})
    store.audit('ep-old', 'state.commit', {'operation': 'o2', 'collection': 'memory_units', 'document': {'_id': 'u', 'revision': 1}})
    store.audit('ep-old', 'state.commit', {'operation': 'o3', 'collection': 'memory_units', 'document': {'_id': 'u', 'revision': 2}})
    store.audit('ep-old', 'state.commit', {'operation': 'o4', 'collection': 'state_revisions', 'document': {'_id': 'r', 'revision': 1}})
    monkeypatch.setattr(state, 'now', real_now)
    store.audit('ep-old', 'context.prepared', {'manifest': {}, 'context': {}})       # recent: kept
    assert audit.prune(store, moment) == 3
    left = [(e['type'], (e['payload'].get('document') or {}).get('_id'), (e['payload'].get('document') or {}).get('revision'))
            for e in store.db.audit_events.find({'stream_id': 'ep-old'}).sort('seq', 1)]
    assert left == [('role_tool', None, None), ('state.commit', 'u', 1), ('state.commit', 'r', 1),
                    ('context.prepared', None, None)]
    [mark] = store.db.audit_events.find({'type': 'audit.pruned'})
    assert mark['payload']['deleted'] == 3 and mark['payload']['before'] < moment.isoformat()
    everything = list(store.db.audit_events.find({}))
    audit.verify(everything)                                                 # gaps where retention cut: accepted
    with pytest.raises(ValueError, match='AUDIT_HASH_CHAIN_INVALID'):
        audit.verify([e for e in everything if e['type'] != 'audit.pruned'])  # the same gaps unexplained: not
    assert audit.prune(store, moment) == 0 and store.db.audit_events.count_documents({'type': 'audit.pruned'}) == 1
