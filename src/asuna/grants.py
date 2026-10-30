"""Host-owned resource grants, never inferred from a message or model role."""
from pathlib import Path

from .state import Denied


def home_workspaces(config):
    """The working folders of her home places: the local chat's, and each of a home line's speakers' (agent lines,
    the peer line). A task there runs in its own place's folder (/task). Platform places, the owner's DM included,
    are not among them."""
    from . import channel_kinds
    from .channels import route_members
    folders = [(config.get('chat') or {}).get('workspace')]
    for channel in (config.get('channels') or {}).values():
        for route in (channel.get('routes') or {}).values() if isinstance(channel, dict) else ():
            if isinstance(route, dict) and route.get('scene_id') and channel_kinds.home(route['scene_id']):
                folders += [grant.get('workspace') for grant in route_members(route).values()]
    seen = []
    for folder in folders:
        if folder and str(Path(folder).resolve()) not in seen:
            seen.append(str(Path(folder).resolve()))
    return seen


def workspace_grant(config, scene_id, person_id, *, required=True):
    local = config.get('chat', {})
    from .integration import owner_line
    from .visibility import home_group
    if (scene_id, person_id) == (local.get('scene_id'), local.get('person_id')) or owner_line(config, scene_id, person_id)             or home_group(config, scene_id):
        return local                     # the owner in his home chat, on a home line he joins (ADR-051), or anyone in a
                                         # group he trusts as home
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


def workspace_folder(config, scene_id, person_id):
    """The folder a task of this person works in here, made now. An admission and a start make none (ADR-107): the
    folder exists once a task of theirs needs it."""
    folder = Path(workspace_grant(config, scene_id, person_id)['workspace']).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def conversation_workspace(config, scene_id):
    """Whether anyone may hand work to the action brain in this conversation (it then lists the tools that do it;
    each turn still checks its own speaker with workspace_grant)."""
    local = config.get('chat', {})
    from .visibility import home_group
    if scene_id == local.get('scene_id') or home_group(config, scene_id):
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


def development_for(store, whose):
    """Whether a task for this `whose` gets the development tools (ADR-011 §6.1, ADR-111): with self-development enabled
    and the sandbox there, only for what the owner asked in one of his conversations, an agent asked on its own line, or
    her self-development turn handed over (`whose.earns_development`). Nobody else's request carries it: in other
    scenes an improvement can only become an entry in her idea notebook (role_tools.note_idea).
    """
    if (store.config.get('self_development') or {}).get('enabled') is not True:
        return False
    from . import sandbox_backend
    if not sandbox_backend.available(store.config):
        return False                      # her candidates are tested in the sandbox (ADR-010 D5)
    from .whose import earns_development
    return earns_development(store, whose)
