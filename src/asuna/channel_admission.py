"""Channel admission: who may speak to her. The core decides, once (ADR-107); a channel package asks and acts on the
answer. Platform events never grant owner access."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from . import channel_kinds
from .config import DATA
from .evidence import canonical, sha
from .state import Denied, now
from .records import artifacts as artifact_records

# How long a package may reuse an answer (`judge`): a known member for a while, a conversation that open admission
# will admit and every refusal for a minute. The core re-decides at every event, so a reused answer never admits.
TTL_SECONDS = {'known': 300, 'would_admit': 60, 'refused': 60}
AUTO_ROUTE = re.compile(r'auto-(dm|group)-(.+)')


def _in_this_data_folder(route):
    """An admitted person's folder is named by a hash under <data>/channels; the data folder belongs to the profile
    that runs now, so a stored admission's folder is placed there, whatever data folder it was admitted under."""
    grants = route.get('members', {}).values() if route['target']['type'] == 'group' else [route]
    for grant in grants:
        if admitted(grant):
            grant['workspace'] = str(DATA / 'channels' / re.split(r'[\\/]', grant['workspace'])[-1])
    return route


def admitted(grant):
    """Whether a grant was made by an admission, not listed by the owner: its folder is named `auto-<hash>`."""
    return re.split(r'[\\/]', grant.get('workspace') or '')[-1].startswith('auto-')


def mode(channel_id, channel):
    """`automatic` (open) only where the deployment says so and the channel's kind may be open (OPEN_ADMISSION);
    every other channel is `explicit` (closed), a home line included."""
    return 'automatic' if channel.get('admission') == 'automatic' and channel_kinds.open_admission(channel_id) else 'explicit'


def closed_by_kind(config):
    """Channels the deployment opens (`automatic`) whose kind does not declare OPEN_ADMISSION, so they stay closed: a
    platform kind from before the declaration, or one installed beside a newer core. A home line is meant to be closed
    and is not named."""
    return [channel_id for channel_id, channel in (config.get('channels') or {}).items()
            if channel.get('admission') == 'automatic' and not channel_kinds.open_admission(channel_id)
            and not channel_kinds.home(channel_id + ':')]


def restore_admissions(store):
    for row in artifact_records.of_kind(store, 'channel_admission').rows():
        channel = store.config.get('channels', {}).get(row['channel_id'])
        if not channel or mode(row['channel_id'], channel) != 'automatic' or channel['account_id'] != row['account_id']:
            continue
        route = _in_this_data_folder(deepcopy(row['route']))
        current = channel.setdefault('routes', {}).get(row['route_id'])
        if current:
            if current['scene_id'] != route['scene_id'] or current['target'] != route['target']:
                raise Denied('CHANNEL_ADMISSION_BINDING_CONFLICT')
            if route['target']['type'] == 'group':
                current['members'] = {**route.get('members', {}), **current.get('members', {})}
        else:
            channel['routes'][row['route_id']] = route


def _checked(channel, platform, body):
    """The checks every admission passes, in their order, shared by the answer (`judge`) and the admission itself:
    the account, the sender and group ids, the block lists. Raises the refusal's code."""
    sender, group = body.get('sender_id'), body.get('group_id')
    if body.get('account_id') != channel['account_id']:
        raise Denied('CHANNEL_IDENTITY_DENIED')
    if not isinstance(sender, str) or not platform.ACCOUNT.fullmatch(sender) or sender == channel['account_id']:
        raise Denied('CHANNEL_SENDER_INVALID')
    if group is not None and (not isinstance(group, str) or not platform.ACCOUNT.fullmatch(group)):
        raise Denied('CHANNEL_GROUP_DENIED')
    if sender in channel.get('blocked_senders', []) or group and group in channel.get('blocked_groups', []):
        raise Denied('CHANNEL_BLOCKED')


def _moment(text):
    """A UTC time from an ISO 8601 text, or None."""
    try:
        moment = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _member(route, sender, at=None):
    """The grant of a sender who is a member now. A grant whose admission ended is one only for a line the platform
    dated at or before the end: a line spooled before they left, or caught up after, still comes from a member."""
    from .channels import route_members
    grant = route_members(route).get(sender)
    if not grant or not grant.get('ended_at'):
        return grant
    sent, left = _moment(at), _moment(grant['ended_at'])
    return grant if sent is not None and left is not None and sent <= left else None


