"""The newest prepared contexts of a scope's turns with one person at one epoch (audit.prepared_for): read newest first
by (occurred_at, _id), each page after the last record the page before it read, at most `limit` found. The answer is
the one a single read in that order gives, ties included, over more than one page and a tie at a page boundary. On the
unit run's store."""
from asuna import audit, state

SCOPE = 'scene:dm-a'


def prepare(store, monkeypatch, at, person='A', epoch=1, scope=SCOPE):
    monkeypatch.setattr(state, 'now', lambda: at)
    return store.audit('ep-' + at, 'context.prepared', {'context': {'person_id': person, 'policy_epoch': epoch}}, scope)


def test_pages_by_cursor_give_the_newest_in_order_across_a_tie_at_the_boundary(store, monkeypatch):
    made = []
    for minute, count in ((1, 2), (2, 5), (3, 1), (4, 3)):                 # five records share minute 2
        for _ in range(count):
            made.append(prepare(store, monkeypatch, '2026-10-29T00:0%d:00+00:00' % minute))
    prepare(store, monkeypatch, '2026-10-29T00:05:00+00:00', person='B')      # someone else
    prepare(store, monkeypatch, '2026-10-29T00:05:00+00:00', epoch=2)         # another epoch
    prepare(store, monkeypatch, '2026-10-29T00:05:00+00:00', scope='scene:elsewhere')
    newest = sorted(made, key=lambda e: (e['occurred_at'], e['_id']), reverse=True)
    want = [(e['_id'], e['occurred_at']) for e in newest]
    got = audit.prepared_for(store, SCOPE, 'A', 1, page=3)                   # pages of 3: the tie crosses two of them
    assert [(e['_id'], e['occurred_at']) for e in got] == want
    assert [e['_id'] for e in audit.prepared_for(store, SCOPE, 'A', 1, limit=6, page=3)] == [e[0] for e in want[:6]]
    assert audit.prepared_for(store, SCOPE, 'A', 1) == got                    # one page holds them all
    assert audit.prepared_for(store, SCOPE, 'C', 1, page=3) == []
