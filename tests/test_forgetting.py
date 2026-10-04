"""Memory fades with time and with conversation volume since its last real use (persona model memory.forgetting)."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna.evidence import Evidence
from asuna.retrieval import Retrieval

FORGETTING = {'half_life_days': 30, 'half_life_messages': 1500, 'step_back_below': 0.1}


@pytest.fixture
def retrieval(store, tmp_path):
    value = Retrieval(store, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_old_and_crowded_out_memories_fade_pins_hold_and_summarized_chunks_step_back(store, retrieval):
    scope = store.db.scenes.find_one({'_id': 'dm-a'})['scope_key']
    store.db.scenes.update_one({'_id': 'dm-a'}, {'$set': {'sequence': 5000}})
    store.db.messages.insert_many([
        {'_id': 'm-old', 'schema_version': 1, 'scene_id': 'dm-a', 'scene_seq': 100, 'summary_batch_id': 'summary-1'},
        {'_id': 'm-new', 'schema_version': 1, 'scene_id': 'dm-a', 'scene_seq': 4990}])
    store.db.memory_units.insert_many([
        {'_id': 'fresh', 'schema_version': 1, 'scope_key': scope, 'kind': 'chat_chunk', 'scene_seq': 4990, 'occurred_at': ago(1),
         'source_event_ids': ['m-new']},
        {'_id': 'old', 'schema_version': 1, 'scope_key': scope, 'kind': 'chat_chunk', 'scene_seq': 100, 'occurred_at': ago(90),
         'source_event_ids': ['m-old']},
        {'_id': 'pinned', 'schema_version': 1, 'scope_key': scope, 'kind': 'chat_chunk', 'scene_seq': 100, 'occurred_at': ago(90),
         'source_event_ids': ['m-old'], 'pinned': True},
        {'_id': 'rehearsed', 'schema_version': 1, 'scope_key': scope, 'kind': 'chat_chunk', 'scene_seq': 100, 'occurred_at': ago(90),
         'source_event_ids': ['m-old'], 'salience': {'last_ref_at': ago(0), 'last_ref_seq': 4999}}])
    ranks = {key: {'score': 1 / 61, 'origins': {}} for key in ('fresh', 'old', 'pinned', 'rehearsed')}
    ranks['old']['score'] = ranks['pinned']['score'] = ranks['rehearsed']['score'] = 2 / 61   # the better match

    stepped = retrieval._forget(ranks, FORGETTING, retrieval._scene_sequences([scope]), automatic=True)
    assert ranks['old']['score'] < ranks['fresh']['score'], '90 days and ~4900 messages later, a better match loses'
    assert ranks['old']['freshness'] < 0.1 and ranks['pinned']['freshness'] == 1.0
    assert ranks['rehearsed']['freshness'] > 0.99, 'a memory a real turn just used is fresh again'
    assert stepped == {'old'}, 'faded raw chat already covered by a summary steps back from automatic recall'

    again = {key: {'score': 1.0, 'origins': {}} for key in ('old',)}
    assert retrieval._forget(again, FORGETTING, retrieval._scene_sequences([scope]), automatic=False) == set(), \
        'explicit recall still reaches it'
