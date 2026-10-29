"""Authenticated transport-neutral adapter seam. Platform protocol belongs to the adapter."""
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

from . import clock
from .evidence import canonical, sha
from .config import redact_text, character_id
from .queue import database_effects_lock
from .state import Denied, now
from .ingress import PROGRAM_AUTHOR
from .people import People
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import tasks as task_records

INBOUND_SLOW_SECONDS = 2.0       # an admission this slow records where it waited (host.inbound_slow)
STACKS_AFTER_SECONDS = 1.0       # ... with every thread's stack as it stood this far into the admission
STACK_DEPTH = 12


def thread_stacks(admitting):
    """Every other thread's innermost frames as `file:line function` (file names and code only, never a value);
    `admitting` (a thread ident) is shown as `admission`."""
    names, seen, stacks = {t.ident: t.name for t in threading.enumerate()}, {}, {}
    for ident, frame in sys._current_frames().items():
        if ident == threading.get_ident():
            continue                  # the thread taking the snapshot
        name = 'admission' if ident == admitting else names.get(ident, 'unnamed')
        seen[name] = seen.get(name, 0) + 1
        stacks[name if seen[name] == 1 else '%s #%d' % (name, seen[name])] = [
            '%s:%d %s' % (os.path.basename(f.filename), f.lineno, f.name)
            for f in traceback.extract_stack(frame)[-STACK_DEPTH:]]
    return stacks

try:                                  # 出站图片附件：元数据、字节端点的围栏都在 outbound_media
    from . import outbound_media
except Exception:                     # 同目录平铺加载（离线自检）也认
    import outbound_media


def route_for_scene(config, channel_id, scene_id):
    channel = config.get('channels', {}).get(channel_id)
    if channel:
        for route in channel['routes'].values():
            if route['scene_id'] == scene_id:
                return route
    raise Denied('CHANNEL_ROUTE_NOT_AUTHORIZED')


def route_members(route):
    if route['target']['type'] == 'dm':
        return {route['sender_id']: route}
    if route['target']['type'] == 'group':
        return route.get('members', {})
    raise Denied('CHANNEL_TARGET_TYPE_DENIED')


# A line the adapter knows is not addressed to her (a peer's turn that did not answer her): stored, no turn.
ASIDE_KEY = 'asuna_aside'
REPLY_ONLY_KEY = 'asuna_reply_only'          # the line only quotes another, with no words of its own (ADR-079)


def kept_raw(event, raw, mentioned=None):
    """What of the adapter's raw event the host keeps: the sender profile verified against this
    authenticated sender and group, the profiles of the people it @-mentions (each bound to a mentioned
    account and this group), the normalized media block, the messages of a merged forward, and the group's name. The platform event
    itself (and anything else an adapter puts there) is never stored."""
    from .peer_context import MENTIONED_KEY, snapshot_event, snapshot_mentioned
    from .vision import MEDIA_KEY
    raw = raw if isinstance(raw, dict) else {}
    kept = {}
    peer = snapshot_event({**event, 'raw': raw})
    if peer:
        kept['asuna_peer'] = peer
    profiles = snapshot_mentioned(event, raw, mentioned)
    if profiles:
        kept[MENTIONED_KEY] = profiles
    if isinstance(raw.get(MEDIA_KEY), dict):
        kept[MEDIA_KEY] = raw[MEDIA_KEY]
    from . import forwards
    forwarded = forwards.kept(raw)
    if forwarded:
        kept[forwards.KEY] = forwarded                     # what a merged forward carried (forwards.py)
    if isinstance(raw.get('group_name'), str) and raw['group_name'].strip():
        kept['group_name'] = ' '.join(raw['group_name'].split())[:60]
    from .caught_up import CATCHUP_KEY, mark
    if mark(raw):
        kept[CATCHUP_KEY] = mark(raw)                         # a line fetched from history after a gap (caught_up.py)
    if raw.get(REPLY_ONLY_KEY) is True:
        kept[REPLY_ONLY_KEY] = True
    if raw.get(ASIDE_KEY) is True:
        kept[ASIDE_KEY] = True                                # not addressed to her: kept, does not wake her (ADR-045)
    from . import notices
    notice = notices.kept(raw)
    if notice:
        kept[notices.KEY] = notice                            # a platform notice projected to words (notices.py)
    from . import channel_kinds
    from .questions import ANSWER_KEY, ID
    answer = raw.get(ANSWER_KEY)
    if channel_kinds.home(event.get('scene_id')) and isinstance(answer, dict) and isinstance(answer.get('question'), str) \
            and ID.fullmatch(answer['question']):
        kept[ANSWER_KEY] = {'question': answer['question']}     # a trusted line answering one of her questions (ADR-061)
    own = raw.get('asuna_self')
    if (event.get('channel') or {}).get('target', {}).get('type') == 'group' and isinstance(own, dict) \
            and own.get('role') in ('owner', 'admin', 'member'):
        kept['asuna_self'] = {'role': own['role']}            # her own role in this group (group_admin.py)
    return kept


def called_by_name(store, text):
    """Whether a message says one of her names (her display name and the persona's other names, 2+ characters)."""
    text = ' '.join(str(text or '').split())
    return any(len(name) >= 2 and name in text for name in People(store).self_names)


# A line of hers addressed to someone waits for their answer: the people she @-tagged and the person she answered.
# Their next unaddressed line within this long gets her one look (owner 2026-10-06: by default, like a reply; she
# turns it off for a line with await_answer). Human answers in her groups: median 40 s, 90% within ~3 min.
AWAIT_SECONDS = 180


def addressees(store, scene, line):
    """The people her line is addressed to: whoever she @-tagged by label, and the author of the line she answered."""
    from .people import LABEL_MENTION
    people = People(store)
    handles = {match.group('handle') or match.group('bare') for match in LABEL_MENTION.finditer(line.get('text') or '')}
    found = {people.person(doc.get('person')) for doc in people.roster(scene['_id']).values()
             if str(doc.get('handle')) in handles and doc.get('person')}
    answered = message_records.get(store, line.get('reply_to'), fields=['author', 'direction']) or {}
    if answered.get('direction') == 'inbound' and answered.get('author') and answered['author'] != PROGRAM_AUTHOR:
        found.add(people.person(answered['author']))
    return found


