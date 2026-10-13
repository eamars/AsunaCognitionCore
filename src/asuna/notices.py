"""Platform notices as one-off lines (ADR-064 phase 1): the adapter projects a notice into words, the host passes
them on as the program's line, never as the words of the person who did it.

A notice arrives as an event from the person who did it with `raw.asuna_notice` (`kind`, optional `gate`, optional
`line`), through the same gates as a message (channels.py). Then:
- `line` names the line it is about by its platform id: a recalled line is quoted (at most QUOTE_CHARS, found
  read-only within this conversation and the last day); a line of hers is named by when she said it, and a notice
  about a line that is not hers is dropped;
- in a group, `gate` (`poked`, `reacted`) puts it through the relevance gate, like a line that calls her without an @;
  it is then stored as that look's input, like every turn's;
- in a group without a gate it is held in memory, never stored: shown once, after the stored lines, in that
  conversation's next turn or relevance-gate material (`take`), lines of one kind with the same words folded into
  one, at most HELD_MAX after folding, the rest counted; a Host restart loses what was not shown yet;
- in a private chat it is that chat's input, as a message would be.

Notices about her own account or asking her to act (requests, a kick, an admin change) come by another endpoint
(`home`): held for HOME_BATCH_SECONDS, then one program event in her home session lists them. A request there has a
number; she answers it with `group_action` `accept` or `decline` and `who` the number (`answer`). Accepting a request
does not admit anyone: who may talk to her stays the channel's admission setting.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from .state import Denied, now

KEY = 'asuna_notice'
GATES = ('poked', 'reacted')
QUOTE_CHARS = 40
QUOTE_DAYS = 1
HELD_MAX = 10
HELD_KEPT = 50                               # held per conversation before the oldest go uncounted
HOME_BATCH_SECONDS = 60
REQUESTS_KEPT = 20
REQUEST_HOURS = 24
MARK = '（平台通知）'                         # after the label line of a notice: the program's line, not typed text
HISTORY_WORD = '平台通知，不是这个人打的字'
HELD_NOTE = '平台转来的通知（谁撤回了消息之类），这里只给一次；每条是程序的话，不是谁打的字。'
HOME_HEAD = '这是平台转来的通知，不是用户消息'
ANSWER_HINT = '（%s：用 group_action 回，kind 写 accept 或 decline，who 写 %s）'

_lock = threading.Lock()
_held = {}                                   # scene_id -> [row]
_peeked = {}                                 # scene_id -> how many of them the relevance gate showed
_home = {'items': [], 'timer': None}
_requests = {}                               # '请求N' -> request
_counter = {'n': 0}


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
    """The notice's words with its {line} filled; None when it is about a line of hers that is not hers."""
    line = block.get('line')
    if not line:
        return text.replace('{line}', '一条消息')
    from .schedule_rules import line_stamp, scene_timezone
    moment = moment or datetime.now(timezone.utc)
    if line['mine']:
        row = store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'outbound',
                                          'platform_message_id': line['message_id']}, {'receipt_at': 1})
        if not row:
            return None
        return text.replace('{line}', '你 %s 说的那句' % line_stamp(scene_timezone(store.config, scene),
                                                                 row.get('receipt_at')), 1)
    since = (moment - timedelta(days=QUOTE_DAYS)).isoformat()
    row = store.db.messages.find_one({'scene_id': scene['_id'], '$or': [
        {'direction': 'inbound', 'event.channel.platform_event_id': line['message_id'], 'received_at': {'$gte': since}},
        {'direction': 'outbound', 'platform_message_id': line['message_id'], 'receipt_at': {'$gte': since}}]},
        {'text': 1}, sort=[('scene_seq', -1)])
    said = ' '.join(str((row or {}).get('text') or '').split())
    quote = said[:QUOTE_CHARS] + ('…' if len(said) > QUOTE_CHARS else '')
    return text.replace('{line}', '消息「%s」' % quote if said else '一条消息', 1)


