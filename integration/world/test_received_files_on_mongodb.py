"""ADR-102 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): keeping, listing and marking a
read stay inside the fence."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import received_files as rf
from asuna.state import Denied

pytestmark = pytest.mark.world                # `store` is the fixture world


def scopes(store):
    rows = list(store.raw.scenes.find({}, {'_id': 1, 'scope_key': 1}).sort('_id', 1))
    return rows[0], rows[1]


def a_file(store, scope, n, body=None, **origin):
    origin = {'name': 'notes-%d.txt' % n, 'sender': 'a sender', **origin}
    return rf.stash(store, body or ('line %d\n' % n).encode(), scope, message_id='in-ep-%d' % n, index=0,
                    **origin)['artifact_id']


def row(store, artifact_id):
    return store.raw.artifacts.find_one({'_id': artifact_id})


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


# ── keeping ─────────────────────────────────────────────────────────
def test_keeping_and_listing_stay_inside_the_fence(store):
    here, there = scopes(store)
    mine, theirs = a_file(store, here['scope_key'], 1), a_file(store, there['scope_key'], 2)
    with pytest.raises(Denied, match='RECEIVED_FILE_NOT_FOUND'):
        rf.keep(store, theirs, 'why', [here['scope_key']])
    rf.keep(store, theirs, 'theirs', [there['scope_key']])
    note = rf.keep(store, mine, 'mine', [here['scope_key']])['note']
    assert note.startswith('留下了') and '现在留着 2 个' in note
    listing = rf.kept(store, [here['scope_key']], here['_id'])
    assert [entry['name'] for entry in listing['kept']] == ['notes-1.txt'] and listing['kept'][0]['why'] == 'mine'
    assert listing['elsewhere'] == rf.OTHERS_ELSEWHERE % 1 and 'notes-2' not in str(listing)
    home = rf.kept(store, [here['scope_key'], there['scope_key']], here['_id'])
    assert [entry['name'] for entry in home['kept']] == ['notes-1.txt', 'notes-2.txt'] and 'elsewhere' not in home


def test_marking_a_read_stays_inside_the_fence(store):
    """The time a quota refusal sorts by is written only inside the fence: another conversation's id leaves it as it
    was (Xiaoman's review of db192bdff79e)."""
    here, there = scopes(store)
    theirs = a_file(store, there['scope_key'], 1)
    rf.mark_read(store, theirs, [here['scope_key']], ago(days=1))
    assert 'last_read_at' not in row(store, theirs)
    rf.mark_read(store, theirs, [there['scope_key']], ago(days=1))
    assert row(store, theirs)['last_read_at']


