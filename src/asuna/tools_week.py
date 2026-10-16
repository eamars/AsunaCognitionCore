"""tools_week_from_program (ADR-070): her week of tools in raw readings, each with its source, for her own review.

Once a week in a self-evaluation turn, beside her memory week; when nine days pass without it (its week and two days
for the roll to come by itself), the next heartbeat that reaches her at home carries it whatever it rolled. The program
counts and says where it counted; it judges nothing. What she proposes is hers: what she can do herself she does, and
what needs the program goes to the developer's line with `ask`, whose answers come back here the next week.
"""
from __future__ import annotations

import collections
import json
import re
import statistics
from datetime import datetime, timedelta, timezone

from .config import excerpt

TABLES_VERSION = 1
WEEK_DAYS = 7
FLOOR_DAYS = 9                       # its week, and two days more for the roll to come by itself
CHARS = 3200                         # measured on her week (2026-10-16): all but parameters fit
EXAMPLE_CHARS = 50
REFUSED_GROUPS = 6                   # the most frequent; the rest summed in one line
ASKED_SHOWN = 6
ANSWER_CHARS = 160
SHOWN = 'review.tools_week'          # the audit record of a showing, with the list it saw
STARTED = 'review.tools_week.started' # before the first showing: where its floor counts from
# The action brain's tools that only read: a task that used nothing else was a lookup.
READING = ('query_authorized_history', 'digest_authorized_discussion', 'read_image', 'read_file', 'list_files',
           'development_read', 'development_files', 'development_database_read', 'integration_status',
           'ask_character')
CUT_MARK = re.compile(r'（截在这里，原文还有 \d+ 字）$')
# When the readings do not fit, these go in order (the week before is a number beside each call); last time and
# refused never.
CUT_ORDER = ('parameters', 'lengths', 'turn_shape', 'action_brain', 'calls')
CUT_WORDS = '放不下，没给：%s（要看就让行动脑按 sources 去数）'
NOTE = ('这是你这一周用工具的原始读数，上一周的并排放着；sources 写着每一项从哪张表、用什么条件、哪个时间段数的，'
        '你可以自己再数一遍。程序只数，不评。看什么、问什么、提什么由你：一周两三条就够，可以加最多一条没有读数撑着的愿望，'
        '标明是愿望；这周没有要提的就说没有。要动程序的，用 ask 发到开发者的线，一条写清改什么、凭哪个读数、'
        '每个脑多了或少了什么；开发者的回答下周在 last_time 里。')


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat()


def _now():
    return datetime.now(timezone.utc)


def last_shown(store, persona):
    """The audit record of the last showing, or None."""
    return store.db.audit_events.find_one({'type': SHOWN, 'payload.persona': persona}, sort=[('occurred_at', -1)])


def due(store, persona, moment=None):
    """'week' when a week has passed since the last showing (or there was none), 'floor' when nine days have: the next
    home heartbeat carries it then whatever it rolled; None when it was shown within the week."""
    moment = moment or _now()
    last = last_shown(store, persona) or store.db.audit_events.find_one(
        {'type': STARTED, 'payload.persona': persona}, sort=[('occurred_at', -1)])
    if not last:                        # never shown: the floor counts from the first time it was asked about
        store.audit('review:' + persona, STARTED, {'persona': persona})
        return 'week'
    at = datetime.fromisoformat(str(last['occurred_at']).replace('Z', '+00:00'))
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    if moment - at >= timedelta(days=FLOOR_DAYS):
        return 'floor'
    return 'week' if moment - at >= timedelta(days=WEEK_DAYS) else None


def _calls(store, since, until):
    return list(store.db.audit_events.find({'type': 'role_tool', 'occurred_at': {'$gte': since, '$lt': until}},
                                           {'stream_id': 1, 'seq': 1, 'occurred_at': 1, 'payload.tool': 1,
                                            'payload.args': 1, 'payload.refused': 1, 'payload.code': 1,
                                            'payload.old_names': 1}).sort([('occurred_at', 1)]))


def _ability(payload):
    from .role_tools import ability
    args = payload.get('args') if isinstance(payload.get('args'), dict) else {}
    return ability(payload.get('tool'), args)


def _why(payload):
    """What was wrong, as a group: the program's code, else the refusal's first clause."""
    if payload.get('code'):
        return payload['code']
    text = re.sub(r'「[^」]*」', '「…」', str(payload.get('refused') or ''))       # an id or a name is not the kind
    text = re.sub(r'\d+', 'N', text)
    return re.split(r'[：。；（:]', text, maxsplit=1)[0][:30] or text[:30]


def _counts(calls):
    return collections.Counter(_ability(c['payload']) for c in calls if 'refused' not in c['payload'])