def admit(controller, channel_id, body):
    """Called only behind channel authentication; validate before changing state. Returns (the route, how the person
    came in): `new` the first time they are admitted into this conversation, `returned` after their admission ended,
    else None."""
    store = controller.app.store
    channel = store.config['channels'][channel_id]
    platform = channel_kinds.of_channel(channel_id)
    sender, group = body.get('sender_id'), body.get('group_id')
    _checked(channel, platform, body)
    existing = channel.get('routes', {}).get(body.get('route_id'))
    if existing and _member(existing, sender, body.get('occurred_at')):
        return existing, None
    if mode(channel_id, channel) != 'automatic':
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
        'target': {'type': kind, 'id': target}}           # its name comes from the platform's messages
    if route['target'] != {'type': kind, 'id': target}:
        raise Denied('CHANNEL_GROUP_DENIED')
    from .records import people as people_records
    key = _key(channel_id, channel, body['route_id'])
    prior = artifact_records.get(store, key)
    back = (route.get('members') or {}).get(sender) if group else None
    if back and back.get('ended_at'):
        # A member whose admission ended: their grant, folder, person and scene are prepared and unchanged; only the
        # mark on the grant goes, and the line that brought them back says so.
        del back['ended_at']
        mark = 'returned'
    else:
        identity = people_records.by_account(store, sender, platform=channel_id)
        # One id form for every person on a platform, configured or admitted (qq:<account>).
        person = identity['person_id'] if identity else platform.person_id(sender)
        from .scene_links import canonical_person_id
        mark = None if people_records.label(store, route['scene_id'] + '|' + (canonical_person_id(store.config, store, person) or person)) else 'new'
        grant = {'person_id': person, 'workspace': str(DATA / 'channels' /
            ('auto-' + sha(canonical([channel_id, channel['account_id'], kind, target, sender]))[:32])),
            'read_only_paths': []}
        if group:
            route.setdefault('members', {})[sender] = grant
        else:
            route.update(sender_id=sender, **grant)
        from .host import prepare_admission
        # Only the new grant is checked and prepared (host.prepare_admission), never every member of every channel:
        # this runs inside the ingress fence. It is validated before the admission fact is durable; the route joins
        # the configuration only once it is prepared, so a failure in between is retried by the sender's next line,
        # and startup finishes the same admission from the stored fact.
        prepare_admission(store, channel_id, body['route_id'], route, sender, dry_run=True)
    # Admission facts are durable business state, not a second settings store.
    artifact_records.save(store, {'_id': key, 'kind': 'channel_admission', 'channel_id': channel_id,
        'account_id': channel['account_id'], 'route_id': body['route_id'], 'route': route,
        'scope_key': 'operator'}, expected=prior['revision'] if prior else None, stream=key)
    if mark != 'returned':
        prepare_admission(store, channel_id, body['route_id'], route, sender)
    channel.setdefault('routes', {})[body['route_id']] = route
    return route, mark


def _key(channel_id, channel, route_id):
    return 'channel-admission-' + sha(canonical([channel_id, channel['account_id'], route_id]))


