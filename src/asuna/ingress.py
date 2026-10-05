"""Durable input boundary. No retrieval or model calls are allowed here."""
from .evidence import canonical, sha
from .state import Conflict, Denied, now


INTERNAL_KINDS = {'self_development': 'self-development', 'presence': 'presence', 'settlement': 'settlement',
                  'visit': 'visit'}
# Where each internal moment may happen: her visit is a group's (ADR-012 §4.2); the rest are private.
INTERNAL_SCENE_KIND = {'visit': 'group'}
# Core notices queued in a person's scene (task results, due plans). They wake the role but are not
# that person's words, so memory, summaries and the source list never treat them as speech.
CORE_NOTICE_KINDS = ('task_feedback', 'scheduled')
NOT_CORE_NOTICE = {'event.episode_kind': {'$nin': list(CORE_NOTICE_KINDS)}}


def episode_id(event):
    return 'ep-' + sha(canonical([event['scene_id'], event['event_id'],
                                event.get('episode_kind', 'external')]))[:32]


def persist_input(store, event, *, managed=False):
    scene = store.authorize(event['scene_id'], event['person_id'])
    # Host-origin opportunities (no user message): self-development, heartbeat, nightly settlement.
    internal = event.get('episode_kind') in INTERNAL_KINDS
    if internal and (event.get('adapter_id') != INTERNAL_KINDS[event['episode_kind']]
                     or scene['kind'] != INTERNAL_SCENE_KIND.get(event['episode_kind'], 'dm')):
        raise Denied('SELF_DEVELOPMENT_SOURCE_DENIED' if event['episode_kind'] == 'self_development' else 'INTERNAL_SOURCE_DENIED')
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
