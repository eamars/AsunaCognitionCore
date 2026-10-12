"""self_review_from_program (ADR-058): her own day in raw readings, for a heartbeat that rolled self evaluation.

Her review asked for readings, not a summary: a summary would write what she thought then more tidily than it was.
Each item says where and when it comes from; nothing is interpreted. Her local day, from midnight on her clock.
"""
from __future__ import annotations

import collections
from datetime import datetime, time, timezone

from .config import excerpt

EXAMPLE_CHARS = 80
TASK_STATES = {'READY': '排着', 'RUNNING': '在做', 'PAUSED': '停着', 'RETURNED': '交回来了', 'FAILED': '没做成',
               'CANCELLED': '撤了'}
NOTE = ('这是你今天的原始读数（从你的零点算起），带出处，没替你总结：said 你在哪儿说了几句，tasks 今天交出去的事和结果，'
        'refused 被退回的调用按工具数，open 还挂着的事。答应过别人还没销的事程序没有记录，在你的活账里（ledgers_from_program）。')


def _midnight(zone_name, moment):
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = timezone.utc
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time(0), zone).astimezone(timezone.utc)


def block(store, persona, zone_name, moment=None):
    from .people import People
    moment = moment or datetime.now(timezone.utc)
    since = _midnight(zone_name, moment).isoformat()
    people = People(store, persona)
    title = {}

    def where(scene_id):
        if scene_id not in title:
            scene = store.db.scenes.find_one({'_id': scene_id})
            title[scene_id] = people.scene_title(scene) if scene else '一个现在已经没有的对话'
        return title[scene_id]

    said = collections.OrderedDict()
    for row in store.db.messages.find({'direction': 'outbound', 'phase': 'SPEAK', 'receipt_at': {'$gte': since}},
                                      {'scene_id': 1, 'receipt_at': 1}).sort('receipt_at', 1):
        item = said.setdefault(row['scene_id'], {'where': where(row['scene_id']), 'lines': 0})
        item['lines'] += 1
        item['last_at'] = row['receipt_at']
    tasks = [{'title': row.get('title') or row.get('goal'), 'where': where(row['scene_id']),
              'state': TASK_STATES.get(row.get('state'), row.get('state')), 'at': row['created_at'],
              **({'failure': row['failure_type']} if row.get('failure_type') else {})}
             for row in store.db.tasks.find({'created_at': {'$gte': since}},
                                            {'title': 1, 'goal': 1, 'scene_id': 1, 'state': 1, 'created_at': 1,
                                             'failure_type': 1}).sort('created_at', 1)]
    refused = collections.OrderedDict()
    for row in store.db.audit_events.find({'type': 'role_tool', 'occurred_at': {'$gte': since},
                                           'payload.refused': {'$exists': True}},
                                          {'payload.tool': 1, 'payload.refused': 1, 'occurred_at': 1}).sort('occurred_at', 1):
        tool = (row.get('payload') or {}).get('tool')
        item = refused.setdefault(tool, {'tool': tool, 'times': 0, 'first': excerpt(row['payload']['refused'], EXAMPLE_CHARS),
                                         'first_at': row['occurred_at']})
        item['times'] += 1
    open_tasks = [{'title': row.get('title') or row.get('goal'), 'where': where(row['scene_id']),
                   'state': TASK_STATES.get(row['state'], row['state'])}
                  for row in store.db.tasks.find({'state': {'$in': ['READY', 'RUNNING', 'PAUSED']}},
                                                 {'title': 1, 'goal': 1, 'scene_id': 1, 'state': 1})]
    return {'said': list(said.values()), 'tasks': tasks, 'refused': list(refused.values()), 'open': open_tasks,
            'since_at': since, 'note': NOTE}
