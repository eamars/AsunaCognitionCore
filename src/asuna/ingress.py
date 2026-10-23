"""Durable input boundary. No retrieval or model calls are allowed here."""
from .evidence import canonical, sha
from .state import Conflict, Denied, now


INTERNAL_KINDS = {'self_development': 'self-development', 'presence': 'presence', 'settlement': 'settlement',
                  'visit': 'visit', 'note': 'note'}
# Where each internal moment may happen: her visit is a group's (ADR-012 §4.2); the rest are private. A note's own
# turn (ADR-018) is only ever at home; a note to a group arrives as a visit there.
INTERNAL_SCENE_KIND = {'visit': 'group'}
# Core notices queued in a person's scene (task results, due plans). They wake the role but are not
# that person's words, so memory, summaries and the source list never treat them as speech.
CORE_NOTICE_KINDS = ('task_feedback', 'scheduled', 'note')
# A line's author is who wrote it (ADR-089): the program for every row it makes. Who authorizes the turn stays on the
# event (`person_id`).
PROGRAM_AUTHOR = 'asuna:internal'
NOT_CORE_NOTICE = {'author': {'$ne': PROGRAM_AUTHOR}}


def author_of(event):
    """Who wrote this input: the program for its own moments and notices, else the person on the event."""
    kind = event.get('episode_kind')
    return PROGRAM_AUTHOR if kind in INTERNAL_KINDS or kind in CORE_NOTICE_KINDS else event['person_id']


def program_group_context(source):
    """The group context of the program's line about another line (a task result, a consult's question): the thread
    it belongs to, nothing of that line's own envelope. Nobody @'d her in it, it calls and answers nobody (ADR-089)."""
    group = ((source or {}).get('event') or {}).get('group_context')
    if not group:
        return None
    return {'wake_reason': None, 'topic_id': group.get('topic_id'), 'reply_to': None, 'reply_message_id': None,
            'mentioned_account_ids': []}


def episode_id(event):
    return 'ep-' + sha(canonical([event['scene_id'], event['event_id'],
                                event.get('episode_kind', 'external')]))[:32]


def persist_input(store, event, *, managed=False):
    scene = store.authorize(event['scene_id'], event['person_id'])
    # Host-origin opportunities (no user message): self-development, heartbeat, nightly settlement.
    internal = event.get('episode_kind') in INTERNAL_KINDS
    where = INTERNAL_SCENE_KIND.get(event.get('episode_kind'), 'dm')
    if event.get('episode_kind') == 'visit' and (event.get('visit') or {}).get('intent') == 'errand':
        where = ('group', 'dm') if scene.get('channel_id') else ()      # ADR-017: an owner errand, to a platform chat
    if internal and (event.get('adapter_id') != INTERNAL_KINDS[event['episode_kind']]
                     or scene['kind'] not in ((where,) if isinstance(where, str) else where)):
        raise Denied('SELF_DEVELOPMENT_SOURCE_DENIED' if event['episode_kind'] == 'self_development' else 'INTERNAL_SOURCE_DENIED')
    if event.get('episode_kind') == 'note':
        from .visibility import owner_private_scenes
        if scene['_id'] not in owner_private_scenes(store.config):
            raise Denied('INTERNAL_SOURCE_DENIED')
    key = episode_id(event)
    previous = store.db.messages.find_one({'_id': 'in-' + key})
    if previous:
        # The same line is the same text as received: a voice re-posted may settle differently the second time
        # (voice.py), and the first stored reading stands.
        received = (previous.get('event') or {}).get('received_text', previous['text'])
        if (previous['author'] != author_of(event) or received != event.get('received_text', event['text'])
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
               'scene_seq': sequence, 'text': event['text'], 'author': author_of(event),
               'direction': 'inbound', 'delivery_state': 'RECEIVED',
               'occurred_at': event.get('occurred_at', now()), 'received_at': now(),
               'character_context': scene.get('character_context', 'initial'),
               'event': event, 'host_managed': managed,
               # The Host's input queue tracks only the inputs it manages (input_state); the others have no queue state.
               **({'ingress_state': 'ACCEPTED'} if managed else {})}
    if internal:
        message['direction'] = 'internal'
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
