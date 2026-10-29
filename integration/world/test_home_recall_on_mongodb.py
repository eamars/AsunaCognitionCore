"""Home recall (owner 2026-10-12) on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): her
thoughts in a group come back at home, never the group's talk."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna.evidence import Evidence
from asuna.retrieval import Retrieval

pytestmark = pytest.mark.world                # `store` is the fixture world


@pytest.fixture
def retrieval(store, tmp_path):
    value = Retrieval(store, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def seed(store):
    scope = store.raw.scenes.find_one({'_id': 'g1'})['scope_key']
    who = store.config['character_id']
    at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    store.raw.memory_units.insert_many([
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