def awaited_answer(store, scene, person_id, mentions, reply):
    """Whether this unaddressed line may be the answer her last line here waits for: her newest delivered line in
    this group was addressed to this person (or she asked for an answer from anyone with await_answer), it was under
    AWAIT_SECONDS ago, she did not turn the wait off, the line @s or quotes no one else, and hers has not had its
    look yet."""
    if mentions or reply:
        return False                   # addressed to someone: an @ or quote of her is already its own wake
    mine = message_records.spoken(store, scene['_id'], scene['policy_epoch'],
                                  author=character_id(store.config)).first(newest_first=True)
    if not mine or not mine.get('receipt_at'):
        return False
    try:
        since = clock.now() - datetime.fromisoformat(str(mine['receipt_at']).replace('Z', '+00:00'))
    except ValueError:
        return False
    if since.total_seconds() > AWAIT_SECONDS:
        return False
    choice = (episode_records.get(store, mine.get('episode_id'), fields=['await_answer']) or {}).get('await_answer')
    if (choice or {}).get('off'):
        return False
    asked = addressees(store, scene, mine)
    if asked:
        if People(store).person(person_id) not in asked:
            return False
    elif not choice:
        return False                   # addressed to nobody and no wait asked for: a remark of hers
    return not message_records.woken(store, scene['_id'], 'awaited_answer', after=mine.get('scene_seq', 0))


def reply_parent(store, scene, reply, at=None, *, outbound_author=None):
    """A reused platform id resolves within this scene to the latest line no later than the reply.

    A line without a readable time cannot be shown to be later, so it stays a candidate, ranked below every dated one.
    """
    def moment(value):
        try:
            date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
        except (ValueError, TypeError):
            return None
    ceiling = moment(at) or clock.now()
    undated = datetime.min.replace(tzinfo=timezone.utc)
    candidates = message_records.by_platform_id(store, scene['_id'], scene['policy_epoch'], platform_id=reply,
                                                author=outbound_author or None).rows()
    eligible = []
    for row in candidates:
        field = 'occurred_at' if row['direction'] == 'inbound' else 'receipt_at'
        when = moment(row.get(field) or row.get('received_at')) or undated
        if when <= ceiling:
            eligible.append((when, row.get('scene_seq') or 0, str(row['_id']), row))
    return max(eligible, key=lambda item: item[:3])[3] if eligible else None


def group_context(store, route, body, event_id, person_id=None):
    """Bind a normalized reply to an actual record in this group and epoch."""
    mentions = body.get('mentioned_account_ids', [])
    if not isinstance(mentions, list) or len(mentions) > 100 or any(not isinstance(v, str) for v in mentions):
        raise ValueError('INVALID_MENTIONS')
    reply = body.get('reply_to')
    if reply is not None and (not isinstance(reply, str) or not 1 <= len(reply) <= 200):
        raise ValueError('INVALID_REPLY_ID')
    scene = scene_records.get(store, route['scene_id'])
    parent = None
    if reply:
        parent = reply_parent(store, scene, reply, body.get('occurred_at'),
                              outbound_author=character_id(store.config))
    reason = 'mentioned_account' if body['account_id'] in mentions else None
    from .caught_up import stale as _stale
    late = _stale(body.get('raw'), body.get('occurred_at'))     # caught up after a gap and no longer fresh
    topic = topic_via = None
    if parent:
        previous = parent.get('event', {}).get('group_context', {})
        recent = parent.get('received_at', parent.get('receipt_at', '')) >= (clock.now()-timedelta(minutes=30)).isoformat()
        if parent['direction'] == 'outbound':
            reason = reason or 'reply_to_character'
            origin = message_records.get(store, 'in-'+parent['episode_id'])
            topic = (origin or {}).get('event', {}).get('group_context', {}).get('topic_id')
            topic_via = 'reply_to_character'
        elif previous.get('wake_reason') and recent:
            # 唤醒口径不变：父行本身被唤醒过（或她回过我）才算"活跃话题里的接话"。
            reason = reason or 'reply_in_active_topic'
            topic, topic_via = previous.get('topic_id'), 'reply_in_active_topic'
        elif previous.get('topic_id'):
            # P5：旁听来的那条线也认得出属于哪个话题，只是不因此唤醒她。
            topic, topic_via = previous['topic_id'], 'reply_chain'
    if not reason and called_by_name(store, body.get('text')):
        # Her name without an @: the relevance gate decides whether that was meant for her (attend.py).
        reason = 'name_called'
    if not reason and person_id and not late and awaited_answer(store, scene, person_id, mentions, reply):
        reason = 'awaited_answer'          # one look, through the relevance gate (attend.py)
    if not reason and person_id and not late and not mentions and not reply:
        from . import questions
        if questions.wants_look(store, scene, person_id):
            reason = 'question_wait'       # her question here still waits: one look per person (ADR-061 step 2)
    answers_her = False
    if reason in ('mentioned_account', 'reply_to_character') and person_id and not late:
        # ADR-086 E1: an @ or a reply to her that answers what she waits for or asked must wake her (attend.gated).
        from . import questions
        answers_her = bool(awaited_answer(store, scene, person_id, [], None) or questions.wants_look(store, scene, person_id))
    if late and reason in ('mentioned_account', 'reply_to_character'):
        reason = 'catchup_mention'         # an old @ or reply to her asks her first (attend.GATED)
    if topic is None:
        topic, topic_via = event_id, (topic_via or ('mentioned' if reason else 'new'))
    return {'wake_reason': reason, 'topic_id': topic, 'topic_via': topic_via,
            'reply_to': reply, 'reply_message_id': parent['_id'] if parent else None,
            'mentioned_account_ids': mentions, **({'answers_her': True} if answers_her else {})}


def route_key(channel_token, route_id):
    """The key that opens one route of a channel whose kind declares ROUTE_KEYS (ADR-033 D4): derived from the
    channel's token, so nothing new is stored, and useless for any other route or channel."""
    digest = hmac.new(channel_token.encode(), ('asuna-route-key:' + route_id).encode(), hashlib.sha256).hexdigest()
    return 'route-%s.%s' % (route_id, digest)


def route_keys_allowed(channel_id):
    from . import channel_kinds
    return bool(getattr(channel_kinds.get(channel_id), 'ROUTE_KEYS', False))


