"""Her places (ADR-012 §4.2, §4.4): the groups she can visit from home, and what a visit sees.

At home, a heartbeat shows her the groups she is in as words only (how busy each is, when she was last there,
her notes' headings, whether she can go now), never a line anyone wrote. If she chooses to go, the program
opens a turn in that group (schedule.py `visit`): a public turn that sees only that group, plus a short
labelled view of the room right now (after Kazusa's 15-minute window). The words come from the versioned
tables below; she reads no counts, ids or timestamps. Nothing here calls a model or writes a message.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .channels import route_members
from .config import ago, character_id, excerpt
from .evidence import sha

TABLES_VERSION = 1
# Lines in the group over the last hour → how it reads.
ACTIVITY = ((0, '没人说话'), (5, '零星有人说话'), (30, '有人在聊'), (None, '很热闹'))
# Different people who spoke over the last hour.
VOICES = ((0, '没有人'), (1, '一个人'), (3, '两三个人'), (None, '好几个人'))
INTENTS = {'errand': '家里有人托你办的事', 'start_topic': '起个话头', 'share_picture': '分享一张你自己做的图',
           'check_in': '露个面、打个招呼', 'write_notes': '只是看看，把看到的写进群笔记'}
OUTCOMES = {'answered': '说了话，有人接了', 'unanswered': '说了话，还没人接', 'sending': '说了话，正在发出去',
            'not_sent': '想说的话没发出去', 'notes': '没说话，写了笔记', 'silent': '看了看，没说话',
            'pending': '还在那儿', 'failed': '没去成'}
SENDING = ('READY', 'QUEUED_EXTERNAL', 'SENDING')
# Intents that open a conversation: these wait until the group has been quiet for heartbeat.quiet_min.
STARTING = ('start_topic', 'share_picture')
# Someone called her (channels.group_context): an @, a reply to her, or her name.
ADDRESSED = ('mentioned_account', 'reply_to_character', 'name_called')
WAKE_REASON = 'visit'
TOPIC_CHARS = 80
VISITS_KEPT = 30
NOTE_HEADINGS = 8
HOUR = timedelta(hours=1)
FINISHED = ('COMMITTED', 'WAITING_TASK')
FAILED = ('FAILED_PROTOCOL', 'FAILED_RUNTIME', 'INTERRUPTED')


def _tier(table, value):
    for limit, words in table:
        if limit is None or value <= limit:
            return words


def _at(value):
    if not value:
        return None
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _ago(moment, since):
    return ago(max(0.0, (moment - since).total_seconds() / 3600))


def place_id(scene_id):
    return 'g' + sha(str(scene_id).encode())[:6]


def groups(config):
    """(scene_id, route, channel) for every group she is routed to and nobody blocked."""
    for channel in (config.get('channels') or {}).values():
        blocked = set(channel.get('blocked_groups') or [])
        for route in (channel.get('routes') or {}).values():
            if route['target']['type'] == 'group' and route['target']['id'] not in blocked:
                yield route['scene_id'], route, channel


def find(config, place):
    return next(((scene_id, route, channel) for scene_id, route, channel in groups(config)
                 if place_id(scene_id) == place), None)


# ── errands (ADR-017, owner 2026-10-06): from a home turn the owner may have her say something elsewhere ──────
ERRAND_CHARS = 500
ERRANDS_PER_DAY = 20
ERRANDS_SHOWN = 5
ERRAND_STATES = {'answered': '发出去了，那边有人接', 'unanswered': '发出去了', 'sending': '正在发',
                 'not_sent': '没发出去', 'silent': '她没发', 'notes': '她没发', 'failed': '没办成（出错了）',
                 'pending': '还在路上'}


def errand_targets(config):
    """(scene_id, route, channel) for every platform chat she has a route to that is not a home one: her groups
    nobody blocked, and the direct chats configured for her."""
    from . import visibility
    home = visibility.owner_private_scenes(config)
    for channel in (config.get('channels') or {}).values():
        blocked = set(channel.get('blocked_groups') or [])
        for route in (channel.get('routes') or {}).values():
            target = route.get('target') or {}
            if route.get('scene_id') in home or target.get('type') not in ('group', 'dm')                     or (target['type'] == 'group' and target.get('id') in blocked):
                continue
            yield route['scene_id'], route, channel


def find_errand(config, place):
    return next(((scene_id, route, channel) for scene_id, route, channel in errand_targets(config)
                 if place_id(scene_id) == place), None)


def errand_places(store, persona):
    """errand_places_from_program: where an errand can go, by name."""
    from .people import People
    people = People(store, persona)
    items = []
    for scene_id, route, _ in errand_targets(store.config):
        scene = store.db.scenes.find_one({'_id': scene_id})
        if scene:
            items.append({'place': place_id(scene_id), 'name': people.scene_title(scene),
                          'kind': '群' if route['target']['type'] == 'group' else '私聊'})
    return items


def errands_lately(store, moment):
    """Errands queued in the last day (the daily cap counts these)."""
    since = (moment - timedelta(days=1)).isoformat()
    return store.db.messages.count_documents({'event.visit.intent': 'errand', 'received_at': {'$gte': since}})


def errand_text(exactly, by=None):
    """by: who at home asked, when it was not the owner (the program names them; it is never assumed)."""
    who = by or '主人'
    return ('这是%s在家里托你来这里办的一件事，不是这里有人叫你。原话在 visit_from_program.request。' % who
            + (('原样转达：照原话发，前面带一句「%s让我转告」。' % who) if exactly else '用适合这里的话把事办了。')
            + '先看看最近的聊天；觉得这里不合适就不发，stay_silent。家里的事这一轮看不到，也别提。')


def errands_block(store, persona, moment):
    """errands_from_program at home: what came of her last errands, as program words only -- never what anyone
    there said back (ADR-017: public words reach home only through her own review)."""
    from .people import People
    people = People(store, persona)
    rows = list(store.db.messages.find({'event.visit.intent': 'errand'},
                                       {'scene_id': 1, 'received_at': 1, 'event.event_id': 1, 'event.visit': 1})
                .sort('received_at', -1).limit(ERRANDS_SHOWN))
    items = []
    for row in rows:
        scene = store.db.scenes.find_one({'_id': row['scene_id']}) or {'_id': row['scene_id']}
        state = outcome(store, {'scene_id': row['scene_id'], 'event_id': row['event']['event_id']})
        items.append({'to': people.scene_title(scene), 'asked': excerpt(row['event']['visit'].get('request'), 60),
                      'state': ERRAND_STATES.get(state, state), 'when': _ago(moment, _at(row.get('received_at')))})
    return {'items': items, 'note': '你最近替家里的人办的事：去了哪儿、办成没有。那边的人怎么回的不在这里，要看等你去那边。'}         if items else None


def visitor(route, channel):
    """Who a visit enters the group as: an authorized member, only so the turn is authorized there. A visit
    turn shows no speaker and no per-person blocks (context.py)."""
    blocked = set(channel.get('blocked_senders') or [])
    members = sorted(grant['person_id'] for sender, grant in route_members(route).items() if sender not in blocked)
    return members[0] if members else None


def night_there(config, scene, moment):
    """Quiet hours there are about other people's night: the route's P5 quiet hours, or the core default."""
    from . import proactive
    limits = proactive.route_settings(config, scene)
    if limits['enabled']:
        windows, offset = limits['quiet_windows'], limits['utc_offset_minutes']
    else:
        windows = [(proactive._clock(start, None), proactive._clock(end, None)) for start, end in proactive.QUIET_DEFAULT]
        offset = None
    windows = [(start, end) for start, end in windows if start is not None and end is not None]
    return proactive.in_quiet(proactive.local_minutes(moment.timestamp(), offset), windows)


def room(store, scene, moment):
    """The room as it is now, from stored rows only."""
    since = (moment - HOUR).isoformat()
    me = character_id(store.config)
    lines = list(store.db.messages.find({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
        'direction': 'inbound', 'received_at': {'$gte': since}}, {'author': 1}))
    last_in = next(iter(store.db.messages.find({'scene_id': scene['_id'], 'direction': 'inbound'},
        {'received_at': 1}).sort('scene_seq', -1).limit(1)), None)
    mine = next(iter(store.db.messages.find({'scene_id': scene['_id'], 'direction': 'outbound', 'author': me,
        'delivery_state': 'DELIVERED'}, {'receipt_at': 1, 'claimed_at': 1, 'scene_seq': 1}).sort('scene_seq', -1).limit(1)), None)
    called = store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'inbound',
        'scene_seq': {'$gt': (mine or {}).get('scene_seq') or 0},
        'event.group_context.wake_reason': {'$in': list(ADDRESSED)}}, {'_id': 1})
    return {'lines': len(lines), 'voices': len({row.get('author') for row in lines}),
            'last_line_at': _at((last_in or {}).get('received_at')),
            'mine_at': _at((mine or {}).get('receipt_at') or (mine or {}).get('claimed_at')),
            'called': bool(called)}


# The pace of a group (owner 2026-10-06): how old the talk is and how much was said since, so she can tell a
# line that is still the topic from one the room has moved past. Facts in words only; what counts as stale is
# hers to learn per group. A stretch is talk without a pause of PACE_GAP; PACE_ROWS bounds the look back.
PACE_VERSION = 1
PACE_GAP = timedelta(minutes=30)
PACE_ROWS = 300
SAID = ((0, '还没有别的话'), (5, '几句'), (20, '一二十句'), (60, '几十句'), (None, '很多句'))


def _span(delta):
    minutes = delta.total_seconds() / 60
    return ('%d 分钟' % round(minutes) if minutes < 60 else '%d 小时' % round(minutes / 60) if minutes < 48 * 60
            else '%d 天' % round(minutes / 1440))


def pace(store, scene, moment, zone):
    """The group's talk as it reads now: the current stretch and, before it, the last pause and what came since."""
    from .schedule_rules import line_stamp
    rows = list(store.db.messages.find({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
        '$or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]},
        {'received_at': 1, 'receipt_at': 1}).sort('scene_seq', -1).limit(PACE_ROWS))
    times = [at for at in (_at(row.get('received_at') or row.get('receipt_at')) for row in rows) if at]
    if not times:
        return {'last_line': '还没见过有人说话'}
    value = {'last_line': '上一句是%s（%s）' % (_ago(moment, times[0]), line_stamp(zone, times[0].isoformat()))}
    stretch = 1
    while stretch < len(times) and times[stretch - 1] - times[stretch] < PACE_GAP:
        stretch += 1
    start = times[stretch - 1]
    value['this_stretch'] = '眼下这一段从 %s 开始，到现在说了%s' % (line_stamp(zone, start.isoformat()),
                                                             _tier(SAID, stretch))
    if stretch < len(times):
        before = times[stretch]
        value['before'] = '再往前停过 %s（%s 到 %s）；%s 那句之后又说了%s' % (
            _span(start - before), line_stamp(zone, before.isoformat()), line_stamp(zone, start.isoformat()),
            line_stamp(zone, before.isoformat()), _tier(SAID, stretch))
    else:
        value['before'] = '往前看的这些话中间没停过'
    return value


def episode_key(visit):
    from .ingress import episode_id
    return episode_id({'scene_id': visit['scene_id'], 'event_id': visit['event_id'], 'episode_kind': 'visit'})


def outcome(store, visit):
    """What happened on one visit, read from its turn and the room afterwards."""
    ep_id = episode_key(visit)
    ep = store.db.episodes.find_one({'_id': ep_id}, {'state': 1, 'tool_calls': 1})
    if not ep:
        source = store.db.messages.find_one({'_id': 'in-' + ep_id}, {'ingress_state': 1})
        return 'failed' if (source or {}).get('ingress_state') == 'FAILED' else 'pending'
    if ep.get('state') not in FINISHED + FAILED:
        return 'pending'
    if ep['state'] in FAILED:
        return 'failed'
    spoken = list(store.db.messages.find({'episode_id': ep_id, 'direction': 'outbound', 'phase': 'SPEAK'},
                                         {'scene_seq': 1, 'delivery_state': 1}))
    said = max((row for row in spoken if row.get('delivery_state') == 'DELIVERED'),
               key=lambda row: row.get('scene_seq') or 0, default=None)
    if said:
        answered = store.db.messages.find_one({'scene_id': visit['scene_id'], 'direction': 'inbound',
                                               'scene_seq': {'$gt': said['scene_seq']}}, {'_id': 1})
        return 'answered' if answered else 'unanswered'
    if spoken:
        return 'sending' if any(row.get('delivery_state') in SENDING for row in spoken) else 'not_sent'
    used = {call.get('tool') for call in (ep.get('tool_calls') or {}).values() if 'result' in call}
    return 'notes' if 'write_document' in used else 'silent'


def local_date(config, model, policy, moment):
    """Her local date (her rhythm's time zone), for the daily counts."""
    from . import schedule_rules
    from .persona_model import timezone as persona_timezone
    zone, _ = persona_timezone(model, policy, config)
    return schedule_rules.local_moment(zone if schedule_rules.is_iana(zone) else 'UTC', moment).date().isoformat()


def today(store, plan, date):
    """Visits made on her local date; one that never got there does not count."""
    return sum(1 for visit in (plan or {}).get('visits') or []
               if visit.get('date') == date and outcome(store, visit) != 'failed')


def last_visit(store, plan, scene_id):
    return next((visit for visit in reversed((plan or {}).get('visits') or [])
                 if visit['scene_id'] == scene_id and outcome(store, visit) != 'failed'), None)


def eligibility(store, scene, plan, settings, moment, date, here=None, intent=None):
    """(can go, words). Deterministic; the view and the visit tool use the same answer. While people are
    talking she may still go and look or take notes; starting a topic or sharing a picture waits for quiet."""
    here = here or room(store, scene, moment)
    if today(store, plan, date) >= settings['per_day']:
        return False, '今天出门的次数用完了'
    if night_there(store.config, scene, moment):
        return False, '那边这会儿是夜里，别去吵'
    visit = last_visit(store, plan, scene['_id'])
    gap = timedelta(minutes=settings['after_own_min'])
    if visit and outcome(store, visit) == 'unanswered':
        gap *= 2                         # she spoke and nobody answered: wait twice as long (as P5 does)
    recent = [at for at in (here['mine_at'], _at((visit or {}).get('at'))) if at]
    if recent and moment - max(recent) < gap:
        return False, '你%s来过这里（说过话或来看过），过一阵再来' % _ago(moment, max(recent))
    if here['last_line_at'] and moment - here['last_line_at'] < timedelta(minutes=settings['quiet_min']):
        if intent in STARTING:
            return False, '这会儿有人在聊；起话头或发图等安静下来，只去看看、写笔记可以'
        return True, '正有人在聊：可以去看看、写笔记；起话头或发图等安静下来'
    return True, '可以去'


def settings(model, policy):
    from .persona_model import effective
    return {'per_day': int(effective(model, 'heartbeat.visits_per_day', policy) or 0),
            'after_own_min': int(effective(model, 'heartbeat.after_own_min', policy) or 0),
            'quiet_min': int(effective(model, 'heartbeat.quiet_min', policy) or 0)}


def places_block(store, persona, model, policy, plan, moment, date):
    """Home view of her groups, in words; None when visits are off or she is in no group."""
    from .documents import DocumentStore
    from .group_admin import notes_slug
    from .people import People
    from .persona_model import effective
    if not effective(model, 'heartbeat.visits', policy):
        return None
    people, docs, rule, items = People(store, persona), DocumentStore(store, persona), settings(model, policy), []
    for scene_id, route, channel in groups(store.config):
        scene = store.db.scenes.find_one({'_id': scene_id})
        if not scene:
            continue
        here = room(store, scene, moment)
        can, why = eligibility(store, scene, plan, rule, moment, date, here)
        notes = [section.get('heading') for section in (docs.read(notes_slug(scene_id))[1] or {}).get('sections', [])
                 if section.get('heading')][:NOTE_HEADINGS]
        visit = last_visit(store, plan, scene_id)
        row = {'place': place_id(scene_id), 'group': people.scene_title(scene),
               'now': _tier(ACTIVITY, here['lines']) + ('，上一句是%s' % _ago(moment, here['last_line_at'])
                                                        if here['last_line_at'] else '，还没见过有人说话'),
               'people': '最近一小时说话的有' + _tier(VOICES, here['voices']),
               'you': ('你%s在这里说过话' % _ago(moment, here['mine_at'])) if here['mine_at'] else '你还没在这里说过话',
               'your_notes': notes or '你还没写过这个群的笔记',
               'can_visit': why}
        if visit:
            row['last_visit'] = '%s来看过：%s' % (_ago(moment, _at(visit['at'])), OUTCOMES[outcome(store, visit)])
        if here['called']:
            row['called_you'] = '你上次说话以后，有人叫过你'
        items.append((not can, row))
    if not items:
        return None
    return {'items': [row for _, row in sorted(items, key=lambda item: item[0])],
            'left_today': max(0, rule['per_day'] - today(store, plan, date)),
            'note': ('你在的群，只有概况，没有原话（新鲜的内容要去了才看得到）。想去哪个看看，就用 visit：'
                     '程序会在那个群里给你开一个回合，你在那儿再决定说不说、说什么。不去也完全正常。'
                     'left_today 是今天还能出门几次。')}


def last_visits_block(store, persona, plan, moment):
    """Her recent visits, brought home: where, when, what happened."""
    from .people import People
    visits = ((plan or {}).get('visits') or [])[-3:]
    if not visits:
        return None
    people = People(store, persona)
    rows = []
    for visit in reversed(visits):
        scene = store.db.scenes.find_one({'_id': visit['scene_id']})
        rows.append({'group': people.scene_title(scene), 'when': _ago(moment, _at(visit['at'])),
                     'went_to': INTENTS.get(visit.get('intent'), ''), 'what': OUTCOMES[outcome(store, visit)]})
    return {'items': rows, 'note': '你最近几次出门：去了哪儿、去做什么、结果怎样。'}


def visit_text(intent, topic):
    return ('这是你自己从家里决定出门来这个群看看，不是有人叫你，也不是新的授权。你出门时的打算：%s%s。'
            '先看看最近的聊天、这里的现场（visit_from_program）和你写的群笔记，再决定：说一句、发一张你自己做的图、'
            '只把看到的写进群笔记，或者 stay_silent。没有合适的话就别硬说。'
            % (INTENTS[intent], '；你想聊的话头：' + topic if topic else ''))


def visit_block(store, scene, visit, moment):
    """The room for a visit turn: Kazusa-style labels in words, about this group only."""
    here = room(store, scene, moment)
    block = {'why': INTENTS.get(visit.get('intent'), ''),
             'here_now': {'activity': _tier(ACTIVITY, here['lines']),
                          'last_line': ('上一句是%s' % _ago(moment, here['last_line_at'])) if here['last_line_at'] else '还没见过有人说话',
                          'people': '最近一小时说话的有' + _tier(VOICES, here['voices']),
                          'you': ('你%s在这里说过话' % _ago(moment, here['mine_at'])) if here['mine_at'] else '你还没在这里说过话'},
             'basis': '你上次说话以后，有人叫过你' if here['called'] else '没人叫你：开口是你自己的主意',
             'note': ('这是你自己出门来的。先读懂这里在聊什么、是谁在说，再决定要不要开口；接不上就别硬接，'
                      '沉默也是正常结果。看到值得记的（谁是谁、聊什么、什么话题和图合适），可以写进群笔记。')}
    if visit.get('intent') == 'errand':
        who = visit.get('by') or '主人'
        block.update(basis='%s托你办的：不是这里有人叫你' % who, request=visit.get('request') or '',
                     how=('原样转达，前面带「%s让我转告」' % who) if visit.get('exactly') else '用适合这里的话说',
                     note='这是%s托你来办的事。先读懂这里在聊什么，再用合适的方式把话带到；不合适就不发。' % who)
    if visit.get('topic'):
        block['topic'] = visit['topic']
    if visit.get('artifact_id'):
        block['picture'] = {'artifact_id': visit['artifact_id'],
                            'note': '这是你出门时想分享的那张图；发不发、配什么话，看了现场再定。'}
    return block


def record(plan, scene_id, event_id, intent, moment, date):
    """The plan's ledger after one visit (newest last, bounded); today's count is read from it."""
    visits = [*((plan or {}).get('visits') or []), {'scene_id': scene_id, 'event_id': event_id, 'intent': intent,
                                                    'at': moment.isoformat(), 'date': date}][-VISITS_KEPT:]
    return {'visits': visits}
