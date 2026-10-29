"""records.memories answers what the replaced reads answered (ADR-104 B7): the vector search's pairs as an `Or` of the
pairs' conditions and no pair answered without a search, the Web memory page newest by each memory's own time, and a
recall's reads leaving the vector out. On the in-memory adapter over the core's catalog."""
import pytest

from asuna.records import memories as memory_records
from asuna.store import Checked
from asuna.store.catalog import CATALOG
from asuna.store.memory import MemoryAdapter
from asuna.store.words import And, Or

ME, REVISION = 'demo', 'route-x'


@pytest.fixture
def store():
    return Checked(MemoryAdapter(seed=0), CATALOG)


def vector(n):
    return [1.0 if i == n else 0.01 for i in range(memory_records.SPACE.dimensions)]


def memory(store, memory_id, scope='scene:a', epoch=1, **fields):
    store.collection('memory_units').insert({
        '_id': memory_id, 'schema_version': 1, 'revision': 1, 'scope_key': scope, 'policy_epoch': epoch,
        'character_id': ME, 'status': 'active', 'embedding_revision': REVISION, 'embedding': vector(0), **fields})


def searched(store):
    """The vector searches the store was asked for: their conditions."""
    asked, nearest = [], store.nearest
    store.nearest = lambda space, v, k, where: asked.append(where) or nearest(space, v, k, where)
    return asked


def test_an_empty_pair_list_answers_nothing_without_a_call(store):
    """No (scope, epoch) pair, or none a text scope with a number epoch: nothing matches, and the store is not asked
    (MongoDB's vector filter refuses an empty any-of; state.py's translation answered it the same way)."""
    memory(store, 'm1')
    asked = searched(store)
    assert memory_records.nearest(store, vector(0), 5, [], character=ME, revision=REVISION) == []
    assert memory_records.nearest(store, vector(0), 5, [('scene:a', None), (None, 1)], character=ME,
                                  revision=REVISION) == []
    assert asked == []


def test_the_pairs_are_an_or_of_each_pairs_conditions(store):
    memory(store, 'here', scope='scene:a', epoch=2)
    memory(store, 'old-epoch', scope='scene:a', epoch=1)
    memory(store, 'shared', scope='global-safe', epoch=1)
    memory(store, 'elsewhere', scope='scene:b', epoch=2)
    memory(store, 'a-thought', scope='scene:a', epoch=2, kind='monologue')
    asked = searched(store)
    found = memory_records.nearest(store, vector(0), 10, [('global-safe', 1), ('scene:a', 2)], character=ME,
                                   revision=REVISION)
    assert sorted(key for key, _ in found) == ['a-thought', 'here', 'shared']
    assert asked == [And({'character_id': ME, 'status': 'active', 'embedding_revision': REVISION},
                         Or({'scope_key': 'global-safe', 'policy_epoch': 1}, {'scope_key': 'scene:a', 'policy_epoch': 2}))]
    thoughts = memory_records.nearest(store, vector(0), 10, [('scene:a', 2)], character=ME, revision=REVISION,
                                      kind='monologue')
    assert [key for key, _ in thoughts] == ['a-thought']


def test_the_web_page_is_newest_by_each_memorys_own_time_then_by_id(store):
    """A memory's own time is the first of generated_at, occurred_at, formed_at it holds (null counts as none);
    memories holding none come last; ties by id, newest first."""
    memory(store, 'summary', generated_at='2026-10-05', occurred_at='2026-01-01', body_markdown='夏天的事')
    memory(store, 'line', occurred_at='2026-10-04', formed_at='2026-12-31', body_markdown='Summer plans')
    memory(store, 'null-made', generated_at=None, occurred_at='2026-10-03')
    memory(store, 'thought', formed_at='2026-10-02')
    memory(store, 'tied-b', formed_at='2026-10-02')
    memory(store, 'timeless-a')
    memory(store, 'timeless-b', formed_at=None)
    memory(store, 'not-hers', character_id='other', formed_at='2026-10-09')
    memory(store, 'old-epoch', epoch=2, formed_at='2026-10-09')
    page = lambda **kw: memory_records.web_page(store, [('scene:a', 1)], ME, fields=['scope_key'], **kw)
    rows = page(limit=10)
    assert [row['_id'] for row in rows] == ['summary', 'line', 'null-made', 'tied-b', 'thought', 'timeless-b',
                                            'timeless-a']
    assert [row['_memory_time'] for row in rows[:3]] == ['2026-10-05', '2026-10-04', '2026-10-03']
    assert rows[-1]['_memory_time'] is None and 'embedding' not in rows[0]
    assert [row['_id'] for row in page(skip=2, limit=3)] == ['null-made', 'tied-b', 'thought']
    assert [row['_id'] for row in page(search='SUMMER', limit=10)] == ['line']
    assert page(limit=0) == [] and memory_records.web_page(store, [], ME, limit=5, fields=[]) == []


def test_a_recall_read_leaves_the_vector_out_and_keeps_the_rest(store):
    memory(store, 'm1', body_markdown='x', salience={'ref_count': 2})
    row = memory_records.get(store, 'm1', memory_records.UNVECTORED, pairs=[('scene:a', 1)], character=ME,
                             status='active')
    assert 'embedding' not in row and row['salience'] == {'ref_count': 2} and row['body_markdown'] == 'x'
    assert 'embedding' in memory_records.get(store, 'm1')
    rows = memory_records.readable(store, [('scene:a', 1)], character=ME, by=('occurred_at', '_id')).rows(
        newest_first=True, fields=memory_records.UNVECTORED)
    assert [sorted(r) for r in rows] == [sorted(k for k in memory_records.get(store, 'm1') if k != 'embedding')]
