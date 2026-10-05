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
from .config import ago, character_id
from .evidence import sha

TABLES_VERSION = 1
# Lines in the group over the last hour → how it reads.
ACTIVITY = ((0, '没人说话'), (5, '零星有人说话'), (30, '有人在聊'), (None, '很热闹'))
# Different people who spoke over the last hour.
VOICES = ((0, '没有人'), (1, '一个人'), (3, '两三个人'), (None, '好几个人'))
INTENTS = {'start_topic': '起个话头', 'share_picture': '分享一张你自己做的图',
           'check_in': '露个面、打个招呼', 'write_notes': '只是看看，把看到的写进群笔记'}
OUTCOMES = {'answered': '说了话，有人接了', 'unanswered': '说了话，还没人接', 'sending': '说了话，正在发出去',
            'not_sent': '想说的话没发出去', 'notes': '没说话，写了笔记', 'silent': '看了看，没说话',
            'pending': '还在那儿', 'failed': '没去成'}
SENDING = ('READY', 'QUEUED_EXTERNAL', 'SENDING')
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


def outcome(store, visit):
    """What happened on one visit, read from its turn and the room afterwards."""
    from .ingress import episode_id
    ep_id = episode_id({'scene_id': visit['scene_id'], 'event_id': visit['event_id'], 'episode_kind': 'visit'})
    ep = store.db.episodes.find_one({'_id': ep_id}, {'state': 1, 'tool_calls': 1})
    if not ep or ep.get('state') not in FINISHED + FAILED:
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


def today(plan, date):
    day = (plan or {}).get('visits_day') or {}
    return day.get('count', 0) if day.get('date') == date else 0


def last_visit(plan, scene_id):
    return next((visit for visit in reversed((plan or {}).get('visits') or []) if visit['scene_id'] == scene_id), None)


def eligibility(store, scene, plan, settings, moment, date, here=None):
    """(can go, words). Deterministic; the view and the visit tool use the same answer."""
    here = here or room(store, scene, moment)
    if today(plan, date) >= settings['per_day']:
        return False, '今天出门的次数用完了'
    if night_there(store.config, scene, moment):
        return False, '那边这会儿是夜里，别去吵'
    visit = last_visit(plan, scene['_id'])
    gap = timedelta(minutes=settings['after_own_min'])
    if visit and outcome(store, visit) == 'unanswered':
        gap *= 2                         # she spoke and nobody answered: wait twice as long (as P5 does)
    recent = [at for at in (here['mine_at'], _at((visit or {}).get('at'))) if at]
    if recent and moment - max(recent) < gap:
        return False, '你%s来过这里（说过话或来看过），过一阵再来' % _ago(moment, max(recent))
    if here['last_line_at'] and moment - here['last_line_at'] < timedelta(minutes=settings['quiet_min']):
        return False, '这会儿有人在聊；有人叫你时你会知道，等安静下来再来起话头'
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
        visit = last_visit(plan, scene_id)
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
            'left_today': max(0, rule['per_day'] - today(plan, date)),
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
    if visit.get('topic'):
        block['topic'] = visit['topic']
    if visit.get('artifact_id'):
        block['picture'] = {'artifact_id': visit['artifact_id'],
                            'note': '这是你出门时想分享的那张图；发不发、配什么话，看了现场再定。'}
    return block


def record(plan, scene_id, event_id, intent, moment, date):
    """The plan fields after one visit: the ledger (newest last, bounded) and today's count."""
    visits = [*((plan or {}).get('visits') or []), {'scene_id': scene_id, 'event_id': event_id, 'intent': intent,
                                                    'at': moment.isoformat()}][-VISITS_KEPT:]
    return {'visits': visits, 'visits_day': {'date': date, 'count': today(plan, date) + 1}}