class Channels:
    def __init__(self, controller):
        self.controller = controller
        self.store = controller.app.store

    def authenticate(self, channel_id, authorization):
        """(channel, route id) for the bearer: the channel's own token opens all of it (route None); a route key
        opens that route alone, on a kind that declares ROUTE_KEYS."""
        channel = self.store.config.get('channels', {}).get(channel_id)
        if channel and secrets.compare_digest(authorization, 'Bearer ' + channel['token']):
            return channel, None
        if channel and route_keys_allowed(channel_id) and authorization.startswith('Bearer route-'):
            route_id = authorization[len('Bearer route-'):].partition('.')[0]
            if route_id in channel.get('routes', {}) and secrets.compare_digest(
                    authorization, 'Bearer ' + route_key(channel['token'], route_id)):
                return channel, route_id
        raise Denied('CHANNEL_AUTH_REQUIRED')

    def route_target(self, channel_id, route_id):
        return self.store.config['channels'][channel_id]['routes'][route_id]['target']

    OWNER_LINES_PER_CLAIM = 20       # the owner's lines one outbox claim hands an agent; the rest come with the next

    def owner_lines(self, channel_id, route_id):
        """What the owner wrote on this line from the Web (ADR-051) that its agent has not been shown yet, oldest
        first, each shown once: the agent never reads her answer to words it never saw."""
        from . import channel_kinds
        scene_id = self.store.config['channels'][channel_id]['routes'][route_id]['scene_id']
        owner = self.store.config['chat']['person_id']
        if not channel_kinds.owner_joins(scene_id):
            return []
        shown = []
        while len(shown) < self.OWNER_LINES_PER_CLAIM:
            row = message_records.claim_unshown(self.store, scene_id, owner, now())
            if not row:
                break
            shown.append({'id': row['_id'], 'seq': row.get('scene_seq'), 'text': row.get('text') or '',
                          'at': row.get('received_at')})
        return shown

    def line_closed(self, channel_id, route_id):
        from . import lines
        return lines.is_closed(self.store, self.store.config['channels'][channel_id]['routes'][route_id]['scene_id'])

    def scope_check(self, channel_id, route_id, command, path, body):
        """A route key posts as its own route, claims and confirms its own line's words, and nothing else."""
        if command == 'POST' and path == ['events']:
            if body.get('route_id') != route_id:
                raise Denied('ROUTE_KEY_OTHER_ROUTE')
        elif command == 'GET' and path == ['outbox']:
            pass
        elif command == 'POST' and len(path) == 3 and path[0] == 'outbox' and path[2] == 'receipt':
            row = message_records.get(self.store, path[1], fields=['target'], channel=channel_id)
            if not row or row.get('target') != self.route_target(channel_id, route_id):
                raise Denied('ROUTE_KEY_OTHER_ROUTE')
        else:
            raise Denied('ROUTE_KEY_ENDPOINT_DENIED')

    def members(self, channel_id, body):
        from . import group_members
        return group_members.receive(self.store, channel_id, body)

    def media_keys(self, channel_id, body):
        from . import media_keys
        return media_keys.receive(channel_id, body)

    def faults(self, channel_id, body):
        """The adapter's lane faults, counted by signature and hour (lane_faults.py, ADR-095)."""
        from . import lane_faults
        return lane_faults.receive(self.store, channel_id, body)

    def notices(self, channel_id, body):
        from . import notices
        return notices.home(self.store, self.controller, channel_id, body)

    def voice(self, channel_id, fields, data, media_type=None):
        """One voice of a line about to be posted, transcribed now; its outcome waits for the line (voice.py)."""
        from . import voice
        return voice.receive(channel_id, fields, data, media_type)

    def own_mute(self, channel_id, body):
        from . import own_mute
        with database_effects_lock(self.store.name):
            return own_mute.receive(self.store, channel_id, body)

    def receive(self, channel_id, body):
        # Admission and input persistence share the controller's existing fence.
        from .chat import INGRESS_TIMING as timing
        started, waited = time.monotonic(), None
        timing.__dict__.clear()
        snapshot, admitting = {}, threading.get_ident()

        def take():
            try:
                snapshot.update(stacks_at=round(time.monotonic() - started, 3), stacks=thread_stacks(admitting))
            except Exception:
                pass
        timer = threading.Timer(STACKS_AFTER_SECONDS, take)
        timer.daemon = True
        timer.start()
        try:
            with self.controller.ingress_lock:
                waited = time.monotonic() - started
                if self.controller.reconfiguring or self.controller.stopping.is_set():
                    raise RuntimeError('HOST_RECONFIGURING')
                return self._receive(channel_id, body)
        finally:
            timer.cancel()
            total = time.monotonic() - started
            if total >= INBOUND_SLOW_SECONDS:
                self._record_slow(channel_id, total, waited, dict(vars(timing)), dict(snapshot))

    def _record_slow(self, channel_id, total, waited, stages, snapshot=None):
        """Where a slow admission spent its seconds: the fence (`fence_wait`), the line's write (`persist`), its projection
        to the Web UI (`project`: `channel_input`, then the worker's `output_lock_wait` and `output_write`), and the rest
        of the admission (`other`: the checks and reads before the write). `stacks` is every thread's stack as it stood
        `stacks_at` seconds in (a snapshot taken much later than asked means no thread could run Python then).
        Recorded after the fence is released; a failure to record is never the admission's."""
        try:
            known = (waited or 0) + stages.get('persist', 0) + stages.get('project', 0)
            self.controller.app.evidence.record('host.inbound_slow', {
                'channel_id': channel_id, 'total': round(total, 3),
                'fence_wait': None if waited is None else round(waited, 3),
                **{k: round(v, 3) for k, v in stages.items()}, 'other': round(max(0.0, total - known), 3),
                **(snapshot or {})})
        except Exception:
            pass

    def _receive(self, channel_id, body):
        allowed = {'route_id', 'account_id', 'sender_id', 'event_id', 'text', 'raw', 'occurred_at', 'mentioned_account_ids', 'reply_to', 'group_id'}
        if set(body) - allowed:
            raise Denied('CHANNEL_ENVELOPE_FIELD_DENIED')
        # Reject malformed payloads before any automatic enrollment writes.
        if not isinstance(body.get('event_id'), str) or not 1 <= len(body['event_id']) <= 200:
            raise ValueError('INVALID_PLATFORM_EVENT_ID')
        if not isinstance(body.get('text'), str) or not 1 <= len(body['text']) <= 16000:
            raise ValueError('INVALID_MESSAGE_TEXT')
        if 'occurred_at' in body and not isinstance(body['occurred_at'], str):
            raise ValueError('INVALID_OCCURRED_AT')
        if body.get('group_id') is None and any(k in body for k in ('group_id', 'mentioned_account_ids')):
            raise Denied('DM_GROUP_FIELDS_DENIED')     # a private chat's quote (reply_to) is its own (ADR-079)
        mentions, reply = body.get('mentioned_account_ids', []), body.get('reply_to')
        if not isinstance(mentions, list) or len(mentions) > 100 or any(not isinstance(v, str) for v in mentions):
            raise ValueError('INVALID_MENTIONS')
        if reply is not None and (not isinstance(reply, str) or not 1 <= len(reply) <= 200):
            raise ValueError('INVALID_REPLY_ID')
        channel = self.store.config['channels'][channel_id]
        if channel.get('admission') == 'automatic' or channel.get('blocked_senders') or channel.get('blocked_groups'):
            from .channel_admission import admit
            admit(self.controller, channel_id, body)
        route = channel['routes'].get(body.get('route_id'))
        member = route_members(route).get(body.get('sender_id')) if route else None
        if not member or body.get('account_id') != channel['account_id']:
            raise Denied('CHANNEL_IDENTITY_DENIED')
        if route['target']['type'] == 'group' and body.get('group_id') != route['target']['id']:
            raise Denied('CHANNEL_GROUP_DENIED')
        if route['target']['type'] == 'dm' and any(k in body for k in ('group_id', 'mentioned_account_ids')):
            raise Denied('DM_GROUP_FIELDS_DENIED')
        if not isinstance(body.get('event_id'), str) or not 1 <= len(body['event_id']) <= 200:
            raise ValueError('INVALID_PLATFORM_EVENT_ID')
        if not isinstance(body.get('text'), str) or not 1 <= len(body['text']) <= 16000:
            raise ValueError('INVALID_MESSAGE_TEXT')
        if 'occurred_at' in body and not isinstance(body['occurred_at'], str):
            raise ValueError('INVALID_OCCURRED_AT')
        # Namespaced by connection/account/scene; same text/time is not deduplication.
        identity = [channel_id, channel['account_id'], route['scene_id'], body['event_id']]
        if 'occurred_at' in body:
            identity.append(body['occurred_at'])
        event_id = 'channel-' + sha(canonical(identity))
        event = {'event_id': event_id, 'scene_id': route['scene_id'], 'person_id': member['person_id'],
                 'adapter_id': channel_id, 'text': body['text'],
                 'channel': {'id': channel_id, 'account_id': channel['account_id'],
                             'platform_event_id': body['event_id'], 'target': route['target'], 'sender_id': body['sender_id']}}
        event['raw'] = kept_raw(event, body.get('raw'), body.get('mentioned_account_ids'))
        from . import voice
        voices = voice.entries_for(self.store, channel_id, body, event['raw'])
        if voices:
            # Settled before the line came (voice.py, ADR-093): the line is stored as it reads, each voice's words in
            # its place, so every reader (and the wake checks below) has the words; what came is kept beside it.
            event.update(voice=voices, received_text=body['text'], text=voice.read_text(body['text'], voices))
            body = {**body, 'text': event['text']}
        from . import media_keys
        media_keys.saw(event)                              # a signed picture link that just arrived (ADR-035)
        from . import notices
        notice = event['raw'].get(notices.KEY)
        scene = scene_records.get(self.store, route['scene_id']) if notice else None
        if notice:
            # A notice reads as the program's line (people.transcript); its {line} is the line it is about.
            text, hers, line_row = notices.fill(self.store, scene or {'_id': route['scene_id']}, notice, body['text'])
            if line_row:
                # Her reading names the line when she reads it (notices.words); the stored text is for any reader.
                notice = {**notice, 'line': {**notice['line'], 'row': line_row}, 'words': body['text']}
            if notice.get('gate') == 'reacted' and not hers:
                # A reaction between other people: kept like a notice without a gate, it does not ask for a look.
                notice = {key: value for key, value in notice.items() if key != 'gate'}
            event['raw'][notices.KEY] = notice
            event['text'] = text
        if route['target']['type'] == 'group':
            event['group_context'] = group_context(self.store, route, body if not notice else
                                                   {**body, 'text': '', 'mentioned_account_ids': []},
                                                   event_id, None if notice else member['person_id'])
            if notice:
                event['group_context'].update(wake_reason=notice.get('gate'),
                                              mentioned_account_ids=body.get('mentioned_account_ids', []))
        elif body.get('reply_to'):
            # ADR-079: a quote in a private chat binds to the line it quotes, as a group's does (group_context).
            here = scene_records.get(self.store, route['scene_id'])
            parent = reply_parent(self.store, here, body['reply_to'], body.get('occurred_at'),
                                  outbound_author=character_id(self.store.config)) if here else None
            event['reply'] = {'reply_to': body['reply_to'], 'reply_message_id': parent['_id'] if parent else None}
        if 'occurred_at' in body:
            event['occurred_at'] = body['occurred_at']
        from . import lines
        if lines.is_closed(self.store, route['scene_id']):
            return {'status': 'line_closed'}           # she closed this peer line: passed over, never replayed
        from . import watches
        watched = None if notice else watches.seen(self.store, member['person_id'])
        if watched:
            # Someone on her watchlist spoke: she hears of it here, where they spoke (owner 2026-10-06).
            event['watched'] = watched['_id']
            if 'group_context' in event and not event['group_context']['wake_reason']:
                event['group_context']['wake_reason'] = 'watched'     # one look, through the relevance gate
        from . import switches
        blocked = switches.blocked(self.store, member['person_id'])
        if blocked and notice:
            return {'status': 'dropped'}                    # ADR-052: a notice from someone she blocked: nowhere
        if blocked:
            # ADR-052: someone she blocked: kept and searchable, wakes her nowhere, not addressed to her.
            event['blocked'] = blocked['_id']
            if 'group_context' in event:
                event['group_context'].update(wake_reason=None, blocked=event['group_context']['wake_reason'])
        if 'group_context' in event:
            # ADR-039: in a group she lets rest, only what is meant for her wakes her (focus.RESTING_WAKES). A notice
            # that asks for a look (a poke at her, a reaction to her line) gets it in any group: her relevance gate
            # decides (ADR-064, owner 2026-10-16).
            from . import focus
            reason = event['group_context']['wake_reason']
            kept = reason if notice and notice.get('gate') else focus.wake(
                self.store, scene_records.get(self.store, route['scene_id']), reason)
            if kept != reason:
                event['group_context'].update(wake_reason=kept, resting=reason)
            if notice and not event['group_context']['wake_reason']:
                # Not for a look: shown once in this group's next turn, kept until then (notices.py).
                notices.hold(self.store, route['scene_id'], {'author': member['person_id'], 'text': event['text'],
                                                 'scene_id': route['scene_id'], 'received_at': now(),
                                                 **({'occurred_at': event['occurred_at']} if 'occurred_at' in event
                                                    else {}), 'event': event})
                return {'status': 'held'}
        return self.controller.receive(event)

    def _valid_publication(self, message, channel_id):
        if not message or message.get('channel_id') != channel_id:
            raise Denied('PUBLICATION_NOT_FOUND')
        route = route_for_scene(self.store.config, channel_id, message['scene_id'])
        episode = episode_records.get(self.store, message['episode_id'])
        channel = self.store.config['channels'][channel_id]
        allowed = {grant['person_id'] for sender, grant in route_members(route).items()
                   if sender not in channel.get('blocked_senders', [])}
        from . import channel_kinds
        if channel_kinds.owner_joins(message['scene_id']):
            allowed.add(self.store.config['chat']['person_id'])          # the owner on his home line (ADR-051)
        if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
            allowed.clear()
        if not episode or episode['person_id'] not in allowed:
            raise Denied('PUBLICATION_MEMBER_REVOKED')
        scene = scene_records.authorize(self.store, message['scene_id'], episode['person_id'])
        if (message['policy_epoch'] != scene['policy_epoch'] or message['scope_key'] != scene['scope_key']
                or message['target'] != route['target']
                or message['channel_account_id'] != self.store.config['channels'][channel_id]['account_id']):
            raise Denied('PUBLICATION_CONTEXT_STALE')
        # A part of her reply leaves while her turn still runs (ADR-064 phase 2), as in publish._publish.
        speaking = ('SPEAK_ACCEPTED', 'WAITING_TASK', 'COMMITTED') + (('TURN',) if message.get('reply_part') else ())
        if not episode or episode['state'] not in speaking:
            raise Denied('PUBLICATION_EPISODE_STALE')
        if episode.get('task_id'):
            task = task_records.get(self.store, episode['task_id'])
            if not task or task['intent_revision'] != episode['intent_revision'] or task['state'] in ('CANCELLED', 'STALE'):
                raise Denied('PUBLICATION_INTENT_STALE')

    # A part of her turn waits for the parts before it: while one is still on its way the later ones wait; once one has
    # settled without arriving (failed, unknown, cancelled after a failure) the later ones never go.
    PART_ON_ITS_WAY = ('READY', 'QUEUED_EXTERNAL', 'SENDING')
    PART_SETTLED = ('DELIVERED', 'CANCELLED_BY_HER')            # one she took back is settled

    def _next(self, channel_id, queued, chat=True):
        """The next line to hand out: the first queued one whose conversation is not waiting. A paced part holds its
        conversation until its time and until the parts before it are delivered, so later lines there never overtake
        it (ADR-009 §11.1); it holds no other conversation. A part whose earlier part will never arrive is cancelled
        here, whenever it was queued: cancel_after reaches only the parts that existed when that one failed.
        Conversations take turns by when their oldest queued line was queued (scene_seq counts within one conversation
        only); within one, lines go in their order.

        ADR-095: for the chat lane (`chat`), a conversation with a chat line out (SENDING, claimed within
        CHAT_LEASE_SECONDS) is held too, so an adapter running several sends at once never has two of one conversation
        out. A file is no earlier part on its way for anyone: it goes on the bulk lane and holds nothing (files don't
        hold chat, owner 2026-10-23); a file waits for the chat parts before it like any part."""
        from .outbound_files import KIND
        held, rows, first = set(), queued.rows(), {}
        if chat and rows:
            lease = (clock.now() - timedelta(seconds=CHAT_LEASE_SECONDS)).isoformat()
            held.update(message_records.in_flight_scenes(self.store, channel_id, lease))
        for row in rows:
            first[row['scene_id']] = min(first.get(row['scene_id'], '~'), str(row.get('queued_at') or ''))
        rows.sort(key=lambda row: (first[row['scene_id']], row['scene_seq']))
        for row in rows:
            if row['scene_id'] in held:
                continue
            if row.get('segment_index'):
                earlier = message_records.turn_parts(
                    self.store, row['episode_id'], before_segment=row['segment_index'],
                    not_states=self.PART_SETTLED, by=None).rows(fields=['delivery_state', KIND])
                if any(part['delivery_state'] not in self.PART_ON_ITS_WAY for part in earlier):
                    message_records.save(self.store, {**row, 'delivery_state': 'CANCELLED_AFTER_FAILURE'},
                                         expected=row['revision'], stream=row['episode_id'])
                    continue
                # a file on its way holds nothing (the bulk lane); a chat part on its way holds the parts after it
                if any(part['delivery_state'] in self.PART_ON_ITS_WAY and not part.get(KIND) for part in earlier):
                    held.add(row['scene_id'])
                    continue
            if row.get('not_before') and row['not_before'] > now():
                held.add(row['scene_id'])
                continue
            return row
        return None

    def claim(self, channel_id, wait_seconds=0, supports=None, target=None, lane='chat'):
        # supports 是领取方声明的能力（napcat-qq 0.5.0 起带 supports=image）。没声明就只给文字，并把
        # 「这条本来带图、图没跟着出去」记在行上：只发文字却报平台已送达，等于声称对方收到一张没到的图。
        from . import capabilities, group_admin, outbound_files
        capabilities.declared(self.store, channel_id, supports)     # what this adapter carries (ADR-079 §9.7)
        supports, limits = capabilities.split(supports)             # names as declared; file:<bytes> keeps its limit
        deadline = time.monotonic() + min(25, max(0, wait_seconds))
        expired = []                      # file rows failed with FILE_BYTES_EXPIRED: their originals are looked at unlocked
        while not self.controller.stopping.is_set():
            while expired:
                outbound_files.expired_source(self.store, expired.pop())
            if self.controller.reconfiguring:
                return {'items': []}
            with database_effects_lock(self.store.name):
                # an admin action goes first, on the chat lane (or the one lane of an adapter that names none)
                action = None if target or lane == 'bulk' else group_admin.claim(self.store, channel_id)
                if action:
                    return {'items': [action], 'lane': lane}
                # ADR-095: files on the bulk lane, everything else on the chat lane. An adapter that declares no
                # files has no bulk lane: its chat claims meet the file rows and fail them, as before; one that names
                # no lane (from before ADR-095) gets everything on its one lane.
                files = True if lane == 'bulk' else (
                    False if lane == 'chat' and outbound_files.CAPABILITY in (supports or ()) else None)
                # a route key claims only its own line's words (ADR-033)
                queued = message_records.queued(self.store, channel_id, files=files, target=target or None)
                row = self._next(channel_id, queued, chat=lane != 'bulk')
                if row:
                    try:
                        self._valid_publication(row, channel_id)
                    except Denied as exc:
                        failed = message_records.save(self.store, {**row, 'delivery_state': 'FAILED',
                                                      'failure': str(exc)},
                                                      expected=row['revision'], stream=row['episode_id'])
                        from .publish import PublishService
                        PublishService(self.store).cancel_after(failed)
                        continue
                    act = row.get('action') if isinstance(row.get('action'), dict) else None
                    if act and act.get('kind') not in (supports or ()):
                        # A poke or a reaction this adapter did not declare is not done at all (ADR-064 phase 2).
                        failed = message_records.save(
                            self.store, {**row, 'delivery_state': 'FAILED',
                                         'failure': 'CHANNEL_DOES_NOT_DECLARE_' + str(act.get('kind')).upper()},
                            expected=row['revision'], stream=row['episode_id'])
                        from .publish import PublishService
                        PublishService(self.store).cancel_after(failed)
                        continue
                    sticker = row.get('sticker') if isinstance(row.get('sticker'), dict) else None
                    if sticker and 'sticker' not in (supports or ()):
                        # A sticker is the whole message: one this adapter cannot send is not sent at all (ADR-016).
                        failed = message_records.save(self.store, {**row, 'delivery_state': 'FAILED',
                                                      'failure': 'CHANNEL_DOES_NOT_DECLARE_STICKER'},
                                                      expected=row['revision'], stream=row['episode_id'])
                        from .publish import PublishService
                        PublishService(self.store).cancel_after(failed)
                        continue
                    sent_file = row.get(outbound_files.KIND) if isinstance(row.get(outbound_files.KIND), dict) else None
                    if sent_file:
                        # A file is the whole message: one this adapter cannot carry, whose bytes are gone or that is over
                        # the limit it declared is not sent at all (ADR-092).
                        failing = ({'failure': 'CHANNEL_DOES_NOT_DECLARE_FILE'}
                                   if outbound_files.CAPABILITY not in supports
                                   else outbound_files.claim_failure(self.store, row, limits))
                        if failing:
                            failed = message_records.save(self.store, {**row, 'delivery_state': 'FAILED', **failing},
                                                          expected=row['revision'], stream=row['episode_id'])
                            from .publish import PublishService
                            PublishService(self.store).cancel_after(failed)
                            if failing['failure'] == 'FILE_BYTES_EXPIRED':
                                expired.append(row['_id'])
                            continue
                    attempt = uuid.uuid4().hex
                    declared = outbound_media.descriptor(row)
                    carries = bool(declared) and outbound_media.supports_image(supports)
                    changes = {**row, 'delivery_state': 'SENDING', 'attempt_id': attempt, 'claimed_at': now()}
                    if declared and not carries:
                        changes[outbound_media.SKIPPED_KEY] = outbound_media.NO_CAPABILITY
                    elif carries:
                        # 这次真把图带出去：上一次留下的「没带出去」不能接着算（重投的行会带着旧标记回来）
                        changes.pop(outbound_media.SKIPPED_KEY, None)
                    message_records.save(self.store, changes, expected=row['revision'], stream=row['episode_id'])
                    # Her @[label] becomes the adapter's @qq:<account> here, at the edge (people.py).
                    scene = scene_records.get(self.store, row['scene_id'])
                    text = People(self.store).outbound(scene, row['text']) if scene else row['text']
                    item = {'publication_id': row['_id'], 'attempt_id': attempt,
                            'target': row['target'], 'text': text,
                            # ADR-079 §9.6: the line her words answer (a reply token for a platform that needs one)
                            # and, apart, the line she chose to quote (shown only by an adapter that declares quote).
                            'reply_to': row.get('platform_answers'), 'quote': row.get('platform_reply_to')}
                    if carries:
                        item[outbound_media.ATTACHMENT_KEY] = declared      # 只有元数据，不带 base64；字节走下面的 GET
                    if sticker:
                        # her row keeps the [表情包:名字] she wrote; the platform gets the sticker alone
                        item['text'] = ''
                        item['sticker'] = {k: v for k, v in sticker.items() if k != 'name'}
                    if act:
                        # her row keeps the program's words for her history; the platform gets the action alone
                        item['text'] = ''
                        item['action'] = dict(act)
                    if sent_file:
                        # her row keeps 「[文件：名字，大小]」; the platform gets the file alone, its bytes in pieces
                        item['text'] = ''
                        item[outbound_files.KIND] = outbound_files.descriptor(sent_file)
                    return {'items': [item], 'lane': lane}
            if time.monotonic() >= deadline:
                break
            self.controller.stopping.wait(min(.2, max(0, deadline - time.monotonic())))
        while expired:
            outbound_files.expired_source(self.store, expired.pop())
        return {'items': [], 'lane': lane}

    def attachment(self, channel_id, publication_id, query=None):
        """字节端点：GET /v1/channels/<id>/outbox/<pub>/attachment?attempt_id=…&artifact_id=…

        同一个 Bearer token（HTTP 层已经验过）。只允许这条 publication 自己声明的那份 artifact；
        attempt_id 必须属于这条且它正在 SENDING；字节从 BlobStore 读，按行内 sha 复核
        （围栏都在 outbound_media.serve）。行上记着 ``attachment_skipped``（那次领取没声明能收图）
        也算「没声明」：元数据还留在行上只为历史，字节一律 403 ATTACHMENT_NOT_DECLARED。
        返回 ``(data, media_type)``。

        A file row (ADR-092) is served in pieces: ``offset`` and ``length`` (at most outbound_files.PIECE_MAX) name
        the piece, under the same publication, attempt and artifact fences (outbound_files.serve_piece).
        """
        from . import outbound_files
        query = query or {}
        attempt_id = (query.get('attempt_id') or [''])[0]
        wanted = (query.get('artifact_id') or [''])[0]
        with database_effects_lock(self.store.name):
            row = message_records.get(self.store, publication_id)
            if not row or row.get('channel_id') != channel_id:
                raise Denied('PUBLICATION_NOT_FOUND')
            if row.get('delivery_state') != 'SENDING' or not row.get('attempt_id') \
                    or row['attempt_id'] != attempt_id:
                raise Denied('PUBLICATION_ATTEMPT_MISMATCH')
            if not isinstance(row.get(outbound_files.KIND), dict):
                declared = outbound_media.declared(row)      # 元数据在 ≠ 声明了：skipped 的行一律拒
                if not declared:
                    raise Denied('ATTACHMENT_NOT_DECLARED')
                if wanted and wanted != declared['artifact_id']:
                    raise Denied('ATTACHMENT_ARTIFACT_DENIED')       # 只发这条自己声明的那张，别人给不了
                from .blobs import BlobStore
                return outbound_media.serve(self.store, BlobStore(self.store), row, declared)
        # A file's piece is read outside the effects lock: every claim and receipt would wait behind a GridFS read.
        return outbound_files.serve_piece(self.store, row, query)

    def receipt(self, channel_id, publication_id, body):
        if set(body) - {'attempt_id', 'status', 'platform_message_id', 'response'}:
            raise Denied('RECEIPT_FIELD_DENIED')
        status = body.get('status')
        if status not in ('platform_accepted', 'failed', 'unknown') or not isinstance(body.get('response'), dict):
            raise ValueError('INVALID_PLATFORM_RECEIPT')
        if publication_id.startswith('ga-'):
            # 管理动作没有自己那条消息：平台的 retcode 就是全部答复，适配器也就不带 platform_message_id
            # （qqadapter/outbound.py 的 receipt_payload 只在有值时才带这个键）。这条分流必须走在下面那道
            # 消息类发布的要求之前：否则平台真办了动作，回执却被 400 拒掉，artifact 永远停在 SENDING，
            # group_admin.receipt 那条审计也一次都没落过。
            from . import group_admin
            with database_effects_lock(self.store.name):
                return group_admin.receipt(self.store, channel_id, publication_id, body)
        with database_effects_lock(self.store.name):
            row = message_records.get(self.store, publication_id)
            # A poke or a reaction makes no message of its own: its receipt carries none (ADR-064 phase 2); nor does a
            # file, whose platform id is not one of ours (ADR-092 D6).
            if (status == 'platform_accepted' and not (row or {}).get('action') and not (row or {}).get('file')
                    and (not isinstance(body.get('platform_message_id'), str) or not body['platform_message_id'].strip())):
                raise ValueError('PLATFORM_MESSAGE_ID_REQUIRED')
            # An already claimed send may have happened before revocation. Preserve
            # the factual receipt without authorizing a new send or target change.
            if not row or row.get('channel_id') != channel_id:
                raise Denied('PUBLICATION_NOT_FOUND')
            if not row.get('attempt_id') or body.get('attempt_id') != row['attempt_id']:
                raise Denied('PUBLICATION_ATTEMPT_MISMATCH')
            if row.get('platform_receipt') == body:
                return {'status': row['delivery_state']}
            if row['delivery_state'] not in ('SENDING', 'UNKNOWN'):
                raise Denied('PUBLICATION_RECEIPT_CONFLICT')
            state = {'platform_accepted': 'DELIVERED', 'failed': 'FAILED', 'unknown': 'UNKNOWN'}[status]
            if (state == 'FAILED' and (row.get('action') or {}).get('kind') == 'react'
                    and (row.get('target') or {}).get('type') == 'dm'):
                from . import role_tools
                role_tools.REACT_OFF_IN_DMS.add(channel_id)     # her call: tried again after the next restart
            message_records.save(self.store, {**row, 'delivery_state': state, 'platform_receipt': body,
                                 'platform_message_id': body.get('platform_message_id'), 'receipt_at': now(),
                                 'delivery_basis': 'platform_ack' if state == 'DELIVERED' else status},
                                 expected=row['revision'], stream=row['episode_id'])
            act = row.get('action') or {}
            if state == 'DELIVERED' and act.get('kind') == 'recall' and act.get('line'):
                # Her own line taken back: the line itself now says so wherever the program shows it again.
                message_records.mark_recalled(self.store, act['line'], now())
            if state == 'DELIVERED' and row.get('file'):
                from . import outbound_files
                outbound_files.sent(self.store, row)            # its bytes are kept KEEP_DAYS from now (D9)
            if state != 'DELIVERED':
                from .publish import PublishService
                PublishService(self.store).cancel_after({**row, 'delivery_state': state})
            from . import own_mute
            own_mute.after_receipt(self.store, row, state, body)     # refused for a mute, or accepted: her mute there
            return {'status': state}

    def recover_sending(self):
        # A lost HTTP response may hide an actual send. Never reclaim automatically.
        from .publish import PublishService
        from . import group_admin
        group_admin.recover_sending(self.store)
        for row in message_records.sending(self.store).rows():
            unknown = message_records.save(self.store, {**row, 'delivery_state': 'UNKNOWN',
                                           'recovery_reason': 'adapter_attempt_interrupted'},
                                           expected=row['revision'], stream=row['episode_id'])
            PublishService(self.store).cancel_after(unknown)


