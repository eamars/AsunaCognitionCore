"""Who may use what: the access table. Three origins of work, the resources a tool needs, and one level per resource.

Every task and every one of her turns has one origin:

- `home`: a turn that acts with home's authority (her local chat, a home group, an agent's line, an errand) and the
  work it starts;
- `home_from_outside`: work she takes on in a home turn of her own for someone outside (`whose.by == 'outside'`);
- `outside`: a turn in an outside conversation, or a home turn a note from outside opened, and the work it starts.

A turn's origin is the class it acts with (`guard.authority`), and a turn about a task (its result, its question, its
time-up) is never wider than that task. A task's is written once when it is made and never widens: a continuation, or
a task made in a turn about another task, keeps the narrower of its own and that task's. A task made before origins
were stored gets one when it is read: by the same rule from the turn that made it, or, when that turn is gone, from
the class of the conversation and the person it runs for.

A resource's level names the origins it allows, from home outwards (home < home_from_outside < outside): `home`,
`home_from_outside`, `everywhere` or `none`. `RESOURCES` is the default table, and the owner's setting
`deployment.access` names only the rows that differ from it. The worker reads it when it starts (`check` refuses a bad
one); every grant and every call asks `allowed`. Every refusal by the table is recorded once (`record`, the audit's
`access.denied`), and her review at home lists it with the row and the column in her words (`mark`).
"""
from __future__ import annotations

from . import visibility

ORIGINS = ('home', 'home_from_outside', 'outside')
LEVELS = ('home', 'home_from_outside', 'everywhere', 'none')
REACH = {'home': ORIGINS[:1], 'home_from_outside': ORIGINS[:2], 'everywhere': ORIGINS, 'none': ()}
RESOURCES = {
    'own_files': 'everywhere',
    'all_files': 'home_from_outside',
    'list_files': 'home_from_outside',
    'disk': 'home',
    'commands': 'home',
    'credentials': 'home',
    'local_network': 'home',
    'internet': 'everywhere',
    'integrations': 'home',
    'development': 'home',
    'drawing': 'everywhere',
    'send_any': 'home',
    'send_to_asker': 'home_from_outside',
    'send_own': 'everywhere',
}
# Outside home no rule says who earns these, so they take no wider level.
HOME_OR_NONE = ('integrations', 'development')
STEPS_MOST = 64             # a walk through turns and tasks for an old task stops here (a broken chain, not a real one)

# Her words (read and signed by her, agent lines 0668 and 0669).
FROM_OUTSIDE = ('这件是外面的人托的事：跑命令、用钥匙、连家里的网、读盘上的路径，都不在这件事里；'
                '文件照样能读、能用。')
DISK_AT_HOME = '盘上的路径只在家里能读。'
NOT_HERE = '这一步这里用不了。'
NOT_IN_OUTSIDE_WORK = ('commands', 'credentials', 'local_network', 'disk')
NOT_TO_SEND = '这个文件不归这个对话发。'
SEND_REFUSED = 'ACCESS_DENIED_SEND: ' + NOT_TO_SEND
# Her review's marks (agent lines 0672, 0681): the row and the column a refusal was met in, in her words; a send is one
# mark whatever row refused it.
ROW_WORDS = {'disk': '盘上的路径', 'commands': '跑命令', 'credentials': '凭据', 'local_network': '家里的网',
             'internet': '公网', 'integrations': '主人的集成', 'development': '自我开发', 'drawing': '画图',
             'own_files': '这个对话自己的文件', 'all_files': '别的对话的文件', 'list_files': '翻看别的对话的文件'}
SENDING = '把这个文件发到这里'
ORIGIN_WORDS = {'home': '家里', 'home_from_outside': '外面托、家里办', 'outside': '外面'}
MARK = '这里不许：%s（%s）'


def levels_of(resource):
    """The levels this resource takes."""
    return ('home', 'none') if resource in HOME_OR_NONE else LEVELS


def check(config):
    """Refuse a setting `access` that names an unknown resource, an unknown level, or a level its row does not take."""
    setting = (config or {}).get('access')
    if setting is None:
        return
    if not isinstance(setting, dict):
        raise ValueError('INVALID_ACCESS: access is a table of resource: level')
    for resource, level in setting.items():
        if resource not in RESOURCES:
            raise ValueError('INVALID_ACCESS: unknown resource %s' % resource)
        if level not in LEVELS:
            raise ValueError('INVALID_ACCESS: %s: unknown level %s (%s)' % (resource, level, ', '.join(LEVELS)))
        if level not in levels_of(resource):
            raise ValueError('INVALID_ACCESS: %s takes only %s' % (resource, ' or '.join(levels_of(resource))))


def table(config):
    """Every resource with its level: the defaults with the owner's rows over them."""
    return {**RESOURCES, **((config or {}).get('access') or {})}


def allowed(config, origin, resource):
    """Whether work of this origin may use this resource."""
    return origin in REACH[table(config)[resource]]


def wider(config):
    """The resources set wider than their default, with their levels."""
    return {resource: level for resource, level in table(config).items()
            if len(REACH[level]) > len(REACH[RESOURCES[resource]])}


