"""Who is in a group (owner 2026-10-08, her design in member-list-eval): the channel adapter fetches each admitted
group's member list when it starts and periodically, and posts it when it changed. The host keeps one list per
group in `group_members`, apart from `scene_people` (that roster stays "people who appeared here": a thousand
members there would change what a label means and make every turn scan them). A group turn shows a chosen slice in
words — the people she already knows here, the most recently active, anyone @-mentioned lately — and `find_member`
searches the whole list. Names, roles and how long ago someone last spoke; never raw numbers or timestamps.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import channel_kinds
from .config import ago
from .people import People, safe_name

MAX_MEMBERS = 5000                       # one group's list; a larger one is refused, not cut
RECENT_ACTIVE = 50                       # the most recently active members always shown
MENTIONED_HOURS = 2                      # @-mentioned this recently: shown
FIND_LIMIT = 10
ROLES = ('owner', 'admin', 'member')
ROLE_WORDS = {'owner': '群主', 'admin': '管理员'}
BLOCK_NOTE = ('这个群的成员名单（程序定时从平台拉的，不是谁都跟你说过话）。这里只列一部分：你在这里认识的人、最近说过话的、'
              '刚被 @ 过的；带标签的可以照抄标签 @ 他。找名单里别的人用 find_member，它给的也是标签。')


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _member(raw):
    user = str(raw.get('user_id') if isinstance(raw, dict) else '')
    if not user.isdigit() or not 4 <= len(user) <= 20:
        return None
    role = raw.get('role') if raw.get('role') in ROLES else 'member'
    out = {'user_id': user, 'nickname': safe_name(raw.get('nickname'))[:60], 'card': safe_name(raw.get('card'))[:60],
           'role': role}
    for key in ('last_sent_time', 'join_time'):
        if _int(raw.get(key)) is not None:
            out[key] = raw[key]
    return out


def receive(store, channel_id, body):
    """POST /v1/channels/<id>/members: one group's whole list from the adapter."""
    from .state import now
    channel = store.config['channels'][channel_id]
    group = str(body.get('group_id') or '')
    route = next((r for r in channel.get('routes', {}).values()
                  if r['target']['type'] == 'group' and r['target']['id'] == group), None)
    if not route or group in channel.get('blocked_groups', []):
        raise PermissionError('MEMBERS_GROUP_NOT_ROUTED: 群 %s 没有已准入的路由；只收已准入群的名单' % group[:20])
    members = body.get('members')
    if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS:
        raise ValueError('MEMBERS_INVALID: members 要是 1..%d 人的列表（给的是 %s）'
                         % (MAX_MEMBERS, len(members) if isinstance(members, list) else type(members).__name__))
    rows = [row for row in map(_member, members) if row]
    scene = store.db.scenes.find_one({'_id': route['scene_id']}, {'scope_key': 1})
    if not scene:
        raise PermissionError('MEMBERS_SCENE_UNKNOWN: 这个群还没有对话记录；有人说过话以后再送')
    current = store.db.group_members.find_one({'_id': route['scene_id']})
    store.put('group_members', {'_id': route['scene_id'], 'scene_id': route['scene_id'], 'group_id': group,
                                'channel_id': channel_id, 'members': rows, 'count': len(rows),
                                'fetched_at': str(body.get('fetched_at') or now())[:40], 'received_at': now(),
                                'scope_key': scene['scope_key']},
              expected=current['revision'] if current else None, stream=route['scene_id'])
    return {'status': 'stored', 'count': len(rows)}


def _name(member):
    return member.get('card') or member.get('nickname') or ''


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
    sent = member.get('last_sent_time')
    if not sent:
        return '没见他说过话'
    return '最近说话是' + ago(max(0.0, moment.timestamp() - sent) / 3600)


def block(store, scene, persona, moment=None):
    """members_from_program for a group turn, or None when no list was received."""
    from .context_budget import MEMBER_LINES
    doc = store.db.group_members.find_one({'_id': scene['_id']})
    if not doc or not doc.get('members'):
        return None
    moment = moment or datetime.now(timezone.utc)
    platform = channel_kinds.of(scene['_id'])
    people = People(store, persona)
    known = {}
    for entry in people.roster(scene['_id']).values():
        account = platform.account_of(entry.get('author') or entry.get('person')) if platform else None
        if account and entry.get('handle'):
            known[str(account)] = entry
    since = (moment - timedelta(hours=MENTIONED_HOURS)).isoformat()
    mentioned = set()
    for row in store.db.messages.find({'scene_id': scene['_id'], 'received_at': {'$gte': since},
                                       'event.group_context.mentioned_account_ids.0': {'$exists': True}},
                                      {'event.group_context.mentioned_account_ids': 1}):
        mentioned.update(str(a) for a in row['event']['group_context']['mentioned_account_ids'])
    members = sorted(doc['members'], key=lambda m: -(m.get('last_sent_time') or 0))
    recent = {m['user_id'] for m in members[:RECENT_ACTIVE]}
    chosen = [m for m in members if m['user_id'] in known or m['user_id'] in recent or m['user_id'] in mentioned]
    items = []
    for member in chosen[:MEMBER_LINES]:
        entry = known.get(member['user_id'])
        item = {'who': people.label(entry) if entry else (_name(member) or '（没名字）'),
                'active': _active(member, moment)}
        if member['role'] in ROLE_WORDS:
            item['role'] = ROLE_WORDS[member['role']]
        items.append(item)
    leaders = ['%s（%s）' % (_name(m), ROLE_WORDS[m['role']]) for m in members if m['role'] in ROLE_WORDS]
    fetched = doc.get('fetched_at') or doc.get('received_at') or ''
    try:
        age = ago(max(0.0, (moment - datetime.fromisoformat(fetched.replace('Z', '+00:00'))).total_seconds()) / 3600)
    except ValueError:
        age = ''
    return {'count': '群里一共 %d 人' % doc['count'], **({'leaders': leaders[:12]} if leaders else {}),
            'items': items, **({'not_shown': '另有 %d 人没列出' % (doc['count'] - len(items))} if doc['count'] > len(items) else {}),
            **({'list_from': '名单是' + age + '拉的'} if age else {}), 'note': BLOCK_NOTE}


def find(store, scene, persona, query, moment=None):
    """find_member: members whose name contains the words (at most FIND_LIMIT), in words."""
    doc = store.db.group_members.find_one({'_id': scene['_id']})
    if not doc:
        raise ValueError('MEMBERS_NOT_AVAILABLE: 这个群还没有成员名单（适配器还没拉过，或这个群没开）；重试也一样，等名单来了再找')
    moment = moment or datetime.now(timezone.utc)
    needle = query.casefold()
    hits = [m for m in doc['members'] if needle in m.get('nickname', '').casefold() or needle in m.get('card', '').casefold()]
    hits.sort(key=lambda m: -(m.get('last_sent_time') or 0))
    people = People(store, persona)
    found = [{'who': _label(people, scene, m), 'active': _active(m, moment),
              **({'role': ROLE_WORDS[m['role']]} if m['role'] in ROLE_WORDS else {}),
              **({'also': '群名片「%s」，昵称「%s」' % (m['card'], m['nickname'])} if m.get('card') and m.get('nickname')
                 and m['card'] != m['nickname'] else {})} for m in hits[:FIND_LIMIT]]
    return {'query': query, 'found': found, 'count': len(hits),
            'note': ('名单里叫这个名字的有 %d 人，列了最近说过话的 %d 个。' % (len(hits), len(found))) if hits
            else '名单里没有名字带「%s」的人。' % query}
