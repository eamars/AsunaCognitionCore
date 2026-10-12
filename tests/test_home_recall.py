"""At home her recall also reaches what she herself thought in her groups (owner 2026-10-12): her monologue there,
never the group's talk, each with the group's name and the time; a group turn's recall does not reach other groups."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna.context import ContextBuilder
from asuna.evidence import Evidence
from asuna.retrieval import Retrieval
from test_adr009_p2 import owner


@pytest.fixture
def retrieval(store, tmp_path):
    value = Retrieval(store, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def seed(store):
    scope = store.db.scenes.find_one({'_id': 'g1'})['scope_key']
    who = store.config['character_id']
    at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    store.db.memory_units.insert_many([
        {'_id': 'thought-g1', 'schema_version': 1, 'scope_key': scope, 'policy_epoch': 1, 'kind': 'monologue',
         'status': 'active', 'character_id': who, 'formed_at': at, 'body_markdown': '群里有人提到一个开源项目，名字我记下了'},
        {'_id': 'talk-g1', 'schema_version': 1, 'scope_key': scope, 'policy_epoch': 1, 'kind': 'chat_chunk',
         'status': 'active', 'character_id': who, 'occurred_at': at, 'body_markdown': '开源项目 开源项目 开源项目'}])
    return scope


def test_her_thoughts_in_a_group_come_back_but_never_the_groups_talk(store, retrieval):
    scope = seed(store)
    found = retrieval.own_thoughts([(scope, 1)], '开源项目')
    assert [m['_id'] for m in found] == ['thought-g1']
    assert retrieval.own_thoughts([], '开源项目') == []


def test_home_recall_names_the_group_and_the_time(store, retrieval):
    seed(store)
    owner(store)
    context = ContextBuilder(store, retrieval)
    home = store.db.scenes.find_one({'_id': 'dm-a'})
    [item] = context.own_thoughts_elsewhere(home, '开源项目')
    assert item['_id'] == 'thought-g1' and item['thought'].startswith('群里有人提到')
    assert item['where'] and 'g1' not in item['where'] and '小时前' in item['when']


def test_the_recall_tool_adds_them_at_home_only(store, retrieval):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    seed(store)
    owner(store)
    think = ('think', {'thought': '想想。'})
    for scene, person, expected in (('dm-a', 'A', True), ('g1', 'A', False)):
        lane = FakeLane(store, [FakeTurn([think, ('recall', {'query': '开源项目'})], '嗯。')])
        coordinator = Coordinator(store, lane)
        coordinator.context.retrieval = retrieval
        coordinator.ingest({'event_id': 'e-' + scene, 'scene_id': scene, 'person_id': person, 'text': '那个项目叫什么来着'})
        result = next(r[4] for r in lane.tool_results if r[2] == 'recall')
        assert ('own_thoughts_in_groups' in result) == expected, (scene, result.keys())
