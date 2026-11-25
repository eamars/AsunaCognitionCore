"""Who may use what: the access table. Three origins of work, the resources a tool needs, and one level per resource.

Every task and every one of her turns has one origin:

- `home`: a turn that acts with home's authority (her local chat, a home group, an agent's line, an errand) and the
  work it starts;
- `home_from_outside`: work she takes on in a home turn of her own for someone outside (`whose.by == 'outside'`);
- `outside`: a turn in an outside conversation, or a home turn a note from outside opened, and the work it starts.

A turn's origin is the class it acts with (`guard.authority`). A task's is written once when it is made and never
widens: a continuation, or a task made in a turn about another task, keeps the narrower of its own and that task's. A
task made before origins were stored gets one by the same rule from its stored rows when it is read.

A resource's level names the origins it allows, from home outwards (home < home_from_outside < outside): `home`,
`home_from_outside`, `everywhere` or `none`. `RESOURCES` is the default table; the owner's setting `deployment.access`
names only the rows that differ from it. The worker reads it when it starts (`check` refuses a bad one); every grant
and every call asks `allowed`.
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
STEPS_MOST = 64             # a chain of continuations walked for an old task stops here

# Her words (read and signed by her, agent line 0668).
FROM_OUTSIDE = ('这件是外面的人托的事：跑命令、用钥匙、连家里的网、读盘上的路径，都不在这件事里；'
                '这一步换个做法，文件照样能读、能用。')
DISK_AT_HOME = '盘上的路径只在家里能读。'
NOT_HERE = '这一步这里用不了。'
NOT_IN_OUTSIDE_WORK = ('commands', 'credentials', 'local_network', 'disk')


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


def require(config, origin, resource):
    """Raise the table's refusal when work of this origin may not use this resource."""
    if not allowed(config, origin, resource):
        from .state import Denied
        raise Denied(refusal(origin, resource))


def origin_of_turn(store, ep):
    """A turn's origin: home when it acts with home's authority, else outside."""
    from . import guard
    return 'home' if guard.authority(store, ep) == visibility.OWNER_PRIVATE else 'outside'


def origin_of_new_task(store, ep, whose, earlier=None):
    """The origin of a task this turn makes for `whose`: outside when the turn is outside, home from outside for work
    for someone outside, else home; never wider than `earlier` (the task it continues) or the task the turn is about."""
    if origin_of_turn(store, ep) == 'outside':
        found = 'outside'
    else:
        found = 'home_from_outside' if (whose or {}).get('by') == 'outside' else 'home'
    from .records import tasks as task_records
    about = [row for row in (earlier, task_records.get(store, ep['task_id']) if ep.get('task_id') else None) if row]
    return narrowest(found, *(origin_of_task(store, row) for row in about))


def origin_of_task(store, task, steps=0):
    """A task's origin: as stored, else (a task made before origins were stored) by the same rule from its rows."""
    if task.get('origin') in ORIGINS:
        return task['origin']
    from .records import scenes as scene_records
    scene = scene_records.get(store, task['scene_id']) or {'_id': task['scene_id']}
    if visibility.session_class(store.config, store, scene, task['requester_id']) != visibility.OWNER_PRIVATE:
        found = 'outside'
    else:
        found = 'home_from_outside' if (task.get('whose') or {}).get('by') == 'outside' else 'home'
    if task.get('continues_task_id') and steps < STEPS_MOST:
        from .records import tasks as task_records
        earlier = task_records.get(store, task['continues_task_id'])
        if earlier:
            return narrowest(found, origin_of_task(store, earlier, steps + 1))
    return found
