"""Who is in a group (owner 2026-10-08, her design in member-list-eval): the channel adapter fetches each admitted
group's member list when it starts and periodically, and posts it when it changed. The host keeps one list per
group in `group_members`, apart from `scene_people` (that roster stays "people who appeared here": a thousand
members there would change what a label means and make every turn scan them). A group turn shows a chosen slice in
words — the people she already knows here, the most recently active, anyone @-mentioned lately — and `find_member`
searches the whole list. Names, roles and when someone last spoke (a timestamp field, shown on the local clock); never raw numbers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import clock
from . import channel_kinds
from .people import People, safe_name
from .records import scenes as scene_records
from .records import messages as message_records
from .records.view import is_text

MAX_MEMBERS = 5000                       # one group's list; a larger one is refused, not cut
RECENT_ACTIVE = 20                       # the most recently active members always shown; find_member reaches the rest
MENTIONED_HOURS = 2                      # @-mentioned this recently: shown
FIND_LIMIT = 10
ROLES = ('owner', 'admin', 'member')
ROLE_WORDS = {'owner': '群主', 'admin': '管理员'}
BLOCK_NOTE = ('这个群的成员名单（程序定时从平台拉的，不是谁都跟你说过话）。这里只列一部分：你在这里认识的人、最近说过话的、'
              '刚被 @ 过的；带标签的可以照抄标签 @ 他。找名单里别的人用 find_member，它给的也是标签。')
# Her own row in the list (the account her channel speaks with here): her names here, never a member to @.
YOU_HERE = '你自己在这个群里的号：%s；你的发言在这里标作「%s」。'
FIND_YOU = '这是你自己（%s）。'
# When she last spoke here and how much today (her shape, 2026-10-22): words that change only at a band's edge, never
# a bare time she would have to subtract, on the conversation's clock like every stamp in her turn. Today's count
# shares places' words (one meaning of 几句 in all her blocks).
TABLES_VERSION = 1
SPOKE_RECENT = ((5, '刚说过'), (30, '半小时内'))         # minutes since her last line here
EVENING_HOUR = 18
SPOKE_DAYS = {'evening': '今晚早先', 'today': '今天早先', 'yesterday': '昨天', 'older': '好几天前'}
YOU_SPOKE = '你上次在这里说话：%s；今天在这里%s。'
NEVER_SPOKE = '你还没在这里说过话。'


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _member(raw, account):
    user = str(raw.get('user_id') if isinstance(raw, dict) else '')
    if not account.fullmatch(user):
        return None
    role = raw.get('role') if raw.get('role') in ROLES else 'member'
    out = {'user_id': user, 'nickname': safe_name(raw.get('nickname'))[:60], 'card': safe_name(raw.get('card'))[:60],
           'role': role}
    for key in ('last_sent_time', 'join_time'):
        if _int(raw.get(key)) is not None:
            out[key] = raw[key]
    return out


# ── the owner of `group_members` ──
# One row per group conversation, by its scene id; a row as stored (`fields` names what to return; `_id` always comes
# back). An id given None, or not text, finds nothing without a read (ADR-104 section 4).
COLLECTION = 'group_members'


def get(store, scene_id, fields=None):
    """The member list of this group conversation, or None."""
    return store.collection(COLLECTION).get(scene_id, fields) if is_text(scene_id) else None


def save(store, row, **kwargs):
    """The revisioned write of a group's list (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, row, **kwargs)


def routed_group(store, channel_id, group, code):
    """The admitted route of a group (not a blocked one), else `<code>_GROUP_NOT_ROUTED`."""
    channel = store.config['channels'][channel_id]
    route = next((r for r in channel.get('routes', {}).values()
                  if r['target']['type'] == 'group' and r['target']['id'] == group), None)
    if not route or group in channel.get('blocked_groups', []):
        raise PermissionError('%s_GROUP_NOT_ROUTED: 群 %s 没有已准入的路由；只收已准入的群' % (code, group[:64]))
    return route