def _refused(calls):
    by = collections.OrderedDict()
    later = collections.defaultdict(list)
    for call in calls:
        later[call.get('stream_id')].append(call)
    for call in calls:
        payload = call['payload']
        if 'refused' not in payload:
            continue
        key = (payload.get('tool'), _why(payload))
        item = by.setdefault(key, {'tool': key[0], 'what': key[1], 'times': 0, 'retried': 0,
                                   'example': excerpt(payload['refused'], EXAMPLE_CHARS)})
        item['times'] += 1
        after = [c for c in later[call.get('stream_id')] if c.get('seq', 0) > call.get('seq', 0)]
        if any(c['payload'].get('tool') == payload.get('tool') and 'refused' not in c['payload'] for c in after):
            item['retried'] += 1
    ranked = sorted(by.values(), key=lambda item: -item['times'])
    rest = ranked[REFUSED_GROUPS:]
    if rest:
        ranked = ranked[:REFUSED_GROUPS] + ['另有 %d 类，共 %d 次' % (len(rest), sum(item['times'] for item in rest))]
    return ranked


def _parameters(calls):
    from . import param_names, role_tools
    shown = {name: set(spec.get('parameters') or {}) for name, spec in role_tools.tools().items()}
    written = collections.defaultdict(set)
    olds = collections.Counter()
    for call in calls:
        payload = call['payload']
        tool = payload.get('tool')
        args = payload.get('args') if isinstance(payload.get('args'), dict) else {}
        back = {handler: name for name, handler in param_names.names(tool).items()}
        written[tool] |= {back.get(key, key) for key in args}
        for old in payload.get('old_names') or []:
            olds['%s.%s' % (tool, old)] += 1
    unused = {tool: sorted(shown[tool] - written[tool]) for tool in sorted(written) if tool in shown
              and shown[tool] - written[tool]}
    return {'never_written': unused, 'old_names': dict(olds.most_common())}


def _lengths(calls):
    over, cut = collections.Counter(), collections.Counter()
    for call in calls:
        payload = call['payload']
        text = str(payload.get('refused') or '')
        if payload.get('code') == 'NOTE_TOO_LONG' or '太长了' in text or re.search(r'intent \d+ 字，上限', text):
            over[payload.get('tool')] += 1
        args = payload.get('args') if isinstance(payload.get('args'), dict) else {}
        if 'refused' not in payload and any(isinstance(v, str) and CUT_MARK.search(v) for v in args.values()):
            cut[payload.get('tool')] += 1
    return {'over': dict(over.most_common()), 'sent_cut': dict(cut.most_common())}


def _turn_shape(calls):
    from .role_tools import CALLS_PER_TURN
    per = collections.Counter(c.get('stream_id') for c in calls)
    sizes = sorted(per.values())
    before_think = sum(1 for c in calls if '先用 think' in str(c['payload'].get('refused') or ''))
    return {'turns': len(sizes), 'calls_middle': statistics.median(sizes) if sizes else 0,
            'calls_most': max(sizes) if sizes else 0, 'cap': CALLS_PER_TURN,
            'at_cap': sum(1 for n in sizes if n >= CALLS_PER_TURN), 'refused_before_think': before_think}


def _action_brain(store, since, until):
    tasks = list(store.db.tasks.find({'created_at': {'$gte': since, '$lt': until}}, {'_id': 1, 'state': 1}))
    ids = [task['_id'] for task in tasks]
    used = collections.defaultdict(set)
    tools = collections.Counter()
    for row in store.db.artifacts.find({'task_id': {'$in': ids}}, {'task_id': 1, 'tool': 1}):
        used[row['task_id']].add(row.get('tool'))
        tools[row.get('tool')] += 1
    rejected = list(store.db.audit_events.find({'type': 'execution.rejected', 'occurred_at': {'$gte': since, '$lt': until}},
                                               {'payload.problem': 1}))
    lookups = sum(1 for task in ids if used[task] and used[task] <= set(READING))
    return ({'tasks': len(ids), 'states': dict(collections.Counter(t.get('state') for t in tasks).most_common()),
             'tools': dict(tools.most_common(8)), 'reports_rejected': len(rejected),
             **({'first_rejected': excerpt(rejected[0]['payload'].get('problem'), EXAMPLE_CHARS)} if rejected else {})},
            lookups)


def _lists(store):
    """Her tools as defined now, and the characters of the list each kind of conversation carries."""
    from . import role_tools, visibility
    out = {'tools': sorted(role_tools.tools()), 'chars': {}}
    local = (store.config.get('chat') or {}).get('scene_id')
    picks = {'home': (local, visibility.OWNER_PRIVATE)}
    for kind in ('group', 'dm'):
        scene = store.db.scenes.find_one({'kind': kind, 'channel_id': {'$exists': True}}, {'_id': 1})
        if scene:
            picks[kind] = (scene['_id'], visibility.PUBLIC)
    for kind, (scene_id, cls) in picks.items():
        if not scene_id:
            continue
        try:
            names = role_tools.toolbox(store, {'scene_id': scene_id, 'persona': None,
                                               'manifest': {'session_class': cls}})
            out['chars'][kind] = len(json.dumps(role_tools.specs(names), ensure_ascii=False))
        except Exception:                   # a conversation the program cannot list now: left out, not guessed
            continue
    return out