WHOLE_HOST_STATES = ('HOST_RECONFIGURING', 'HOST_STOPPING')


def whole_host_state(exc):
    """The name of a state of the whole Host an exception reports (applying settings, stopping, its database out of
    reach), or None when it is this request's own failure."""
    if isinstance(exc, RuntimeError) and str(exc) in WHOLE_HOST_STATES:
        return str(exc)
    from .store.errors import Unavailable           # the adapter's word for a database out of reach
    if isinstance(exc, Unavailable):
        return 'HOST_DATABASE_UNAVAILABLE'
    return None


# ADR-095: a chat line out longer than this no longer holds its conversation (an adapter that died mid-send); it
# stays SENDING until its receipt or the Host's start (recover_sending) says what became of it.
CHAT_LEASE_SECONDS = 300
MEMBERS_BODY_LIMIT = 4 * 1024 * 1024
JSON_BODY_LIMIT = 262144


class ChannelServer:
    def __init__(self, channels, port=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def drop_body(self):
                """A body refused before it was read is read and dropped before the answer, so the client gets the
                answer, not a reset connection; one larger than any endpoint takes (a voice's) closes the connection
                instead."""
                from .voice import BODY_LIMIT
                try:
                    left = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    left = -1
                if not 0 <= left <= BODY_LIMIT:
                    self.close_connection = True
                    return
                while left > 0:
                    chunk = self.rfile.read(min(left, 65536))
                    if not chunk:
                        break
                    left -= len(chunk)

            def handle_request(self):
                status = 200
                self.body_read = False
                raw = None                      # (bytes, content_type)：只有附件端点走这一条
                try:
                    url = urlsplit(self.path)
                    parts = [unquote(part) for part in url.path.strip('/').split('/')]
                    if len(parts) < 4 or parts[:2] != ['v1', 'channels']:
                        raise ValueError('UNKNOWN_CHANNEL_ENDPOINT')
                    channel_id = parts[2]
                    _, scoped = channels.authenticate(channel_id, self.headers.get('Authorization', ''))
                    body, audio, voice_fields = {}, None, None
                    if self.command == 'POST':
                        size = int(self.headers.get('Content-Length', '0'))
                        media_type = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
                        # A voice's bytes come raw (voice.py); every other body is one JSON object. A group's member
                        # list (group_members.py) is the one JSON body that may be large.
                        raw_voice = parts[3:] == ['voice']
                        from . import voice
                        if raw_voice:
                            # Who may post it and what it is about are settled before a byte of audio is read.
                            if scoped:
                                channels.scope_check(channel_id, scoped, self.command, parts[3:], body)
                            voice_fields = voice.fields({key: values[0] for key, values in parse_qs(url.query).items()})
                        limit = (voice.BODY_LIMIT if raw_voice else MEMBERS_BODY_LIMIT if parts[3:] == ['members']
                                 else JSON_BODY_LIMIT)
                        if not 0 < size <= limit:
                            raise ValueError('INVALID_BODY_SIZE')
                        if raw_voice:
                            audio = self.rfile.read(size)
                            self.body_read = True
                            if len(audio) != size:
                                raise ValueError('INVALID_BODY_SIZE')
                        else:
                            data = self.rfile.read(size)
                            self.body_read = True
                            body = json.loads(data)
                            if not isinstance(body, dict):
                                raise ValueError('INVALID_BODY')
                    if scoped:
                        channels.scope_check(channel_id, scoped, self.command, parts[3:], body)
                    if self.command == 'POST' and parts[3:] == ['events']:
                        value = channels.receive(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['members']:
                        value = channels.members(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['media_keys']:
                        value = channels.media_keys(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['faults']:
                        value = channels.faults(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['notices']:
                        value = channels.notices(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['own_mute']:
                        value = channels.own_mute(channel_id, body)
                    elif self.command == 'POST' and parts[3:] == ['voice']:
                        value = channels.voice(channel_id, voice_fields, audio, media_type)
                    elif self.command == 'GET' and parts[3:] == ['outbox']:
                        query = parse_qs(url.query)
                        owner = []
                        if scoped and channels.line_closed(channel_id, scoped):
                            value = {'items': [], 'line': 'closed'}    # her words wait while she keeps it closed
                        else:
                            owner = channels.owner_lines(channel_id, scoped) if scoped else []
                            # no lane named: an adapter from before ADR-095, one lane for everything
                            lane = query.get('lane', ['one'])[0]
                            if lane not in ('chat', 'bulk', 'one'):
                                raise ValueError('OUTBOX_LANE_INVALID: lane 是 chat 或 bulk')
                            value = channels.claim(channel_id, 0 if owner else int(query.get('wait_seconds', ['0'])[0]),
                                                   supports=outbound_media.parse_supports(query),
                                                   target=channels.route_target(channel_id, scoped) if scoped else None,
                                                   lane=lane)
                        if owner:
                            value = {**value, 'owner_lines': owner}
                    elif self.command == 'GET' and len(parts) == 6 and parts[3] == 'outbox' and parts[5] == 'attachment':
                        payload = channels.attachment(channel_id, parts[4], parse_qs(url.query))
                        raw = payload if isinstance(payload, tuple) else None
                        value = {} if raw is not None else payload
                    elif self.command == 'POST' and len(parts) == 6 and parts[3] == 'outbox' and parts[5] == 'receipt':
                        value = channels.receipt(channel_id, parts[4], body)
                    else:
                        status, value = 404, {'error': 'UNKNOWN_CHANNEL_ENDPOINT'}
                except PermissionError as exc:
                    status, value = 403, {'error': str(exc)}
                except (ValueError, TypeError) as exc:
                    status, value = 400, {'error': str(exc)}
                except Exception as exc:
                    whole = whole_host_state(exc)
                    if whole:
                        # The whole Host, not this request: a client waits and asks again; it is no fault of the
                        # request (RUNTIME_API, ADR-095 §5.4).
                        status, value = 503, {'error': whole}
                    else:
                        # Database addresses/credentials never cross the adapter boundary.
                        error = redact_text(traceback.format_exc(), channels.store.config)
                        channels.controller.app.evidence.record('host.channel_error', {'traceback': error})
                        channels.controller.emit('[系统] 通道接口未完成：\n' + error)
                        status, value = 500, {'error': 'HOST_REQUEST_FAILED'}
                if self.command == 'POST' and not self.body_read:
                    self.drop_body()
                if raw is not None and status == 200:
                    data, media_type = raw
                    self.send_response(200)
                    self.send_header('Content-Type', media_type)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = handle_request
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