def receive(store, channel_id, body):
    """POST /v1/channels/<id>/members: one group's whole list from the adapter."""
    from .state import now
    group = str(body.get('group_id') or '')
    route = routed_group(store, channel_id, group, 'MEMBERS')
    members = body.get('members')
    if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS:
        raise ValueError('MEMBERS_INVALID: members 要是 1..%d 人的列表（给的是 %s）'
                         % (MAX_MEMBERS, len(members) if isinstance(members, list) else type(members).__name__))
    account = channel_kinds.of_channel(channel_id).ACCOUNT
    rows = [row for row in (_member(raw, account) for raw in members) if row]
    scene = scene_records.get(store, route['scene_id'], fields=['scope_key'])
    if not scene:
        raise PermissionError('MEMBERS_SCENE_UNKNOWN: 这个群还没有对话记录；有人说过话以后再送')
    current = get(store, route['scene_id'])
    save(store, {'_id': route['scene_id'], 'scene_id': route['scene_id'], 'group_id': group,
                 'channel_id': channel_id, 'members': rows, 'count': len(rows),
                 'fetched_at': str(body.get('fetched_at') or now())[:40], 'received_at': now(),
                 'scope_key': scene['scope_key']},
         expected=current['revision'] if current else None, stream=route['scene_id'])
    return {'status': 'stored', 'count': len(rows)}


def _name(member):
    return member.get('card') or member.get('nickname') or ''


def _yours(member):
    """Her own row's names, in words."""
    names = ['昵称「%s」' % member['nickname']] if member.get('nickname') else []
    return '，'.join(names + ['群名片「%s」' % member['card'] if member.get('card') else '没设群名片'])


def _spoken(store, scene_id, moment):
    """Her last line here and today's count, in words (SPOKE_RECENT, SPOKE_DAYS, places' line words)."""
    from .local_time import her_zone
    from .places import _at, _lines_word
    last = message_records.spoken(store, scene_id, with_receipt=True, by='receipt_at').first(
        newest_first=True, fields=['receipt_at'])
    if not last:
        return NEVER_SPOKE
    tz = her_zone(store)['tz']
    at, here = _at(last['receipt_at']).astimezone(tz), moment.astimezone(tz)
    minutes = (moment - at).total_seconds() / 60
    words = next((words for limit, words in SPOKE_RECENT if minutes < limit), None)
    if not words:
        day = 'older' if (here.date() - at.date()).days > 1 else 'yesterday' if at.date() < here.date() else \
              'evening' if at.hour >= EVENING_HOUR else 'today'
        words = SPOKE_DAYS[day]
    start = here.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    today = message_records.spoken(store, scene_id, receipt_since=start).count()
    return YOU_SPOKE % (words, '说了' + _lines_word(today) if today else '还没说话')


def _label(people, scene, member):
    """The label she copies to @ someone she found (ADR-024 amendment, 2026-10-09): a member not yet in this group's
    roster is placed there, marked as looked up, with the names the list has; nothing is ever dropped from it."""
    from .people import ROLES
    profile = {field: ' '.join(str(member[field]).split())[:60] for field in ('card', 'nickname') if member.get(field)}
    if member.get('role') in ROLES:
        profile['role'] = member['role']
    entry = people.entry(scene, people.account_person(scene['_id'], member['user_id']), profile=profile, looked_up=True)
    return people.label(entry)


def _active(member, moment):
    """When they last spoke, as a timestamp field (shown on the local clock), or that nobody saw them speak."""
    sent = member.get('last_sent_time')
    if not sent:
        return {'active': '没见他说过话'}
    return {'last_spoke_at': datetime.fromtimestamp(sent, timezone.utc).isoformat(timespec='seconds')}