def narrowest(*origins):
    """The narrowest of these origins."""
    return max(origins, key=ORIGINS.index)


def words(origin, resource):
    """Her words for a refusal by the table of this resource to work of this origin."""
    if origin == 'home_from_outside' and resource in NOT_IN_OUTSIDE_WORK:
        return FROM_OUTSIDE
    return DISK_AT_HOME if origin == 'outside' and resource == 'disk' else NOT_HERE


def refusal(origin, resource):
    """A refusal by the table, as a tool error: its code (ACCESS_DENIED_<RESOURCE>) and her words."""
    return 'ACCESS_DENIED_%s: %s' % (resource.upper(), words(origin, resource))


def require(store, by, origin, resource, tool, config=None):
    """Raise the table's refusal, recorded (`record`), when work of this origin may not use this resource (by `config`,
    the store's by default)."""
    if not allowed(store.config if config is None else config, origin, resource):
        from .state import Denied
        record(store, by, origin, resource, tool)
        raise Denied(refusal(origin, resource))


def record(store, by, origin, resource, tool, *, send=False):
    """One audit row (`access.denied`) for a refusal by the table: the row, the origin, the tool, the turn (`by`'s
    `turn`, with its `call`) or the task (`task`) it was met in, and whether it was a send. Never what was refused or
    whose it is. `by` None records nothing (a caller with no turn or task)."""
    if not by:
        return
    stream = by.get('task') or by.get('turn')
    store.audit(stream, 'access.denied', {
        'resource': resource, 'origin': origin, 'tool': tool,
        **({'task': by['task']} if by.get('task') else {}), **({'call': by['call']} if by.get('call') else {}),
        **({'send': True} if send else {})}, by.get('scope') or 'operator')


def mark(said):
    """Her review's mark for one `access.denied` row: 这里不许：<the row>（<the column>）."""
    column = ORIGIN_WORDS.get(said.get('origin'), said.get('origin') or '')
    return MARK % (SENDING if said.get('send') else ROW_WORDS.get(said.get('resource'), said.get('resource')), column)


def origin_of_turn(store, ep, steps=0):
    """A turn's origin: home when it acts with home's authority, else outside; a turn about a task (it carries
    `task_id`: the task's result, its question, its time-up) is never wider than that task."""
    from . import guard
    found = 'home' if guard.authority(store, ep) == visibility.OWNER_PRIVATE else 'outside'
    if ep.get('task_id') and steps < STEPS_MOST:
        from .records import tasks as task_records
        task = task_records.get(store, ep['task_id'])
        if task:
            found = narrowest(found, origin_of_task(store, task, steps + 1))
    return found


def origin_of_input(store, event, cls):
    """The origin of the turn an input opens, before its episode is written (the turn's context): as `origin_of_turn`
    reads it from the episode. `cls` is the class of the conversation for the input's person."""
    from . import errands, guard, notes
    if errands.carried(store, event):
        found = 'home'                            # an errand turn carries home's authority
    elif cls != visibility.OWNER_PRIVATE:
        found = 'outside'
    else:
        probe = {'episode_kind': event.get('episode_kind') or 'external', 'manifest': {'session_class': cls}}
        found = 'outside' if guard.from_outside(store, probe, notes.opening_for(store, event)) is not None else 'home'
    if event.get('task_id'):
        from .records import tasks as task_records
        task = task_records.get(store, event['task_id'])
        if task:
            found = narrowest(found, origin_of_task(store, task, 1))
    return found


def origin_of_new_task(store, ep, whose, earlier=None, steps=0):
    """The origin of a task this turn makes for `whose`: the turn's own (outside, or the task it is about), home from
    outside for work for someone outside, else home; never wider than `earlier` (the task it continues)."""
    found = narrowest(origin_of_turn(store, ep, steps),
                      'home_from_outside' if (whose or {}).get('by') == 'outside' else 'home')
    return narrowest(found, origin_of_task(store, earlier, steps + 1)) if earlier else found


def origin_of_task(store, task, steps=0):
    """A task's origin: as stored, else (a task made before origins were stored) by the rule a new task has, from the
    turn that made it; when that turn is gone, from the class of its conversation and person, never wider than the
    task it continues."""
    if task.get('origin') in ORIGINS:
        return task['origin']
    from .records import episodes as episode_records
    from .records import tasks as task_records
    walk = steps < STEPS_MOST
    earlier = (task_records.get(store, task['continues_task_id'])
               if walk and task.get('continues_task_id') else None)
    made = episode_records.get(store, task['episode_id']) if walk and task.get('episode_id') else None
    if made:
        return origin_of_new_task(store, made, task.get('whose'), earlier, steps + 1)
    from .records import scenes as scene_records
    scene = scene_records.get(store, task['scene_id']) or {'_id': task['scene_id']}
    if visibility.session_class(store.config, store, scene, task['requester_id']) != visibility.OWNER_PRIVATE:
        found = 'outside'
    else:
        found = 'home_from_outside' if (task.get('whose') or {}).get('by') == 'outside' else 'home'
    return narrowest(found, origin_of_task(store, earlier, steps + 1)) if earlier else found
