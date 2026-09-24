"""Durable input boundary. No retrieval or model calls are allowed here."""
from .evidence import canonical, sha
from .state import Conflict, Denied, now


def episode_id(event):
    return 'ep-' + sha(canonical([event['scene_id'], event['event_id'],
                                event.get('episode_kind', 'external')]))[:32]


def persist_input(store, event, *, managed=False):
    scene = store.authorize(event['scene_id'], event['person_id'])
    internal = event.get('episode_kind') == 'self_development'
    if internal and (event.get('adapter_id') != 'self-development' or scene['kind'] != 'dm'):
        raise Denied('SELF_DEVELOPMENT_SOURCE_DENIED')
    key = episode_id(event)
    previous = store.db.messages.find_one({'_id': 'in-' + key})
    if previous:
        if (previous['author'] != ('asuna:internal' if internal else event['person_id']) or previous['text'] != event['text']
                or previous['policy_epoch'] != scene['policy_epoch']
                or previous.get('event', {}).get('integration_profile') != event.get('integration_profile')):
            raise Denied('INPUT_IDENTITY_OR_CONTENT_CONFLICT')
        return previous, False
    sequence = store.db.scenes.find_one_and_update(
        {'_id': scene['_id']}, {'$inc': {'sequence': 1}}, return_document=True)['sequence']
    message = {'_id': 'in-' + key, 'episode_id': key,
               'adapter_id': event.get('adapter_id', 'fixture'),
               'platform_event_id': event['event_id'], 'scene_id': scene['_id'],
               'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
               'scene_seq': sequence, 'text': event['text'], 'author': event['person_id'],
               'direction': 'inbound', 'delivery_state': 'RECEIVED',
               'occurred_at': event.get('occurred_at', now()), 'received_at': now(),
               'character_context': scene.get('character_context', 'initial'),
               'event': event, 'host_managed': managed, 'ingress_state': 'ACCEPTED'}
    if internal:
        message['direction'] = 'internal'
        message['author'] = 'asuna:internal'
    try:
        return store.put('messages', message, stream=key), True
    except Conflict:
        # A duplicate HTTP arrival may race the first durable write.
        if not store.db.messages.find_one({'_id': 'in-' + key}):
            raise
        return persist_input(store, event, managed=managed)[0], False


def input_state(store, key, state, **extra):
    message = store.db.messages.find_one({'_id': 'in-' + key})
    if message and message.get('host_managed'):
        return store.put('messages', {**message, 'ingress_state': state, **extra},
                         expected=message['revision'], stream=key)
