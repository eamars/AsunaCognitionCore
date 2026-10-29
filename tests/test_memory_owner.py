"""records.memories asks the vector search what the replaced reads asked (ADR-104 B7): the (scope, epoch) pairs as an
`Or` of each pair's conditions beside the other filters, and no pair answered without a search (MongoDB's vector
filter refuses an empty any-of). What the search answers is the adapter's: the store's contract on MongoDB
(integration/store_contract.py, class N). No database: the store here only records what it was asked."""
from asuna.records import memories as memory_records
from asuna.store.words import And, Or

ME, REVISION = 'demo', 'route-x'


class Asked:
    """A store whose vector search records its conditions and finds nothing."""

    def __init__(self):
        self.asked = []

    def nearest(self, space, vector, k, where):
        self.asked.append(where)
        return []


def vector(n):
    return [1.0 if i == n else 0.01 for i in range(memory_records.SPACE.dimensions)]


def test_an_empty_pair_list_answers_nothing_without_a_call():
    """No (scope, epoch) pair, or none a text scope with a number epoch: nothing matches, and the store is not asked."""
    store = Asked()
    assert memory_records.nearest(store, vector(0), 5, [], character=ME, revision=REVISION) == []
    assert memory_records.nearest(store, vector(0), 5, [('scene:a', None), (None, 1)], character=ME,
                                  revision=REVISION) == []
    assert store.asked == []


def test_the_pairs_are_an_or_of_each_pairs_conditions():
    store = Asked()
    memory_records.nearest(store, vector(0), 10, [('global-safe', 1), ('scene:a', 2)], character=ME, revision=REVISION)
    memory_records.nearest(store, vector(0), 10, [('scene:a', 2)], character=ME, revision=REVISION, kind='monologue')
    assert store.asked == [
        And({'character_id': ME, 'status': 'active', 'embedding_revision': REVISION},
            Or({'scope_key': 'global-safe', 'policy_epoch': 1}, {'scope_key': 'scene:a', 'policy_epoch': 2})),
        And({'character_id': ME, 'status': 'active', 'embedding_revision': REVISION, 'kind': 'monologue'},
            Or({'scope_key': 'scene:a', 'policy_epoch': 2}))]