def judge(store, channel_id, ask, account_id):
    """What the core would do with one ask of a channel package (POST …/admission), and for how long the answer may be
    reused. Pure: it writes nothing and makes no route, folder, identity or scene.

    `ask` is {conversation: {type, id}, sender_id?} or {route_id}. The answer is {verdict: admitted | refused |
    blocked, …}; `admitted` names the route (`known`: it exists and, when a sender was asked, has them as a member;
    not known: open admission will admit it on its first event under that route id)."""
    channel = store.config['channels'][channel_id]
    platform = channel_kinds.of_channel(channel_id)
    open_ = mode(channel_id, channel) == 'automatic'

    def refused(code, scope, verdict='refused'):
        return {'verdict': verdict, 'code': code, 'scope': scope, 'ttl_seconds': TTL_SECONDS['refused']}
    routes = channel.get('routes', {})
    if 'route_id' in ask:
        route = routes.get(ask['route_id'])
        named = AUTO_ROUTE.fullmatch(ask['route_id']) if isinstance(ask['route_id'], str) else None
        if route:
            conversation = dict(route['target'])
        elif named and open_:
            conversation = {'type': named.group(1), 'id': named.group(2)}
        else:
            return refused('CHANNEL_ROUTE_NOT_AUTHORIZED', 'conversation')
        sender = None
    else:
        conversation = ask['conversation']
        sender = ask.get('sender_id')
    kind, target = conversation['type'], conversation['id']
    if not isinstance(target, str) or not platform.ACCOUNT.fullmatch(target):
        return refused('CHANNEL_GROUP_DENIED' if kind == 'group' else 'CHANNEL_SENDER_INVALID', 'conversation')
    if kind == 'dm':
        sender = target if sender is None else sender
        if sender != target:
            return refused('CHANNEL_GROUP_DENIED', 'conversation')
    scope = 'conversation' if kind == 'dm' or sender is None else 'sender'
    if sender is not None:
        try:
            _checked(channel, platform, {'account_id': account_id, 'sender_id': sender,
                                         **({'group_id': target} if kind == 'group' else {})})
        except Denied as exc:
            code = str(exc).split(':')[0]
            if code == 'CHANNEL_BLOCKED':
                return refused(code, 'conversation' if kind == 'group' and target in channel.get('blocked_groups', [])
                               else scope, 'blocked')
            return refused(code, scope)
    elif kind == 'group' and target in channel.get('blocked_groups', []):
        return refused('CHANNEL_BLOCKED', 'conversation', 'blocked')
    held = next(((route_id, route) for route_id, route in list(routes.items()) if route['target'] == conversation), None)
    if held:
        route_id, route = held
        if sender is None or _member(route, sender):
            return {'verdict': 'admitted', 'route_id': route_id, 'conversation': conversation, 'known': True,
                    'ttl_seconds': TTL_SECONDS['known']}
        if not open_:
            return refused('CHANNEL_IDENTITY_DENIED', 'sender')
    elif not open_:
        return refused('CHANNEL_IDENTITY_DENIED', 'conversation')
    route_id = held[0] if held else 'auto-' + kind + '-' + target
    return {'verdict': 'admitted', 'route_id': route_id, 'conversation': conversation, 'known': False,
            'ttl_seconds': TTL_SECONDS['would_admit']}


def depart(controller, channel_id, body):
    """A person is no longer in a group (POST …/departures). Their admission ends: the grant is marked `ended_at`, in
    the configuration and in the stored admission, and their next line is admitted again as a return. Nothing else
    changes: not the person, the scene (its members, its epoch), the roster, the lines or the folder. Only an admitted
    grant ends; a listed one, an unknown sender or a mark already there is `unchanged`. Never creates anything."""
    store = controller.app.store
    channel = store.config['channels'][channel_id]
    platform = channel_kinds.of_channel(channel_id)
    conversation, sender = body.get('conversation'), body.get('sender_id')
    if not isinstance(conversation, dict) or set(conversation) != {'type', 'id'} or conversation['type'] != 'group' \
            or not isinstance(conversation['id'], str) or not isinstance(sender, str) \
            or not platform.ACCOUNT.fullmatch(conversation['id']) or not platform.ACCOUNT.fullmatch(sender):
        raise ValueError('INVALID_DEPARTURE: conversation 要是 {"type": "group", "id": 群号}，sender_id 要是账号')
    if body.get('account_id') != channel['account_id']:
        raise Denied('CHANNEL_IDENTITY_DENIED')
    route_id, route = next(((route_id, route) for route_id, route in channel.get('routes', {}).items()
                            if route['target'] == conversation), (None, None))
    grant = (route.get('members') or {}).get(sender) if route else None
    if not grant or not admitted(grant) or grant.get('ended_at'):
        return {'status': 'unchanged'}
    key = _key(channel_id, channel, route_id)
    prior = artifact_records.get(store, key)
    if not prior:
        return {'status': 'unchanged'}
    left = _moment(body.get('occurred_at'))
    moment = left.astimezone(timezone.utc).isoformat() if left else now()      # when the platform says they left
    stored = deepcopy(prior['route'])
    stored.setdefault('members', {}).setdefault(sender, deepcopy(grant))['ended_at'] = moment
    artifact_records.save(store, {**prior, 'route': stored}, expected=prior['revision'], stream=key)
    grant['ended_at'] = moment
    store.audit(key, 'channel.departed', {'channel_id': channel_id, 'route_id': route_id, 'person_id': grant['person_id'],
                                          'event_id': body.get('event_id')}, 'operator')
    return {'status': 'ended'}
