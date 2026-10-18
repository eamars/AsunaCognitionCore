"""Her line quotes only the line she chose (ADR-079 §9.4, publish._quote): the program never chooses a quote."""
from types import SimpleNamespace

from asuna.publish import PublishService

SCENE = {'_id': 'g1'}


def row(store, _id, direction, seq, **extra):
    store.db.messages.insert_one({'_id': _id, 'schema_version': 1, 'scene_id': 'g1', 'direction': direction,
                                  'scene_seq': seq, 'phase': 'SPEAK' if direction == 'outbound' else None, **extra})
    return store.db.messages.find_one({'_id': _id})


def quote(store, msg):
    return PublishService._quote(SimpleNamespace(store=store), msg, SCENE)


def test_she_quotes_only_the_line_she_chose(store):
    row(store, 'in-a', 'inbound', 10, event={'channel': {'platform_event_id': 'pe-a'}})
    row(store, 'out-b', 'outbound', 11, platform_message_id='pm-b', delivery_state='DELIVERED')
    row(store, 'in-other', 'inbound', 12, author='qq:9')
    plain = row(store, 'ep-1:speak:0', 'outbound', 13, episode_id='ep-1')
    assert quote(store, plain) is None, 'others spoke since, and still nothing is quoted unless she chose'
    assert quote(store, {**plain, 'quote_line': 'in-a'}) == 'pe-a'
    assert quote(store, {**plain, 'quote_line': 'out-b'}) == 'pm-b', 'her own line, to amend it'
    assert quote(store, {**plain, 'quote_line': 'gone'}) is None
