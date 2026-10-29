"""The counters written outside a document's revision (state.COUNTER_FIELDS), one case each: the counters at a read,
the write their real writer makes (in the store's words), and the counters after it. The table the counter cases of
integration/test_store_counters.py run, and tests/test_store_counters.py checks complete."""
from asuna.store.words import AddToSet, Increase, Set

THEN, NOW = '2026-10-28T01:00:00+00:00', '2026-10-29T01:00:00+00:00'
BUMPS = {
    'scenes': ({'sequence': 3}, Increase('sequence'), {'sequence': 4}),                             # ingress, coordinator
    'memory_units': ({'salience': {'ref_count': 1}},                                                # retrieval
                     [Increase('salience.ref_count'), Set({'salience.last_ref_seq': 9})],
                     {'salience': {'ref_count': 2, 'last_ref_seq': 9}}),
    'watches': ({'appeared': 0, 'last_seen_at': None},                                              # watches.seen
                [Set({'last_seen_at': NOW}), Increase('appeared')], {'appeared': 1, 'last_seen_at': NOW}),
    'notes': ({'seen_in': ['ep-1']}, AddToSet('seen_in', 'ep-2'), {'seen_in': ['ep-1', 'ep-2']}),     # notes
    'artifacts': ({'last_sent_at': THEN, 'last_read_at': THEN},                                     # mark_sent, mark_read
                  Set({'last_sent_at': NOW, 'last_read_at': NOW}), {'last_sent_at': NOW, 'last_read_at': NOW}),
}
