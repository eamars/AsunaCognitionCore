"""Host-owned resource grants, never inferred from a message or model role."""
from .state import Denied


def workspace_grant(config, scene_id, person_id, *, required=True):
    local = config.get('chat', {})
    if (scene_id, person_id) == (local.get('scene_id'), local.get('person_id')):
        return local
    for channel in config.get('channels', {}).values():
        for route in channel.get('routes', {}).values():
            if scene_id == route['scene_id']:
                from .channels import route_members
                if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
                    continue
                for sender, grant in route_members(route).items():
                    if sender in channel.get('blocked_senders', []):
                        continue
                    if person_id == grant['person_id']: return grant
    if required:
        raise Denied('WORKSPACE_NOT_AUTHORIZED: 这个人在这里没有授权的工作区，任务用不了工作区；重试也一样：不用工作区能做的先做，没做成的照实说')
    return {}


def conversation_workspace(config, scene_id):
    """Whether anyone may hand work to the action brain in this conversation (it then lists the tools that do it;
    each turn still checks its own speaker with workspace_grant)."""
    local = config.get('chat', {})
    if scene_id == local.get('scene_id'):
        return bool(local.get('person_id'))
    for channel in config.get('channels', {}).values():
        for route in channel.get('routes', {}).values():
            if scene_id == route['scene_id']:
                from .channels import route_members
                if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
                    continue
                if any(sender not in channel.get('blocked_senders', []) for sender in route_members(route)):
                    return True
    return False


def development_granted(store, scene, event, session_class=None):
    """Who may hand work with the development tools to the action brain (ADR-011 §6.1).

    Two sources only, with self-development enabled: the owner asking in a private chat (the local chat or
    the owner's DM, i.e. an owner-private turn the owner wrote), and her own self-improvement turns. Her
    feedback turns keep the grant of the task they answer. Nobody else's request carries it: in other
    scenes an improvement can only become an entry in her idea notebook (role_tools.note_idea).
    """
    from . import visibility
    if (store.config.get('self_development') or {}).get('enabled') is not True:
        return False
    from . import sandbox_backend
    if not sandbox_backend.available(store.config):
        return False                      # her candidates are tested in the sandbox (ADR-010 D5)
    kind = event.get('episode_kind') or 'external'
    if kind == 'task_feedback':
        return bool((store.db.tasks.find_one({'_id': event.get('task_id')}) or {}).get('development_grant'))
    cls = session_class or visibility.session_class(store.config, store.db, scene, event['person_id'])
    if cls != visibility.OWNER_PRIVATE:
        return False
    return kind in ('self_development', 'external')