def block(store, scene, persona, moment=None):
    """members_from_program for a group turn, or None when no list was received."""
    from .context_budget import MEMBER_LINES
    doc = get(store, scene['_id'])
    if not doc or not doc.get('members'):
        return None
    moment = moment or clock.now()
    platform = channel_kinds.of(scene['_id'])
    people = People(store, persona)
    known = {}
    for entry in people.roster(scene['_id']).values():
        account = platform.account_of(entry.get('author') or entry.get('person')) if platform else None
        if account and entry.get('handle'):
            known[str(account)] = entry
    since = (moment - timedelta(hours=MENTIONED_HOURS)).isoformat()
    mentioned = set()
    for row in message_records.mentions(store, scene['_id'], since).rows(
            fields=['event.group_context.mentioned_account_ids']):
        mentioned.update(str(a) for a in row['event']['group_context']['mentioned_account_ids'])
    mine = people.own_account(scene['_id'])
    own = next((m for m in doc['members'] if m['user_id'] == mine), None) if mine else None
    members = sorted((m for m in doc['members'] if m is not own), key=lambda m: -(m.get('last_sent_time') or 0))
    recent = {m['user_id'] for m in members[:RECENT_ACTIVE]}
    chosen = [m for m in members if m['user_id'] in known or m['user_id'] in recent or m['user_id'] in mentioned]
    items = []
    for member in chosen[:MEMBER_LINES]:
        entry = known.get(member['user_id'])
        item = {'who': people.label(entry) if entry else (_name(member) or '（没名字）'),
                **_active(member, moment)}
        if member['role'] in ROLE_WORDS:
            item['role'] = ROLE_WORDS[member['role']]
        items.append(item)
    leaders = ['%s（%s）' % (_name(m), ROLE_WORDS[m['role']]) for m in members if m['role'] in ROLE_WORDS]
    fetched = doc.get('fetched_at') or doc.get('received_at') or ''
    left = doc['count'] - len(items) - (1 if own else 0)
    you = YOU_HERE % (_yours(own), people.self_name) + _spoken(store, scene['_id'], moment) if own else None
    return {'count': '群里一共 %d 人' % doc['count'], **({'you': you} if you else {}),
            **({'leaders': leaders[:12]} if leaders else {}),
            'items': items, **({'not_shown': '另有 %d 人没列出' % left} if left > 0 else {}),
            **({'list_fetched_at': fetched} if fetched else {}), 'note': BLOCK_NOTE}


def find(store, scene, persona, query, moment=None):
    """find_member: members whose name contains the words (at most FIND_LIMIT), in words."""
    doc = get(store, scene['_id'])
    if not doc:
        raise ValueError('MEMBERS_NOT_AVAILABLE: 这个群还没有成员名单（适配器还没拉过，或这个群没开）；重试也一样，等名单来了再找')
    moment = moment or clock.now()
    needle = query.casefold()
    hits = [m for m in doc['members'] if needle in m.get('nickname', '').casefold() or needle in m.get('card', '').casefold()]
    hits.sort(key=lambda m: -(m.get('last_sent_time') or 0))
    people = People(store, persona)
    mine = people.own_account(scene['_id'])
    you = next((m for m in hits if m['user_id'] == mine), None) if mine else None
    hits = [m for m in hits if m is not you]
    found = [{'who': _label(people, scene, m), **_active(m, moment),
              **({'role': ROLE_WORDS[m['role']]} if m['role'] in ROLE_WORDS else {}),
              **({'also': '群名片「%s」，昵称「%s」' % (m['card'], m['nickname'])} if m.get('card') and m.get('nickname')
                 and m['card'] != m['nickname'] else {})} for m in hits[:FIND_LIMIT]]
    return {'query': query, 'found': found, 'count': len(hits), **({'you': FIND_YOU % _yours(you)} if you else {}),
            'note': ('名单里叫这个名字的有 %d 人，列了最近说过话的 %d 个。' % (len(hits), len(found))) if hits
            else '名单里叫这个名字的只有你自己。' if you else '名单里没有名字带「%s」的人。' % query}
