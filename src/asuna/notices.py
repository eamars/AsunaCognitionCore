"""Platform notices as one-off lines (ADR-064 phase 1): the adapter projects a notice into words, the host passes
them on as the program's line, never as the words of the person who did it.

A notice arrives as an event from the person who did it with `raw.asuna_notice` (`kind`, optional `gate`, optional
`line`), through the same gates as a message (channels.py). Then:
- `line` names the line it is about by its platform id, in the one form every pointer has (ADR-079 §9.3): its
  number where the conversation shows numbers, its speaker (hers as 你) and its first words, found
  read-only within this conversation and the last day; a line the program has no record of is `一条消息`;
- in a group, `gate` (`poked`, `reacted`) puts it through the relevance gate, like a line that calls her without an @;
  it is then stored as that look's input, like every turn's. A reaction asks for a look only when it is on her line;
  one between other people is kept like a notice without a gate;
- in a group without a gate it is kept in `artifacts` (kind `held_notice`), not as a line of the conversation: shown
  once, after the stored lines, in that conversation's next turn or relevance-gate material (`take`), lines of one
  kind with the same words folded into one, reactions between other people folded into one line, at most HELD_MAX
  after folding, the rest counted; shown, it is deleted, and a Host restart keeps what was not shown yet;
- in a private chat it is that chat's input, as a message would be.

Notices about her own account or asking her to act (requests, a kick, an admin change) come by another endpoint
(`home`): held for HOME_BATCH_SECONDS, then one program event in her home session lists them. A request is kept in
`artifacts` (kind `platform_request`, one row per platform flag) with a number that stays the same across restarts,
open until she answers it or the platform refuses the answer (it is gone there); after a restart the open ones are
listed in her home again (`remind_open`). She answers one with `group_action` `accept` or `decline` and `who` the
number (`answer`). Accepting a request does not admit anyone: who may talk to her stays the channel's admission
setting.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from .state import Denied, now

KEY = 'asuna_notice'
GATES = ('poked', 'reacted')
QUOTE_DAYS = 1
HELD_MAX = 10
HELD_KEPT = 50                               # held per conversation before the oldest go uncounted
HOME_BATCH_SECONDS = 60
REQUEST_KIND = 'platform_request'
MARK = '（平台通知）'                         # after the label line of a notice: the program's line, not typed text
HISTORY_WORD = '平台通知，不是这个人打的字'
HELD_NOTE = '平台转来的通知（谁撤回了消息之类），这里只给一次；每条是程序的话，不是谁打的字。'
HOME_HEAD = '这是平台转来的通知，不是有人跟你说话'
ANSWER_HINT = '（%s：用 group_action 回，kind 写 accept 或 decline，who 写 %s）'
OPEN_HEAD = '重启以后还开着、等你回的请求'
# What became of her answer (group_admin.receipt): the platform took it, or refused it (the request is gone there).
ANSWERED = {'DONE': 'answered', 'FAILED': 'gone', 'UNKNOWN': 'unknown'}

_lock = threading.Lock()
_peeked = {}                                 # scene_id -> the held notices the relevance gate showed
_home = {'items': [], 'timer': None}


def kept(raw):
    """The notice block the host keeps from an adapter's raw event, or None."""
    block = (raw or {}).get(KEY) if isinstance(raw, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get('kind'), str) or not 1 <= len(block['kind']) <= 40:
        return None
    out = {'kind': block['kind']}
    if block.get('gate') in GATES:
        out['gate'] = block['gate']
    line = block.get('line')
    if isinstance(line, dict) and isinstance(line.get('message_id'), str) and 1 <= len(line['message_id']) <= 40:
        out['line'] = {'message_id': line['message_id'], 'mine': line.get('mine') is True}
    return out


def fill(store, scene, block, text, moment=None):
    """(the notice's words with {line} filled for any reader, whether the line is hers, the line's row id or None).
    The words she reads name the line when she reads them (`words`), in the form every pointer has."""
    line = block.get('line')
    if not line:
        return text.replace('{line}', '一条消息'), False, None
    moment = moment or datetime.now(timezone.utc)
    since = (moment - timedelta(days=QUOTE_DAYS)).isoformat()
    fields = {'_id': 1, 'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1}
    # Her own line is found however old (its id is her receipt's); anyone's within the last QUOTE_DAYS.
    row = (store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'outbound',
                                       'platform_message_id': line['message_id']}, fields, sort=[('scene_seq', -1)])
           if line.get('mine') else None) or store.db.messages.find_one({'scene_id': scene['_id'], '$or': [
        {'direction': 'inbound', 'event.channel.platform_event_id': line['message_id'], 'received_at': {'$gte': since}},
        {'direction': 'outbound', 'platform_message_id': line['message_id'], 'receipt_at': {'$gte': since}}]},
        fields, sort=[('scene_seq', -1)])
    if not row:
        return text.replace('{line}', '一条消息', 1), False, None
    return _named(store, scene, text, row), row.get('direction') == 'outbound', row['_id']


