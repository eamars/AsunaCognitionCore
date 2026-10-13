"""NapCat notices and requests as one-off lines (ADR-064 phase 1): every kind projected, the shown ones posted.

`project` turns one notice or request into a kind and one line of words from WORDS, a versioned table: a person in a
group line is written `@<account>` (Core shows it as that person's label, like a real @ in a message), her own
account as 你, and text a person controls (a group name, a request's note) in 「」 with label-shaped parts made plain
by Core. Which kinds she is shown is SHOWN, a switch table; every other kind is projected and counted, not posted.

Every kind is counted, with no content, in `health.json` (`notices`: today's counts by kind, and the last 14 days in
`<data>/notices/counts.json`, so restarts do not lose them). A notice of an unknown kind is counted under its
platform name and never shown. Not projected at all (counted only): typing, connection plumbing, her own messages
sent elsewhere, online-file transfers.

Where a shown line goes:
- in a group or a private chat, as an event from the person who did it (`POST /events`, `raw.asuna_notice`), under
  the same gates as a message (her own account, the allowlists, blocked people). `gate` asks Core to put it through
  the relevance gate (`poked`, `reacted`); `line` asks Core to name the line it is about (`message_id`: a recalled
  line, quoted; a line of hers, by when she said it), and Core drops a reaction that is not to a line of hers;
- about her own account or asking her to act (a friend or group request, a kick, an admin change): to her home
  session (`POST /notices`), with the request's `flag` so her answer can go back.
"""
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone

from . import faces

WORDS_VERSION = 1
# Her first batch (owner 2026-10-13): what asks her to act or tells her her own state. Flip a kind on to show it.
SHOWN = frozenset({'poke_you', 'reaction', 'recall', 'request_friend', 'request_join', 'request_invite',
                   'kicked_you', 'admin_you'})
# About her own account or asking her to act: her home session, not the conversation.
HOME_KINDS = frozenset({'request_friend', 'request_join', 'request_invite', 'kicked_you', 'admin_you', 'disband',
                        'offline', 'profile_like'})
GATES = {'poke_you': 'poked', 'reaction': 'reacted'}       # a group line that goes through the relevance gate
NOT_PROJECTED = {'input_status', 'online_file', 'message_sent', 'meta'}
DAYS_KEPT = 14
SAVE_EVERY = 60.0
NAME_CHARS = 30
NOTE_CHARS = 60

# The words of every kind, after the name of who did it (a home line without one starts with them). {a}, {t}: a
# person; {n}, {old}, {new}: text a person controls; {d}: a duration; {e}: an emoji. Core fills {line} (the line it is
# about) and {g} (a group's name, in a home line).
WORDS = {
    'recall': '撤回了{line}',
    'recall_other': '撤回了 {t} 的{line}',
    'recall_yours': '撤回了你的{line}',
    'poke_you': '戳了戳你',
    'poke': '戳了戳 {t}',
    'reaction': '给{line}点了{e}',
    'reaction_removed': '收回了给{line}点的{e}',
    'join': '进群了',
    'join_invited': '被 {a} 拉进了群',
    'leave': '退群了',
    'kick': '把 {t} 移出了群',
    'kicked_you': '把你移出了群{g}',
    'disband': '解散了群{g}',
    'mute': '禁言了 {t} {d}',
    'unmute': '解除了 {t} 的禁言',
    'mute_all': '开了全员禁言',
    'unmute_all': '关了全员禁言',
    'admin_you': '你被设成了群{g}的管理员',
    'unadmin_you': '你在群{g}的管理员被取消了',
    'admin': '把 {t} 设成了管理员',
    'unadmin': '取消了 {t} 的管理员',
    'card': '把群名片从「{old}」改成了「{new}」',
    'title': '得到了专属头衔「{n}」',
    'group_name': '把群名改成了「{n}」',
    'essence': '把{line}设成了精华',
    'essence_removed': '把{line}移出了精华',
    'upload': '上传了文件「{n}」',
    'profile_like': '给你的资料卡点了赞',
    'gray_tip': '发了一条平台灰字提示：「{n}」',
    'friend_add': '和你成了好友',
    'request_friend': '想加你好友{n}',
    'request_join': '想进群{g}{n}',
    'request_invite': '邀请你进群{g}',
    'offline': '你的账号被挤下线了',
}
# Words that differ from their kind's own (a kind with variants in WORDS).
VARIANT_OF = {'recall_other': 'recall', 'recall_yours': 'recall', 'join_invited': 'join', 'unadmin_you': 'admin_you',
              'unadmin': 'admin', 'unmute': 'mute', 'mute_all': 'mute', 'unmute_all': 'mute'}


