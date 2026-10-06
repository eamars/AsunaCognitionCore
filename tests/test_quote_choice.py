"""Whether her group line quotes the line that called her (publish._quote, owner 2026-10-06)."""
from types import SimpleNamespace

from asuna.publish import PublishService

GROUP = {'target': {'type': 'group', 'id': 'g'}}
DM = {'target': {'type': 'dm', 'id': 'p'}}
SCENE = {'_id': 'g1'}


def row(store, _id, direction, seq, **extra):
    store.db.messages.insert_one({'_id': _id, 'schema_version': 1, 'scene_id': 'g1', 'direction': direction,
                                  'scene_seq': seq, 'phase': 'SPEAK' if direction == 'outbound' else None, **extra})
    return store.db.messages.find_one({'_id': _id})


def quote(store, ep, msg, route=GROUP, source=None):
    me = SimpleNamespace(store=store)
    return PublishService._quote(me, ep, msg, SCENE, route, source or {'scene_seq': 10}, {'platform_event_id': 'called-me'})


def test_she_quotes_like_people_do_and_her_choice_wins(store):
    ep = {'_id': 'ep-1'}
    first = row(store, 'ep-1:speak:0', 'outbound', 11, episode_id='ep-1')
    second = row(store, 'ep-1:speak:1', 'outbound', 12, episode_id='ep-1')
    assert quote(store, ep, first) is None                       # nobody spoke since: a plain line
    assert quote(store, ep, first, route=DM) == 'called-me'      # direct chats as before
    assert quote(store, {**ep, 'quote': 'source'}, first) == 'called-me'
    assert quote(store, {**ep, 'quote': 'source'}, second) is None   # only her first message may quote
    row(store, 'in-other', 'inbound', 10.5, author='qq:9')
    assert quote(store, ep, first) == 'called-me'               # others spoke since: quote so it is clear
    assert quote(store, {**ep, 'quote': 'none'}, first) is None # a bot command goes out bare
