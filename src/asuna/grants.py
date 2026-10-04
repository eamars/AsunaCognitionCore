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
                for grant in route_members(route).values():
                    if person_id == grant['person_id']: return grant
    if required:
        raise Denied('WORKSPACE_NOT_AUTHORIZED')
    return {}