def _id(value):
    text = str(value if value is not None else '').strip()
    return text if text.isascii() and text.isdigit() and text != '0' else ''


def _text(value, limit):
    """Text a person controls, on one line, bounded; braces made full-width so it cannot fill a slot."""
    text = ' '.join(str(value or '').split())[:limit]
    return text.replace('{', '｛').replace('}', '｝')


def duration_words(seconds):
    seconds = int(seconds or 0)
    if seconds >= 86400 and seconds % 86400 == 0:
        return '%d 天' % (seconds // 86400)
    if seconds >= 3600 and seconds % 3600 == 0:
        return '%d 小时' % (seconds // 3600)
    return '%d 分钟' % max(1, round(seconds / 60))


def emoji_words(emoji_id):
    """An emoji reaction by name: a QQ face's name, a Unicode emoji itself, else 一个表情."""
    key = str(emoji_id or '').strip()
    if key in faces.BY_ID:
        return '「%s」' % faces.BY_ID[key]
    if key.isdigit() and int(key) > 0x2000:
        try:
            return chr(int(key))
        except (ValueError, OverflowError):
            pass
    return '一个表情'


def _who(account, own):
    return '你' if account == own else '@' + account


def kind_of(event):
    """The kind this notice or request counts under, before any check: (kind, known)."""
    post = event.get('post_type')
    if post == 'meta_event':
        return 'meta', True
    if post == 'message_sent':
        return 'message_sent', True
    if post == 'request':
        kind = {'friend': 'request_friend'}.get(event.get('request_type')) or {
            'add': 'request_join', 'invite': 'request_invite'}.get(event.get('sub_type'))
        return (kind, True) if kind else ('request:%s' % event.get('request_type'), False)
    if post != 'notice':
        return 'post:%s' % post, False
    notice, sub = event.get('notice_type'), event.get('sub_type')
    if notice == 'notify':
        kind = {'poke': 'poke', 'title': 'title', 'group_name': 'group_name', 'profile_like': 'profile_like',
                'gray_tip': 'gray_tip', 'input_status': 'input_status'}.get(sub)
        return (kind, True) if kind else ('notify:%s' % sub, False)
    simple = {'group_recall': 'recall', 'friend_recall': 'recall', 'group_msg_emoji_like': 'reaction',
              'group_increase': 'join', 'group_ban': 'mute', 'group_card': 'card', 'essence': 'essence',
              'group_upload': 'upload', 'friend_add': 'friend_add', 'bot_offline': 'offline',
              'online_file_send': 'online_file', 'online_file_receive': 'online_file'}
    if notice in simple:
        return simple[notice], True
    if notice == 'group_decrease':
        return {'leave': 'leave', 'kick': 'kick', 'kick_me': 'kicked_you', 'disband': 'disband'}.get(sub, 'leave'), True
    if notice == 'group_admin':
        return 'admin', True
    return 'notice:%s' % notice, False


def project(event, own):
    """One notice as {kind, words, where, actor, group_id, people, ...}, or None when it is not projected (a kind
    without words, her own doing, or a shape that names nobody). `words` keeps its {line} slot for Core."""
    kind, known = kind_of(event)
    if not known or kind in NOT_PROJECTED:
        return None
    group = _id(event.get('group_id'))
    user, operator = _id(event.get('user_id')), _id(event.get('operator_id'))
    out = {'kind': kind, 'group_id': group, 'people': []}
    variant, slots = kind, {}

    def person(account):
        if account and account != own and account not in out['people']:
            out['people'].append(account)
        return _who(account, own)

    if kind == 'recall':
        actor = operator or user
        out['message_id'] = str(event.get('message_id') or '')
        if user == own:
            variant = 'recall_yours'
        elif operator and user and operator != user:
            variant, slots['t'] = 'recall_other', person(user)
    elif kind == 'poke':
        actor, target = user, _id(event.get('target_id'))
        if target == own:
            variant = kind = out['kind'] = 'poke_you'
        else:
            slots['t'] = person(target)
    elif kind == 'reaction':
        actor = user
        out['message_id'] = str(event.get('message_id') or '')
        likes = event.get('likes') if isinstance(event.get('likes'), list) else []
        first = likes[0] if likes and isinstance(likes[0], dict) else {}
        slots['e'] = emoji_words(first.get('emoji_id', event.get('emoji_id')))
        if event.get('is_add') is False:
            variant = kind = out['kind'] = 'reaction_removed'
    elif kind == 'join':
        actor = user
        if event.get('sub_type') == 'invite' and operator and operator != user:
            variant, slots['a'] = 'join_invited', person(operator)
    elif kind in ('leave', 'kick', 'kicked_you', 'disband'):
        actor = operator if kind != 'leave' else user
        if kind == 'kick':
            slots['t'] = person(user)
    elif kind == 'mute':
        actor = operator
        if not user:
            variant = 'mute_all' if event.get('sub_type') == 'ban' else 'unmute_all'
        elif user == own:
            return None                                   # her own mute is a state (mutes.py), not a line
        else:
            slots['t'] = person(user)
            if event.get('sub_type') == 'lift_ban':
                variant = 'unmute'
            else:
                slots['d'] = duration_words(event.get('duration'))
    elif kind == 'admin':
        actor = user if user != own else ''
        unset = event.get('sub_type') == 'unset'
        if user == own:
            kind = out['kind'] = 'admin_you'
            variant = 'unadmin_you' if unset else 'admin_you'
        else:
            variant = 'unadmin' if unset else 'admin'
            slots['t'] = person(user)
    elif kind == 'card':
        actor = user
        slots['old'], slots['new'] = _text(event.get('card_old'), NAME_CHARS), _text(event.get('card_new'), NAME_CHARS)
    elif kind in ('title', 'group_name'):
        actor = user
        slots['n'] = _text(event.get('title') if kind == 'title' else event.get('name_new'), NAME_CHARS)
    elif kind == 'essence':
        actor = operator or _id(event.get('sender_id'))
        out['message_id'] = str(event.get('message_id') or '')
        if event.get('sub_type') == 'delete':
            variant = 'essence_removed'
    elif kind == 'upload':
        actor = user
        slots['n'] = _text((event.get('file') or {}).get('name') if isinstance(event.get('file'), dict) else '', NAME_CHARS)
    elif kind == 'profile_like':
        actor = operator
    elif kind == 'gray_tip':
        actor = user
        slots['n'] = _text(event.get('content'), NOTE_CHARS)
    elif kind in ('friend_add', 'offline'):
        actor = user if kind == 'friend_add' else ''
    else:                                                 # the three requests
        actor = user
        note = _text(event.get('comment'), NOTE_CHARS)
        slots['n'] = '，附言「%s」' % note if note and kind != 'request_invite' else ''
        out['request'] = {'flag': str(event.get('flag') or ''), 'type': 'friend' if kind == 'request_friend' else 'group',
                          **({} if kind == 'request_friend' else {'sub_type': event.get('sub_type')})}
        if not out['request']['flag']:
            return None
    if actor == own:
        return None                                       # her own doing: its receipt already told her
    out['actor'] = actor
    out['where'] = ('home' if kind in HOME_KINDS
                    else 'group' if group else 'dm')
    words = WORDS[variant]
    for key, value in slots.items():
        words = words.replace('{%s}' % key, value)
    out['words'] = words
    return out


class Counts:
    """How many of each kind arrived, by UTC day, with no content; kept across restarts."""

    def __init__(self, data_dir, clock=time.time):
        self.path = os.path.join(data_dir, 'notices', 'counts.json')
        self.clock = clock
        self._lock = threading.Lock()
        self._saved = 0.0
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                self.days = {str(k): {str(a): int(b) for a, b in v.items()}
                             for k, v in (json.load(handle).get('days') or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            self.days = {}

    def _day(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime('%Y-%m-%d')

    def add(self, kind, outcome=None):
        with self._lock:
            day = self.days.setdefault(self._day(), {})
            day[kind] = day.get(kind, 0) + 1
            if outcome:
                day[kind + ':' + outcome] = day.get(kind + ':' + outcome, 0) + 1
            for old in sorted(self.days)[:-DAYS_KEPT]:
                del self.days[old]
            due = self.clock() - self._saved >= SAVE_EVERY
        if due:
            self.save()

    def save(self):
        with self._lock:
            self._saved = self.clock()
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as handle:
                json.dump({'version': 1, 'words_version': WORDS_VERSION, 'days': self.days}, handle, sort_keys=True)
                handle.write('\n')
            os.replace(tmp, self.path)

    def summary(self):
        with self._lock:
            today = dict(self.days.get(self._day(), {}))
            week = {}
            for day in sorted(self.days)[-7:]:
                for kind, count in self.days[day].items():
                    week[kind] = week.get(kind, 0) + count
        return {'words_version': WORDS_VERSION, 'shown': sorted(SHOWN), 'today': today, 'last_7_days': week}


def _stamp(ts):
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def envelope(proj, event, cfg, seen):
    """(the event to post for a shown group or private-chat line, None) or (None, why it is dropped): the same
    gates as a message from the person who did it."""
    own, actor, group = str(cfg.napcat['account_id']), proj.get('actor') or '', proj.get('group_id') or ''
    if str(event.get('self_id')) != own:
        return None, 'wrong_self'
    if not actor or actor in cfg.blocked_senders or not 4 <= len(actor) <= 20:
        return None, 'unauthorized_sender'
    route = cfg.route_for_group(group) if group else cfg.route_for_sender(actor)
    if route is None:
        return None, 'group_not_allowed' if group else 'unauthorized_sender'
    if group and not cfg.is_group_member(group, actor):
        return None, 'unauthorized_group_member'
    occurred = _stamp(event.get('time'))
    ident = proj.get('message_id') or str(event.get('target_id') or '')
    event_id = 'notice-%s-%s-%s' % (proj['kind'], ident or '-', actor)
    if not seen.add_if_new((route.route_id, event_id, occurred)):
        return None, 'duplicate_local'
    block = {'kind': proj['kind'], 'words_version': WORDS_VERSION}
    if group and proj['kind'] in GATES:
        block['gate'] = GATES[proj['kind']]
    if proj.get('message_id'):
        block['line'] = {'message_id': proj['message_id'][:40], 'mine': proj['kind'] == 'reaction'}
    out = {'route_id': route.route_id, 'account_id': own, 'sender_id': actor, 'event_id': event_id[:200],
           'text': proj['words'], 'raw': {'asuna_notice': block}}
    if occurred:
        out['occurred_at'] = occurred
    if group:
        out['group_id'] = group
        out['mentioned_account_ids'] = list(proj['people'])
    return out, None


class HomePoster:
    """Posts the lines about her own account to the host from its own thread, with the names they need (read-only
    `get_stranger_info` for who did it, `get_group_info` for a group she has no conversation in)."""

    TRIES, WAIT, TIMEOUT = 5, 5.0, 5.0

    def __init__(self, cfg, onebot, host, counters, log=print, sleep=time.sleep):
        self.cfg, self.onebot, self.host, self.counters, self.log, self.sleep = cfg, onebot, host, counters, log, sleep
        self.jobs = queue.Queue()

    def put(self, proj, event):
        self.jobs.put((proj, event.get('time')))

    def loop(self, stop):
        while not stop.is_set():
            try:
                job = self.jobs.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.post(*job)
            except Exception as exc:
                self.counters.inc('notice_home_error')
                self.log('NOTICE_HOME_ERROR type=%s' % type(exc).__name__)

    def _name(self, action, params, field):
        try:
            resp = self.onebot.api_call(action, params, timeout=self.TIMEOUT, meta={'notice': action})
        except Exception:
            return ''
        data = resp.get('data') if isinstance(resp, dict) and resp.get('retcode') == 0 else None
        return _text(data.get(field), NAME_CHARS) if isinstance(data, dict) else ''

    def body(self, proj, at):
        body = {'kind': proj['kind'], 'words': proj['words']}
        if proj.get('actor'):
            body['actor_name'] = self._name('get_stranger_info', {'user_id': int(proj['actor'])}, 'nickname')
        if proj.get('group_id'):
            body['group_id'] = proj['group_id']
            if self.cfg.route_for_group(proj['group_id']) is None:
                body['group_name'] = self._name('get_group_info', {'group_id': int(proj['group_id'])}, 'group_name')
        if proj.get('request'):
            body['request'] = proj['request']
        if type(at) is int and at > 0:
            body['at'] = at
        return {key: value for key, value in body.items() if value != ''}

    def post(self, proj, at):
        body = self.body(proj, at)
        for tries in range(self.TRIES):
            if tries:
                self.sleep(self.WAIT)
            res = self.host.post_notice(body)
            if res.kind == 'accepted':
                self.counters.inc('notice_home_posted')
                self.log('NOTICE_HOME kind=%s status=%s' % (body['kind'], (res.obj or {}).get('status')))
                return 'posted'
            if res.kind != 'retry':
                break
        self.counters.inc('notice_home_failed')
        self.log('NOTICE_HOME_FAILED kind=%s http=%s error=%s'
                 % (body['kind'], res.code,
                    str((res.obj or {}).get('error', '') if isinstance(res.obj, dict) else res.error)[:160]))
        return 'failed'
