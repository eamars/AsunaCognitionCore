"""What her night turns changed, for her first heartbeat after them.

Her night turns (self-improvement and settlement, by kind, not by the clock) can change things her daytime self
then does not know about. The first home heartbeat after them lists what they changed: when, what, and the reason
she wrote then, or, for a call without one, the thought it came from (reasons.py). What counts is the one table of
calls with consequences (`reasons.consequential`). Her work log is a running record, so only its section names are
listed. Lookups and refused calls do not count. Computed from the audit each time; nothing is kept. A later heartbeat
starts after the earlier one, so the block appears once, and not at all after a night with no changes.
"""
from __future__ import annotations

from datetime import timedelta

NIGHT_KINDS = ('self_development', 'settlement')
LOOKBACK = timedelta(hours=48)
SHOWN = 12
JOURNAL = 'work_log'
NOTE = ('夜里那几轮（自我改进、夜间沉淀）里你做过的事，按时间先后；why 是你当时写的理由，'
        '没写理由的带 your_thought_then，是你当时的心里话。work_log 只列节名，要看就 recall 那一节。')
DECISIONS = {'adopt': '采纳', 'defer': '先放着', 'drop': '不要了'}


def _short(value, limit=40):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def _what(store, persona, tool, args):
    from . import places
    from .people import People
    op = args.get('op')
    if tool == 'group_focus':
        found = places.find(store.config, args.get('place'))
        scene = store.db.scenes.find_one({'_id': found[0]}) if found else None
        title = People(store, persona).scene_title(scene) if scene else args.get('place')
        return '让%s%s' % (title, '常驻' if op == 'active' else '歇着')
    if tool == 'set_policy':
        return '改设置 %s → %s' % (args.get('key'), _short(args.get('value'), 30))
    if tool == 'update_self':
        return '改了自己的 %s' % (args.get('target') or args.get('layer') or '那一份')
    if tool == 'restart':
        return {'request': '挂了重启', 'drill': '挂了重启演练', 'cancel': '撤了重启'}[op] + (
            '（%s）' % args['when'] if args.get('when') else '')
    if tool == 'plan':
        intent = args.get('intent') or (store.db.plans.find_one({'_id': args.get('plan_id')}, {'intent': 1}) or {}).get('intent')
        return {'create': '定了计划', 'update': '改了计划', 'cancel': '撤了计划'}[op or 'create'] + '：' + _short(intent, 30)
    if tool == 'peer_line':
        return '旧居那条线：' + ('开了' if op == 'open' else '关了')
    if tool == 'review_idea':
        idea = (store.db.ideas.find_one({'_id': args.get('idea')}, {'idea': 1}) or {}).get('idea')
        return '想法%s：%s' % (DECISIONS.get(args.get('decision'), args.get('decision')), _short(idea, 30))
    if tool == 'watch':
        return '%s盯 %s' % ('开始' if op == 'on' else '不再', _short(args.get('person'), 20))
    if tool == 'write_document':
        doc = str(args.get('doc') or '')
        if doc.startswith('group:'):
            found = places.find(store.config, 'g' + doc[6:12])         # a group's notes: slug and place share the hash
            scene = store.db.scenes.find_one({'_id': found[0]}) if found else None
            doc = '%s的群笔记' % (People(store, persona).scene_title(scene) if scene else '一个群')
        return '%s 的「%s」：%s' % (doc, _short(args.get('heading') or args.get('sid'), 30), args.get('op'))
    from .reasons import _action
    return _action(tool, args) or tool


def _kinds(store, ids):
    return {row['_id']: row.get('episode_kind') for row in store.db.episodes.find({'_id': {'$in': list(ids)}},
                                                                                 {'episode_kind': 1})}


def _last_heartbeat(store, current, since):
    """When the latest earlier heartbeat turn started (or `since`)."""
    started = [row for row in store.db.audit_events.find({'type': 'turn.started', 'occurred_at': {'$gte': since}},
                                                         {'stream_id': 1, 'occurred_at': 1})
               if row['stream_id'] != current]
    kinds = _kinds(store, {row['stream_id'] for row in started})
    beats = [row['occurred_at'] for row in started if kinds.get(row['stream_id']) == 'presence']
    return max(beats) if beats else since


def block(store, persona, zone, moment, current):
    """night_from_program: what her night turns changed since the last heartbeat; None when nothing."""
    from .schedule_rules import line_stamp
    since = _last_heartbeat(store, current, (moment - LOOKBACK).isoformat())
    from . import reasons
    calls = [row for row in store.db.audit_events.find(
        {'type': 'role_tool', 'occurred_at': {'$gt': since}, 'payload.refused': {'$exists': False}},
        {'stream_id': 1, 'occurred_at': 1, 'payload': 1}).sort('occurred_at', 1)]
    kinds = _kinds(store, {row['stream_id'] for row in calls})
    items, journal = [], []
    for row in calls:
        payload = row.get('payload') or {}
        tool, args = payload.get('tool'), payload.get('args') or {}
        if not reasons.consequential(tool, args) or kinds.get(row['stream_id']) not in NIGHT_KINDS:
            continue
        if tool == 'write_document' and args.get('doc') == JOURNAL:
            heading = args.get('heading') or args.get('sid')
            if heading and heading not in journal:
                journal.append(_short(heading, 40))
            continue
        item = {'at': line_stamp(zone, row['occurred_at']), 'what': _what(store, persona, tool, args)}
        why = args.get('why') or args.get('reason')
        if why:
            item['why'] = _short(why, 80)
        else:
            ref = payload.get('reason_ref') or reasons.reason_of(
                store.db.episodes.find_one({'_id': row['stream_id']}, {'tool_calls': 1}), payload.get('call_id'))
            then = reasons.thought(store, ref)
            if then:
                item['your_thought_then'] = then
        items.append(item)
    if not items and not journal:
        return None
    result = {'items': items[:SHOWN], 'note': NOTE}
    if len(items) > SHOWN:
        result['more'] = '还有 %d 件没列出来' % (len(items) - SHOWN)
    if journal:
        result['work_log'] = journal
    return result
