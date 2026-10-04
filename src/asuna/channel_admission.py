"""Owner-configured channel admission. Platform events never grant owner access."""
from copy import deepcopy

from . import channel_kinds
from .config import ROOT
from .evidence import canonical, sha
from .state import Denied


def restore_admissions(store):
    for row in store.db.artifacts.find({'kind': 'channel_admission'}):
        channel = store.config.get('channels', {}).get(row['channel_id'])
        if not channel or channel.get('admission') != 'automatic' or channel['account_id'] != row['account_id']:
            continue
        route = deepcopy(row['route'])
        current = channel.setdefault('routes', {}).get(row['route_id'])
        if current:
            if current['scene_id'] != route['scene_id'] or current['target'] != route['target']:
                raise Denied('CHANNEL_ADMISSION_BINDING_CONFLICT')
            if route['target']['type'] == 'group':
                current['members'] = {**route.get('members', {}), **current.get('members', {})}
        else:
            channel['routes'][row['route_id']] = route


def admit(controller, channel_id, body):
    """Called only behind channel authentication; validate before changing state."""
    store = controller.app.store
    channel = store.config['channels'][channel_id]
    platform = channel_kinds.of_channel(channel_id)
    sender, group = body.get('sender_id'), body.get('group_id')
    if body.get('account_id') != channel['account_id']:
        raise Denied('CHANNEL_IDENTITY_DENIED')
    if not isinstance(sender, str) or not platform.ACCOUNT.fullmatch(sender) or sender == channel['account_id']:
        raise Denied('CHANNEL_SENDER_INVALID')
    if group is not None and (not isinstance(group, str) or not platform.ACCOUNT.fullmatch(group)):
        raise Denied('CHANNEL_GROUP_DENIED')
    if sender in channel.get('blocked_senders', []) or group and group in channel.get('blocked_groups', []):
        raise Denied('CHANNEL_BLOCKED')
    existing = channel.get('routes', {}).get(body.get('route_id'))
    if existing:
        from .channels import route_members
        if route_members(existing).get(sender):
            return existing
    if channel.get('admission') != 'automatic':
        raise Denied('CHANNEL_IDENTITY_DENIED')
    kind, target = ('group', group) if group else ('dm', sender)
    expected_id = 'auto-' + kind + '-' + target
    if not existing and body.get('route_id') != expected_id:
        raise Denied('CHANNEL_ROUTE_NOT_AUTHORIZED')
    # Do not let an adapter create a second route for a configured target.
    for route_id, route in channel.get('routes', {}).items():
        if route['target'] == {'type': kind, 'id': target} and route_id != body['route_id']:
            raise Denied('CHANNEL_TARGET_ALREADY_BOUND')
    route = deepcopy(existing) if existing else {
        'scene_id': platform.scene_id(channel['account_id'], kind, target),
        'target': {'type': kind, 'id': target}, 'display_name': target}
    if route['target'] != {'type': kind, 'id': target}:
        raise Denied('CHANNEL_GROUP_DENIED')
    identity = store.db.identities.find_one({'platform': channel_id, 'account_id': sender})
    # One id form for every person on a platform, configured or admitted (qq:<account>).
    person = identity['person_id'] if identity else platform.person_id(sender)
    grant = {'person_id': person, 'workspace': str(ROOT / '.runtime' / 'channels' /
        ('auto-' + sha(canonical([channel_id, channel['account_id'], kind, target, sender]))[:32])),
        'read_only_paths': []}
    if group:
        route.setdefault('members', {})[sender] = grant
    else:
        route.update(sender_id=sender, **grant)
    key = 'channel-admission-' + sha(canonical([channel_id, channel['account_id'], body['route_id']]))
    prior = store.db.artifacts.find_one({'_id': key})
    from .host import prepare_channels
    # Validate all grants before making the admission fact durable. On a
    # storage failure after that point, startup can finish the same admission.
    channel.setdefault('routes', {})[body['route_id']] = route
    try:
        prepare_channels(store, dry_run=True)
    except Exception:
        if existing is None:
            channel['routes'].pop(body['route_id'], None)
        else:
            channel['routes'][body['route_id']] = existing
        raise
    # Admission facts are durable business state, not a second settings store.
    store.put('artifacts', {'_id': key, 'kind': 'channel_admission', 'channel_id': channel_id,
        'account_id': channel['account_id'], 'route_id': body['route_id'], 'route': route,
        'scope_key': 'operator'}, expected=prior['revision'] if prior else None, stream=key)
    prepare_channels(store)
    return route