def _named(store, scene, text, row):
    from .people import People
    return text.replace('{line}', ' %s ' % People(store).pointed(scene, row), 1).rstrip()


def line_row(store, block):
    """The row of the line a notice is about, when it was found (its direction tells whether it is hers)."""
    row_id = ((block or {}).get('line') or {}).get('row')
    return store.db.messages.find_one({'_id': row_id}, {'direction': 1}) if row_id else None


def words(store, scene, text, block):
    """A notice's words as she reads them: the line it is about named now (ADR-079 §9.3), from the notice's own
    template, since a label written into the stored text would read as typed."""
    template = (block or {}).get('words')
    row_id = ((block or {}).get('line') or {}).get('row')
    if not template or not row_id:
        return text
    row = store.db.messages.find_one({'_id': row_id}, {'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1})
    return _named(store, scene, template, row) if row else text


# ---- seen once, in a group ------------------------------------------------------------------------------------------
HELD_KIND = 'held_notice'
REACTIONS_HEAD = '这期间的点表情：'
REACTIONS_MAX = 5                            # lines reacted to, in that one line; older ones counted


def hold(store, scene_id, row):
    """Kept until her next turn there shows it (ADR-079: a restart loses none); the oldest beyond HELD_KEPT go."""
    store.db.artifacts.insert_one({'_id': 'notice-' + uuid.uuid4().hex, 'kind': HELD_KIND, 'scene_id': scene_id,
                                   'received_at': row.get('received_at') or now(), 'row': row, 'schema_version': 1})
    extra = list(store.db.artifacts.find({'kind': HELD_KIND, 'scene_id': scene_id}, {'_id': 1})
                 .sort('received_at', -1).skip(HELD_KEPT))
    if extra:
        store.db.artifacts.delete_many({'_id': {'$in': [doc['_id'] for doc in extra]}})


def take(store, scene, persona=None, keep=False):
    """The notices held for this conversation, as she reads them, once: {'items': [...], 'more': ...} or None.
    `keep` (the relevance gate) leaves them for her turn if she takes it up; `drop_seen` ends them if she does not."""
    held = list(store.db.artifacts.find({'kind': HELD_KIND, 'scene_id': scene['_id']}).sort('received_at', 1))
    if keep:
        with _lock:
            _peeked[scene['_id']] = [doc['_id'] for doc in held]
    else:
        with _lock:
            _peeked.pop(scene['_id'], None)
        if held:
            store.db.artifacts.delete_many({'_id': {'$in': [doc['_id'] for doc in held]}})
    rows = [doc['row'] for doc in held]
    if not rows:
        return None
    from .caught_up import said_at
    from .people import People
    from .schedule_rules import line_stamp, scene_timezone
    people = People(store, persona)
    zone = scene_timezone(store.config, scene)
    folded, reactions = {}, {}
    for row in rows:
        _place(people, scene, row)
        block = row['event']['raw'][KEY]
        body = words(store, scene, people.heard(scene, row['text'], (row['event'].get('channel') or {}).get('account_id')),
                     block)
        kind = block['kind']
        then = people.thought_then(line_row(store, block), scene['_id'])
        if then:
            body += then                     # a notice about her line: the same anchor a quote of it has
        item = (reactions if kind in ('reaction', 'reaction_removed') else folded).setdefault((kind, body), {'who': [], 'at': ''})
        who = people.speaker(scene, row['author'], row)
        if who not in item['who']:
            item['who'].append(who)
        item['at'] = line_stamp(zone, said_at(row)) or item['at']
    items = ['%s %s%s%s' % ('、'.join(item['who']), item['at'], MARK, body) for (_, body), item in folded.items()]
    if reactions:
        shown = ['%s %s' % ('、'.join(item['who']), body) for (_, body), item in reactions.items()]
        rest = len(shown) - REACTIONS_MAX
        items.append(REACTIONS_HEAD + '；'.join(shown[-REACTIONS_MAX:]) + ('；另有 %d 条较早的' % rest if rest > 0 else '')
                     + MARK)
    out = {'items': items[-HELD_MAX:]}
    if len(items) > HELD_MAX:
        out['more'] = '还有 %d 条较早的通知没列出' % (len(items) - HELD_MAX)
    return out


def drop_seen(store, scene_id):
    """The gate showed them and she let the line pass: they were seen once."""
    with _lock:
        ids = _peeked.pop(scene_id, [])
    if ids:
        store.db.artifacts.delete_many({'_id': {'$in': ids}, 'kind': HELD_KIND})


def _place(people, scene, row):
    """The people a notice names get their labels here, as a message's @ do."""
    account = (row['event'].get('channel') or {}).get('account_id')
    for number in (row['event'].get('group_context') or {}).get('mentioned_account_ids') or []:
        if str(number) != str(account):
            profile = people.mentioned(row, number)
            people.entry(scene, people.account_person(scene['_id'], number), row if profile else None, profile)


def forget():
    with _lock:
        _peeked.clear()
        _home['items'].clear()
        if _home['timer']:
            _home['timer'].cancel()
        _home['timer'] = None


# ---- her home session ---------------------------------------------------------------------------------------------
HOME_FIELDS = {'kind', 'words', 'actor_name', 'group_id', 'group_name', 'request', 'at'}


def home(store, controller, channel_id, body, delay=HOME_BATCH_SECONDS):
    """POST /v1/channels/<id>/notices: a line about her own account; held a minute, then one home event."""
    from .people import People, safe_name, typed
    if set(body) - HOME_FIELDS:
        raise PermissionError('NOTICE_FIELD_DENIED: 只收 %s' % '、'.join(sorted(HOME_FIELDS)))
    words, kind = body.get('words'), body.get('kind')
    if not isinstance(words, str) or not 1 <= len(words) <= 200 or not isinstance(kind, str) or not 1 <= len(kind) <= 40:
        raise ValueError('NOTICE_INVALID: kind 和 words 要是不长的文字')
    people = People(store)
    group = str(body.get('group_id') or '')
    if '{g}' in words:
        from .group_members import routed_group
        try:
            scene = store.db.scenes.find_one({'_id': routed_group(store, channel_id, group, 'NOTICE')['scene_id']})
        except PermissionError:
            scene = None
        title = people.scene_title(scene) if scene else ''
        name = title[3:-1] if title.startswith('群聊「') else safe_name(body.get('group_name'), 30)
        words = words.replace('{g}', '「%s」' % name if name else '')
    actor = safe_name(body.get('actor_name'), 30)
    line = typed(('「%s」' % actor if actor else '') + words)
    request = body.get('request')
    if request is not None:
        if not (isinstance(request, dict) and isinstance(request.get('flag'), str) and 1 <= len(request['flag']) <= 200
                and request.get('type') in ('friend', 'group')
                and (request['type'] == 'friend' or request.get('sub_type') in ('add', 'invite'))):
            raise ValueError('NOTICE_INVALID: request 要有 flag、type（friend 或 group）和群请求的 sub_type')
    at = body.get('at')
    moment = datetime.fromtimestamp(at, timezone.utc) if type(at) is int and at > 0 else datetime.now(timezone.utc)
    if request is not None:
        line += _hint(_keep_request(store, channel_id, request, line, moment))
    with _lock:
        _home['items'].append((moment, line))
        if _home['timer'] is None:
            timer = threading.Timer(delay, _send_home, args=(store, controller))
            timer.daemon = True
            _home['timer'] = timer
            timer.start()
    return {'status': 'held'}


def _send_home(store, controller):
    from .schedule_rules import line_stamp
    from . import local_time
    with _lock:
        items, _home['items'], _home['timer'] = list(_home['items']), [], None
    if not items:
        return None
    chat = store.config.get('chat') or {}
    zone = local_time.zone_of(store, chat.get('scene_id'))
    text = HOME_HEAD + '：\n' + '\n'.join('- %s %s' % (line_stamp(zone, moment.isoformat()), line)
                                          for moment, line in items)
    event_id = 'presence:notice-' + uuid.uuid4().hex[:16]
    controller.offer_internal('presence', event_id, chat['scene_id'], chat['person_id'], text)
    store.audit('notices', 'notice.home', {'event_id': event_id, 'lines': len(items)}, 'operator')
    return event_id


def _number(row):
    return '请求%d' % row['number']


def _hint(row):
    return ANSWER_HINT % (_number(row), _number(row))


def _keep_request(store, channel_id, request, line, moment):
    """The request's row: one per platform flag, numbered once (the next number after the highest ever given)."""
    from .evidence import sha
    from .state import Conflict
    row_id = 'request-' + sha(('%s|%s' % (channel_id, request['flag'])).encode())[:24]
    for _ in range(5):
        row = store.db.artifacts.find_one({'_id': row_id})
        if row:
            return row
        last = store.db.artifacts.find_one({'kind': REQUEST_KIND}, {'number': 1}, sort=[('number', -1)])
        try:
            return store.put('artifacts', {'_id': row_id, 'kind': REQUEST_KIND, 'channel_id': channel_id,
                                           'number': (last or {}).get('number', 0) + 1, 'flag': request['flag'],
                                           'type': request['type'],
                                           **({'sub_type': request['sub_type']} if request['type'] == 'group' else {}),
                                           'line': line, 'received_at': moment.isoformat(), 'state': 'open',
                                           'created_at': now()}, stream='requests')
        except Conflict:
            continue
    raise Conflict('REQUEST_BUSY')


def pending(store):
    """The requests she may answer now, by number."""
    rows = store.db.artifacts.find({'kind': REQUEST_KIND, 'state': 'open'}).sort('number', 1)
    return {_number(row): row for row in rows}


def remind_open(store, controller):
    """After a start: the requests still waiting on her, listed once in her home; None when there are none."""
    from .schedule_rules import line_stamp
    from . import local_time
    rows = list(pending(store).values())
    if not rows:
        return None
    chat = store.config.get('chat') or {}
    zone = local_time.zone_of(store, chat.get('scene_id'))
    text = HOME_HEAD + '。' + OPEN_HEAD + '：\n' + '\n'.join(
        '- %s %s%s' % (line_stamp(zone, row['received_at']), row['line'], _hint(row)) for row in rows)
    event_id = 'presence:requests-' + uuid.uuid4().hex[:16]
    controller.offer_internal('presence', event_id, chat['scene_id'], chat['person_id'], text)
    store.audit('notices', 'notice.requests_open', {'event_id': event_id, 'open': len(rows)}, 'operator')
    return event_id


def settled(store, action, state):
    """Her answer's receipt: the request is answered, gone from the platform, or its fate unknown."""
    row = store.db.artifacts.find_one({'kind': REQUEST_KIND, 'answer': action['_id']})
    if row and state in ANSWERED:
        store.put('artifacts', {**row, 'state': ANSWERED[state], 'settled_at': now()}, expected=row['revision'],
                  stream='requests')


def answer(store, ep, item, key):
    """group_action accept/decline at home: queue the answer to one listed request for the adapter."""
    from .evidence import canonical, sha
    found = pending(store)
    who = ''.join(str(item.get('who') or '').split())
    number = who if who.startswith('请求') else '请求' + who.lstrip('#')
    request = found.get(number)
    if not request:
        raise Denied('GROUP_ACTION_REQUEST_NOT_FOUND: 「%s」不是等你回的请求；%s' % (
            item.get('who'), '现在等你回的是 ' + '、'.join(sorted(found)) if found else '现在没有等你回的请求，重试也一样'))
    scene = store.db.scenes.find_one({'_id': ep['scene_id']}) or {}
    row_id = 'ga-' + sha(canonical([ep['_id'], 'group_action', key]))[:24]
    if not store.db.artifacts.find_one({'_id': row_id}):
        store.put('artifacts', {'_id': row_id, 'kind': 'group_action', 'channel_id': request['channel_id'],
                                'scene_id': ep['scene_id'], 'scope_key': scene.get('scope_key'),
                                'policy_epoch': scene.get('policy_epoch'), 'episode_id': ep['_id'],
                                'target': {'type': 'request', 'id': request['type']},
                                'admin': {'kind': item['kind'], 'flag': request['flag'], 'request': request['type'],
                                          **({'sub_type': request['sub_type']} if 'sub_type' in request else {})},
                                'who': number, 'reason': item.get('reason', ''), 'state': 'QUEUED', 'created_at': now()},
                  stream=row_id)
    store.put('artifacts', {**request, 'state': 'answering', 'answer': row_id, 'answered_at': now()},
              expected=request['revision'], stream='requests')
    from .group_admin import KIND_WORDS, STATE_WORDS
    return {'action': KIND_WORDS[item['kind']], 'who': number, 'state': STATE_WORDS['QUEUED']}