# ---- seen once, in a group ------------------------------------------------------------------------------------------
def hold(scene_id, row):
    with _lock:
        rows = _held.setdefault(scene_id, [])
        rows.append(row)
        del rows[:-HELD_KEPT]


def take(store, scene, persona=None, keep=False):
    """The notices held for this conversation, as she reads them, once: {'items': [...], 'more': ...} or None.
    `keep` (the relevance gate) leaves them for her turn if she takes it up; `drop_seen` ends them if she does not."""
    with _lock:
        rows = list(_held.get(scene['_id'], []))
        if keep:
            _peeked[scene['_id']] = len(rows)
        else:
            _held.pop(scene['_id'], None)
            _peeked.pop(scene['_id'], None)
    if not rows:
        return None
    from .caught_up import said_at
    from .people import People
    from .schedule_rules import line_stamp, scene_timezone
    people = People(store, persona)
    zone = scene_timezone(store.config, scene)
    folded = {}
    for row in rows:
        _place(people, scene, row)
        body = people.heard(scene, row['text'], (row['event'].get('channel') or {}).get('account_id'))
        key = (row['event']['raw'][KEY]['kind'], body)
        item = folded.setdefault(key, {'who': [], 'at': ''})
        who = people.speaker(scene, row['author'], row)
        if who not in item['who']:
            item['who'].append(who)
        item['at'] = line_stamp(zone, said_at(row)) or item['at']
    items = ['%s %s%s%s' % ('、'.join(item['who']), item['at'], MARK, body) for (_, body), item in folded.items()]
    out = {'items': items[-HELD_MAX:]}
    if len(items) > HELD_MAX:
        out['more'] = '还有 %d 条较早的通知没列出' % (len(items) - HELD_MAX)
    return out


def drop_seen(scene_id):
    """The gate showed them and she let the line pass: they were seen once."""
    with _lock:
        count = _peeked.pop(scene_id, 0)
        rows = _held.get(scene_id, [])
        del rows[:count]
        if not rows:
            _held.pop(scene_id, None)


def _place(people, scene, row):
    """The people a notice names get their labels here, as a message's @ do."""
    account = (row['event'].get('channel') or {}).get('account_id')
    for number in (row['event'].get('group_context') or {}).get('mentioned_account_ids') or []:
        if str(number) != str(account):
            profile = people.mentioned(row, number)
            people.entry(scene, people.account_person(scene['_id'], number), row if profile else None, profile)


def forget():
    with _lock:
        _held.clear()
        _peeked.clear()
        _home['items'].clear()
        if _home['timer']:
            _home['timer'].cancel()
        _home['timer'] = None
        _requests.clear()
        _counter['n'] = 0


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
    with _lock:
        if request is not None:
            _counter['n'] += 1
            number = '请求%d' % _counter['n']
            _requests[number] = {'channel_id': channel_id, 'flag': request['flag'], 'type': request['type'],
                                 **({'sub_type': request['sub_type']} if request['type'] == 'group' else {}),
                                 'line': line, 'at': now()}
            for old in sorted(_requests, key=lambda n: _requests[n]['at'])[:-REQUESTS_KEPT]:
                del _requests[old]
            line += ANSWER_HINT % (number, number)
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


def pending():
    """The requests she may answer now, by number."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=REQUEST_HOURS)).isoformat()
    with _lock:
        for number in [n for n, r in _requests.items() if r['at'] < cutoff]:
            del _requests[number]
        return dict(_requests)


def answer(store, ep, item, key):
    """group_action accept/decline at home: queue the answer to one listed request for the adapter."""
    from .evidence import canonical, sha
    found = pending()
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
    with _lock:
        _requests.pop(number, None)
    from .group_admin import KIND_WORDS, STATE_WORDS
    return {'action': KIND_WORDS[item['kind']], 'who': number, 'state': STATE_WORDS['QUEUED']}
