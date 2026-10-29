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

from . import clock
from .config import excerpt
from .records import scenes as scene_records
from .records import messages as message_records
from .records import sessions as session_records
from .records import tasks as task_records
from .records import artifacts as artifact_records

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



def last_shown(store, persona):
    """The audit record of the last showing, or None."""
    from . import audit as audit_trail
    return audit_trail.events(store, SHOWN, persona=persona).first(newest_first=True)


def due(store, persona, moment=None):
    """'week' when a week has passed since the last showing (or there was none), 'floor' when nine days have: the next
    home heartbeat carries it then whatever it rolled; None when it was shown within the week."""
    moment = moment or clock.now()
    from . import audit as audit_trail
    last = last_shown(store, persona) or audit_trail.events(store, STARTED, persona=persona).first(newest_first=True)
    if not last:                        # never shown: the floor counts from the first time it was asked about
        store.audit('review:' + persona, STARTED, {'persona': persona})
        return 'week'
    at = datetime.fromisoformat(str(last['occurred_at']).replace('Z', '+00:00'))
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    if moment - at >= timedelta(days=FLOOR_DAYS):
        return 'floor'
    return 'week' if moment - at >= timedelta(days=WEEK_DAYS) else None


def _calls(store, since, until):
    from . import audit as audit_trail
    return audit_trail.events(store, 'role_tool', since=since, before=until).rows(
        fields=['stream_id', 'seq', 'occurred_at', 'payload.tool', 'payload.args', 'payload.refused', 'payload.code',
                'payload.old_names'])


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
    from .role_tools import CALLS_HARD, CALLS_USUAL
    per = collections.Counter(c.get('stream_id') for c in calls)
    sizes = sorted(per.values())
    before_think = sum(1 for c in calls if '先用 think' in str(c['payload'].get('refused') or ''))
    return {'turns': len(sizes), 'calls_middle': statistics.median(sizes) if sizes else 0,
            'calls_most': max(sizes) if sizes else 0, 'usual': CALLS_USUAL, 'hard': CALLS_HARD,
            'past_usual': sum(1 for n in sizes if n > CALLS_USUAL), 'at_hard': sum(1 for n in sizes if n >= CALLS_HARD),
            'refused_before_think': before_think}