def _list_change(now, before):
    if not before:
        return '上次没有记下来，从这次开始比。'
    added = sorted(set(now['tools']) - set(before.get('tools') or []))
    gone = sorted(set(before.get('tools') or []) - set(now['tools']))
    sizes = {kind: now['chars'][kind] - (before.get('chars') or {}).get(kind, now['chars'][kind])
             for kind in now['chars']}
    if not added and not gone and not any(sizes.values()):
        return '没变。'
    words = {'home': '家里', 'group': '群', 'dm': '私聊'}
    parts = (['多了 ' + '、'.join(added)] if added else []) + (['少了 ' + '、'.join(gone)] if gone else [])
    parts += ['%s的表 %+d 字' % (words[kind], change) for kind, change in sizes.items() if change]
    return '；'.join(parts) + '。'


def _last_time(store, persona, since):
    """What she asked the developer's line since `since`, and what came of each."""
    from . import questions
    scene_id, _ = questions.developer_place(store.config)
    if not scene_id:
        return []
    out = []
    for row in store.db.questions.find({'persona': persona, 'asked_at': {'$gte': since},
                                        'sources.scene_id': scene_id}).sort('asked_at', 1):
        source = next(s for s in row['sources'] if s.get('scene_id') == scene_id)
        answers = []
        for answer in source.get('answers') or []:
            line = store.db.messages.find_one({'_id': answer.get('line')}, {'text': 1}) if answer.get('line') else None
            if line and line.get('text'):
                answers.append(excerpt(line['text'], ANSWER_CHARS))
        out.append({'asked': excerpt(row.get('text'), EXAMPLE_CHARS), 'asked_at': row.get('asked_at'),
                    'state': questions.STATE_WORDS.get(source.get('state'), source.get('state')),
                    **({'answered': answers} if answers else {})})
    return out[-ASKED_SHOWN:]


def block(store, persona, moment=None):
    """The readings, or None when shown within the week. Records the showing with the list it saw."""
    moment = moment or _now()
    last = last_shown(store, persona)
    if last and due(store, persona, moment) is None:
        return None
    until = _iso(moment)
    since = _iso(moment - timedelta(days=WEEK_DAYS))
    before = _iso(moment - timedelta(days=2 * WEEK_DAYS))
    week, prior = _calls(store, since, until), _calls(store, before, since)
    now_counts, prior_counts = _counts(week), _counts(prior)
    from .role_tools import TOOL_NAMES
    called = {name.split('.')[0] for name in now_counts}
    action, lookups = _action_brain(store, since, until)
    _, prior_lookups = _action_brain(store, before, since)
    lists = _lists(store)
    asked_since = (last or {}).get('occurred_at') or since
    readings = {
        'last_time': _last_time(store, persona, asked_since) or ['上次以来你没往开发者的线提过。'],
        'refused': _refused(week) or ['这周没有被退回的调用。'],
        'calls': {'by_tool': {name: '%d（上周 %d）' % (count, prior_counts[name]) for name, count in now_counts.most_common()},
                  'not_called': sorted(set(TOOL_NAMES) - called)},
        'looking_things_up': {'this_week': lookups, 'week_before': prior_lookups},
        'parameters': _parameters(week),
        'lengths': _lengths(week),
        'turn_shape': _turn_shape(week),
        'action_brain': action,
        'list_change': _list_change(lists, ((last or {}).get('payload') or {}).get('lists')),
    }
    sources = ('窗口 %s 到 %s（上周往前再 7 天）。calls 到 turn_shape：audit_events type=role_tool，refused 按 code 或第一句'
               '（「」和数字抹掉）分组，retried＝同一 stream_id 后面同一工具调成了；looking_things_up：tasks 的 artifacts.tool 全在 '
               'tools_week.READING；action_brain：tasks、artifacts、audit execution.rejected；list_change：对上次展示时记下的表；'
               'last_time：questions 里问开发者那条线的（asked_at ≥ 上次展示）' % (since[:16], until[:16]))
    out = {**readings, 'sources': sources, 'note': NOTE}
    cut = []
    for key in CUT_ORDER:
        if len(json.dumps(out, ensure_ascii=False)) <= CHARS:
            break
        out.pop(key, None)
        cut.append(key)
        out['cut'] = CUT_WORDS % '、'.join(cut)           # counted with the rest: the line saying so takes room too
    store.audit('review:' + persona, SHOWN, {'persona': persona, 'lists': lists, 'tables_version': TABLES_VERSION})
    return out