def _action_brain(store, since, until):
    tasks = task_records.created(store, since, until=until).rows(fields=['_id', 'state', 'tier', 'tool_steps'])
    ids = [task['_id'] for task in tasks]
    used = collections.defaultdict(set)
    tools = collections.Counter()
    for row in artifact_records.of_tasks(store, ids).rows(fields=['task_id', 'tool']):
        used[row['task_id']].add(row.get('tool'))
        tools[row.get('tool')] += 1
    from . import audit as audit_trail
    rejected = audit_trail.events(store, 'execution.rejected', since=since, before=until, by=None).rows(
        fields=['payload.problem'])
    lookups = sum(1 for task in ids if used[task] and used[task] <= set(READING))
    from . import action_tiers
    tiers = action_tiers.weekly(tasks)
    return ({'tasks': len(ids), 'states': dict(collections.Counter(t.get('state') for t in tasks).most_common()),
             **({'tiers': tiers} if tiers else {}),
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
        scene = scene_records.channel_scenes(store, kind)
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


LANE_WORDS = {'attend': '要不要接话的判断', 'appraiser': '心情评估', 'summary': '后台摘要'}
SPEECH_NONE = ('这周你说出去的话里，没有一句带着本机的真实路径（发出前程序会把它换成占位名；这个数本来就该是 0）。')
SPEECH_SOME = ('这周你说出去的话里，有 %d 处本来带着本机的真实路径，发出前程序换成了占位名。这个数本来该是 0：'
               '大于 0 就是要查的故障（模型读到之前那层没换掉，或者模型自己编出了路径），值得用 ask 报给开发者。')
REWRITTEN_NONE = ('这周程序没有记下你的请求被改写过：要么这周它没数到（插件没把数交回来），要么藏路径的那层没在工作；'
                  '这个本来每周都大于 0，值得用 ask 问开发者。')
REWRITTEN_SOME = ('这周程序在模型读到之前把本机路径换成占位名的请求：%s。这是这层在工作的证据，平常每处都大于 0。')


def _local_roots(store, persona, since, until):
    """ADR-098: two readings, each with its own criterion — her speech replaced (should be 0) and her requests
    rewritten per conversation (normally above 0)."""
    from . import local_roots
    from .people import People
    from . import audit as audit_trail
    spoken = sum(int((row.get('payload') or {}).get('count') or 0) for row in audit_trail.events(
        store, local_roots.SPEECH_EVENT, since=since, before=until, by=None).each(fields=['payload.count']))
    places = {}
    people = People(store, persona)
    for row in audit_trail.events(store, local_roots.TALLY, stream='roots:' + persona, since=since, before=until,
                                  by=None).each(fields=['payload.sessions']):
        for item in (row.get('payload') or {}).get('sessions') or ():
            lane = item.get('lane')
            if lane in LANE_WORDS:
                where = LANE_WORDS[lane]
            else:
                binding = session_records.get(store, item.get('session_id'), fields=['scene_id']) or {}
                scene = scene_records.get(store, binding.get('scene_id')) if binding.get('scene_id') else None
                where = people.scene_title(scene)
            seen = places.setdefault(where, [0, 0])
            seen[0] += int(item.get('rewritten') or 0)
            seen[1] += int(item.get('requests') or 0)
    rewritten = ('；'.join('%s %d 次（共 %d 次请求）' % (where, n, total) for where, (n, total) in places.items())
                 if places else '')
    return {'speech': SPEECH_SOME % spoken if spoken else SPEECH_NONE,
            'requests': REWRITTEN_SOME % rewritten if rewritten else REWRITTEN_NONE}


# ADR-099: where her thoughts come from the model's thinking, how many turns got one and why the others did not.
# ADR-101: shown in either mode whenever there are such turns, and said to be the program's capture, not her writing.
THOUGHT_WHY = {'no_thinking': '模型没思考', 'redacted': '思考被遮住了', 'capture_failed': '没记上',
               'not_carried': '那一拍的调用没带上模型的思考'}
THOUGHTS_FROM = '这些是程序从模型自己的思考里替你抓下的（那几拍没有让你用 think 自己写）'


def _thoughts(store, since, until):
    """Turns that recorded a summary of the model's thinking as her thought, and those that did not, by why; None
    when the week had neither."""
    from . import audit as audit_trail
    taken = audit_trail.count(store, 'thought.taken', since=since, before=until)
    none = collections.Counter((row.get('payload') or {}).get('why') for row in audit_trail.events(
        store, 'thought.none', since=since, before=until, by=None).each(fields=['payload.why']))
    if not taken and not none:
        return None
    missing = '、'.join('%s %d' % (THOUGHT_WHY.get(why, why), n) for why, n in none.most_common())
    return ('这周 %d 个回合记下了你想法的摘要（别的模型写的）；%d 个回合没有%s。%s。'
            % (taken, sum(none.values()), '（%s）' % missing if missing else '', THOUGHTS_FROM))


def _last_time(store, persona, since):
    """What she asked the developer's line since `since`, and what came of each."""
    from . import questions
    scene_id, _ = questions.developer_place(store.config)
    if not scene_id:
        return []
    out = []
    for row in questions.asked(store, persona, since, scene_id=scene_id).each():
        source = next(s for s in row['sources'] if s.get('scene_id') == scene_id)
        answers = []
        for answer in source.get('answers') or []:
            line = message_records.get(store, answer.get('line'), fields=['text']) if answer.get('line') else None
            if line and line.get('text'):
                answers.append(excerpt(line['text'], ANSWER_CHARS))
        out.append({'asked': excerpt(row.get('text'), EXAMPLE_CHARS), 'asked_at': row.get('asked_at'),
                    'state': questions.STATE_WORDS.get(source.get('state'), source.get('state')),
                    **({'answered': answers} if answers else {})})
    return out[-ASKED_SHOWN:]


def block(store, persona, moment=None):
    """The readings, or None when shown within the week. Records the showing with the list it saw."""
    moment = moment or clock.now()
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
        'local_paths': _local_roots(store, persona, since, until),
    }
    thoughts = _thoughts(store, since, until)
    if thoughts:
        readings['thoughts'] = thoughts
    sources = ('窗口 %s 到 %s（上周往前再 7 天）。calls 到 turn_shape：audit_events type=role_tool，refused 按 code 或第一句'
               '（「」和数字抹掉）分组，retried＝同一 stream_id 后面同一工具调成了；looking_things_up：tasks 的 artifacts.tool 全在 '
               'tools_week.READING；action_brain：tasks、artifacts、audit execution.rejected；list_change：对上次展示时记下的表；'
               'last_time：questions 里问开发者那条线的（asked_at ≥ 上次展示）；local_paths：audit_events '
               'type=roots.speech_replaced 的 count 之和，type=roots.tally 按对话加总'
               '%s' % (since[:16], until[:16], '；thoughts：audit_events type=thought.taken 和 thought.none（按 why）'
                       if 'thoughts' in readings else ''))
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
