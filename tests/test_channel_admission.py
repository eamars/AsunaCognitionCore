"""Who may talk to her is decided once, by the core (ADR-107): closed and open admission, the block lists, the answer a
package asks for before it works, the end of an admitted member, the mark on a line, and the folder a task makes.
A stand-in kind that is not a real platform proves the core names none."""
import copy
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from asuna import channel_admission, channel_kinds, grants, integration
from asuna.channels import Channels
from asuna.config import DATA
from asuna.records import people as people_records
from asuna.records import scenes as scene_records
from asuna.state import Denied

ACCOUNT = re.compile(r'[a-z]{4,12}')
BOT = 'botacct'


def stand_in(name, **declared):
    return SimpleNamespace(KIND=name, TITLE=name.title(), ACCOUNT=ACCOUNT, INBOUND_MENTION=re.compile(r'(?!)'),
                           person_id=lambda account: name + ':' + str(account),
                           scene_id=lambda bot, kind, target: '%s:%s:%s:%s' % (name, bot, kind, target),
                           outbound_mention=lambda account: '@' + name + ':' + str(account),
                           adapter_config=lambda adapter, channel: adapter, strip_derived=lambda adapter: adapter,
                           **declared)


def listed_route(channel, group='crew', member='alice'):
    return {'scene_id': channel_kinds.get(channel).scene_id(BOT, 'group', group), 'target': {'type': 'group', 'id': group},
            'members': {member: {'person_id': channel + ':' + member, 'read_only_paths': [],
                                 'workspace': str(DATA / 'channels' / (channel + '-' + group) / member)}}}


@pytest.fixture
def desk(store):
    """A store holding a channel of an open-capable stand-in kind and one of a home-line kind, in the given mode."""
    channel_kinds.register(stand_in('acme', OPEN_ADMISSION=True))
    channel_kinds.register(stand_in('peer', HOME=True))

    def settle(admission, **block):
        store.config.update(
            chat={'scene_id': 'local', 'person_id': 'owner', 'persona': 'demo', 'workspace': str(DATA / 'work' / 'desk-local')},
            channels={name: {'account_id': BOT, 'token': name * 12, 'admission': admission, 'routes': {}, **block}
                      for name in ('acme', 'peer')})
        store.config['channels']['acme']['routes']['crew'] = listed_route('acme')
        return store
    yield settle
    channel_kinds._KINDS.pop('acme', None)
    channel_kinds._KINDS.pop('peer', None)


def controller(store, received=None):
    return SimpleNamespace(app=SimpleNamespace(store=store, evidence=SimpleNamespace(record=lambda *a: None)),
                           ingress_lock=threading.RLock(), reconfiguring=False, stopping=threading.Event(),
                           receive=lambda event: received.append(event) or {'status': 'accepted'})


def event(sender, group=None, route=None, channel='acme'):
    target = group or sender
    return {'route_id': route or 'auto-%s-%s' % ('group' if group else 'dm', target), 'account_id': BOT,
            'sender_id': sender, **({'group_id': group} if group else {})}


def admit(store, body, channel='acme'):
    return channel_admission.admit(controller(store), channel, body)


def asked(store, conversation=None, sender=None, route=None, channel='acme'):
    ask = {'route_id': route} if route else {'conversation': conversation, **({'sender_id': sender} if sender else {})}
    return channel_admission.judge(store, channel, ask, BOT)


def code(call, *args, **kwargs):
    with pytest.raises(Denied) as raised:
        call(*args, **kwargs)
    return str(raised.value).split(':')[0]


def test_closed_admits_only_what_the_owner_listed(desk):
    store = desk('explicit')
    assert admit(store, event('alice', 'crew', 'crew'))[1] is None
    assert code(admit, store, event('bobby', 'crew', 'crew')) == 'CHANNEL_IDENTITY_DENIED'
    assert code(admit, store, event('bobby', 'elsewhere')) == 'CHANNEL_IDENTITY_DENIED'
    assert code(admit, store, event('carolyn')) == 'CHANNEL_IDENTITY_DENIED'
    group = {'type': 'group', 'id': 'crew'}
    assert asked(store, group, 'alice')['known'] is True
    assert asked(store, group, 'bobby')['scope'] == 'sender'
    assert asked(store, {'type': 'group', 'id': 'elsewhere'}, 'bobby')['scope'] == 'conversation'
    assert asked(store, {'type': 'dm', 'id': 'carolyn'})['verdict'] == 'refused'
    assert asked(store, route='crew')['conversation'] == group


def test_open_admits_a_stranger_under_the_name_the_core_gives_with_no_standing_of_the_owner(desk):
    store = desk('automatic')
    assert code(admit, store, event('carolyn', route='made-up')) == 'CHANNEL_ROUTE_NOT_AUTHORIZED'
    would = asked(store, {'type': 'dm', 'id': 'carolyn'})
    assert (would['verdict'], would['known'], would['route_id']) == ('admitted', False, 'auto-dm-carolyn')
    route, how = admit(store, event('carolyn'))
    assert how == 'new' and route['sender_id'] == 'carolyn'
    scene = route['scene_id']
    assert scene_records.get(store, scene)['members'] == ['acme:carolyn']
    assert admit(store, event('carolyn'))[1] is None, 'a person already in comes in unmarked'
    grant = grants.workspace_grant(store.config, scene, 'acme:carolyn')
    assert Path(grant['workspace']).name.startswith('auto-') and not Path(grant['workspace']).exists()
    assert not integration.owner_dm(store.config, scene, 'acme:carolyn') and grant is not store.config['chat']
    # a group, and a second member of it
    assert admit(store, event('dana', 'tribe'))[1] == 'new' and admit(store, event('edgar', 'tribe'))[1] == 'new'
    assert asked(store, {'type': 'group', 'id': 'tribe'}, 'dana')['known'] is True
    assert asked(store, {'type': 'group', 'id': 'tribe'}, 'frank') == {
        'verdict': 'admitted', 'route_id': 'auto-group-tribe', 'conversation': {'type': 'group', 'id': 'tribe'},
        'known': False, 'ttl_seconds': channel_admission.TTL_SECONDS['would_admit']}


@pytest.mark.parametrize('mode', ['explicit', 'automatic'])
def test_a_block_list_wins_in_both_modes(desk, mode):
    store = desk(mode)
    store.config['channels']['acme'].update(blocked_senders=['mallory'], blocked_groups=['trouble'])
    assert code(admit, store, event('mallory', 'crew', 'crew')) == 'CHANNEL_BLOCKED'
    assert code(admit, store, event('alice', 'trouble')) == 'CHANNEL_BLOCKED'
    assert asked(store, {'type': 'group', 'id': 'crew'}, 'mallory')['verdict'] == 'blocked'
    assert asked(store, {'type': 'group', 'id': 'trouble'}) == {
        'verdict': 'blocked', 'code': 'CHANNEL_BLOCKED', 'scope': 'conversation',
        'ttl_seconds': channel_admission.TTL_SECONDS['refused']}


def test_a_home_line_is_never_open_whatever_the_deployment_says(desk):
    store = desk('automatic')
    assert channel_admission.mode('peer', store.config['channels']['peer']) == 'explicit'
    assert channel_admission.mode('acme', store.config['channels']['acme']) == 'automatic'
    assert code(admit, store, event('stranger'), 'peer') == 'CHANNEL_IDENTITY_DENIED'
    assert asked(store, {'type': 'dm', 'id': 'stranger'}, channel='peer')['verdict'] == 'refused'


def test_the_answer_changes_nothing_and_is_the_admission_s(desk):
    senders = ('alice', 'bobby', 'mallory', 'x')
    conversations = [{'type': 'group', 'id': 'crew'}, {'type': 'group', 'id': 'tribe'}, {'type': 'group', 'id': 'trouble'},
                     {'type': 'dm', 'id': 'bobby'}, {'type': 'dm', 'id': 'alice'}, {'type': 'group', 'id': 'BAD'}]
    for mode in ('explicit', 'automatic'):
        for conversation in conversations:
            for sender in (*senders, None):
                store = desk(mode, blocked_senders=['mallory'], blocked_groups=['trouble'])
                before = (copy.deepcopy(store.config['channels']), store.collection('scenes').count({}),
                          store.collection('artifacts').count({}), store.collection('identities').count({}))
                answer = asked(store, conversation, sender)
                assert (copy.deepcopy(store.config['channels']), store.collection('scenes').count({}),
                        store.collection('artifacts').count({}), store.collection('identities').count({})) == before
                if sender is None or conversation['type'] == 'dm' and sender != conversation['id']:
                    continue
                group = conversation['id'] if conversation['type'] == 'group' else None
                if answer['verdict'] != 'admitted':
                    # a refusal or a block is the admission's too: the same code, whatever route id is posted
                    assert code(admit, store, event(sender, group)) == answer['code']
                    continue
                body = event(sender, group, answer['route_id'])
                admit(store, body)                       # the answer's route id is the one the core takes
                assert admit(store, body)[1] is None


def test_a_member_who_left_is_admitted_again_marked_and_nothing_of_who_they_are_changes(desk):
    store = desk('automatic')
    admit(store, event('dana', 'tribe'))
    admit(store, event('edgar', 'tribe'))
    scene = channel_kinds.get('acme').scene_id(BOT, 'group', 'tribe')
    here = lambda: (scene_records.get(store, scene), people_records.identity(store, 'acme:dana'))
    kept = here()
    leave = {'account_id': BOT, 'conversation': {'type': 'group', 'id': 'tribe'}, 'sender_id': 'dana'}
    assert channel_admission.depart(controller(store), 'acme', leave) == {'status': 'ended'}
    assert channel_admission.depart(controller(store), 'acme', leave) == {'status': 'unchanged'}
    assert here() == kept, 'the scene (members, epoch), the person and the roster stay as they were'
    # a stored admission brings the mark back after a start
    for route in list(store.config['channels']['acme']['routes']):
        if route != 'crew':
            del store.config['channels']['acme']['routes'][route]
    channel_admission.restore_admissions(store)
    assert store.config['channels']['acme']['routes']['auto-group-tribe']['members']['dana'].get('ended_at')
    assert asked(store, {'type': 'group', 'id': 'tribe'}, 'edgar')['known'] is True
    assert asked(store, {'type': 'group', 'id': 'tribe'}, 'dana')['known'] is False
    assert admit(store, event('dana', 'tribe'))[1] == 'returned'
    assert admit(store, event('dana', 'tribe'))[1] is None
    assert 'ended_at' not in store.config['channels']['acme']['routes']['auto-group-tribe']['members']['dana']
    assert scene_records.get(store, scene)['policy_epoch'] == kept[0]['policy_epoch']


def test_only_an_admitted_member_of_a_group_can_leave(desk):
    store = desk('automatic')
    admit(store, event('dana', 'tribe'))
    leave = lambda group, sender, **more: channel_admission.depart(
        controller(store), 'acme', {'account_id': BOT, 'conversation': {'type': 'group', 'id': group}, 'sender_id': sender, **more})
    assert leave('crew', 'alice') == {'status': 'unchanged'}, 'a member the owner listed does not end'
    assert leave('tribe', 'nobody') == {'status': 'unchanged'} and leave('nowhere', 'dana') == {'status': 'unchanged'}
    for bad in ({'conversation': {'type': 'dm', 'id': 'dana'}}, {'conversation': {'type': 'group', 'id': 'tribe', 'x': 1}},
                {'sender_id': 'BAD'}):
        with pytest.raises(ValueError, match='INVALID_DEPARTURE'):
            channel_admission.depart(controller(store), 'acme', {
                'account_id': BOT, 'conversation': {'type': 'group', 'id': 'tribe'}, 'sender_id': 'dana', **bad})
    assert code(channel_admission.depart, controller(store), 'acme', {
        'account_id': 'other', 'conversation': {'type': 'group', 'id': 'tribe'}, 'sender_id': 'dana'}) == 'CHANNEL_IDENTITY_DENIED'


def test_the_two_new_endpoints_take_nothing_they_do_not_know(desk):
    store = desk('automatic')
    channels = Channels(controller(store))
    ask = {'conversation': {'type': 'dm', 'id': 'carolyn'}}
    assert channels.admission('acme', {'account_id': BOT, 'asks': [ask]})['answers'][0]['verdict'] == 'admitted'
    for body in ({'account_id': BOT, 'asks': [ask], 'extra': 1}, {'account_id': 'other', 'asks': [ask]}):
        with pytest.raises(PermissionError):
            channels.admission('acme', body)
    for asks in ([], [ask] * (Channels.ADMISSION_ASKS + 1), [{}], [{'route_id': 'crew', 'conversation': ask['conversation']}],
                 [{'route_id': 'crew', 'sender_id': 'alice'}], [{'conversation': {'type': 'room', 'id': 'x'}}],
                 [{'conversation': {'type': 'dm', 'id': 'carolyn', 'x': 1}}], [{'conversation': ask['conversation'], 'x': 1}]):
        with pytest.raises(ValueError, match='INVALID_ADMISSION_ASK'):
            channels.admission('acme', {'account_id': BOT, 'asks': asks})
    with pytest.raises(PermissionError):
        channels.departures('acme', {'account_id': BOT, 'conversation': ask['conversation'], 'sender_id': 'x', 'extra': 1})
    for command, endpoint in (('POST', ['admission']), ('POST', ['departures']), ('GET', ['routes'])):
        with pytest.raises(PermissionError, match='ROUTE_KEY_ENDPOINT_DENIED'):   # a route key reaches only its own line
            channels.scope_check('acme', 'crew', command, endpoint, {})


def test_a_line_carries_how_its_sender_came_in(desk):
    store = desk('automatic')
    received = []
    channels = Channels(controller(store, received))
    line = {**event('carolyn'), 'event_id': '1', 'text': 'hello'}
    channels.receive('acme', line)
    channels.receive('acme', {**line, 'event_id': '2'})
    assert [row.get('admitted') for row in received] == ['new', None]


def test_no_folder_is_made_by_a_start_or_an_admission_only_by_a_task(desk):
    from asuna import host
    store = desk('automatic')
    listed = Path(store.config['channels']['acme']['routes']['crew']['members']['alice']['workspace'])
    host.prepare_channels(store)
    route, _ = admit(store, event('carolyn'))
    folder = Path(route['workspace'])
    try:
        assert not listed.exists() and not folder.exists()
        assert grants.workspace_folder(store.config, route['scene_id'], 'acme:carolyn') == folder.resolve()
        assert folder.is_dir()
    finally:
        if folder.is_dir():
            folder.rmdir()


def test_the_routes_a_package_may_work_on_are_the_ones_served_and_not_blocked(desk):
    store = desk('automatic', blocked_senders=['mallory'], blocked_groups=['trouble'])
    channels = Channels(controller(store))
    for body in (event('dana', 'tribe'), event('mallory'), event('carolyn')):
        try:
            admit(store, body)
        except Denied:
            pass
    store.config['channels']['acme']['routes']['auto-group-trouble'] = listed_route('acme', 'trouble', 'zed')
    served = {row['route_id']: row['conversation'] for row in channels.routes('acme')['routes']}
    assert served == {'crew': {'type': 'group', 'id': 'crew'}, 'auto-group-tribe': {'type': 'group', 'id': 'tribe'},
                      'auto-dm-carolyn': {'type': 'dm', 'id': 'carolyn'}}


def test_a_line_sent_before_the_member_left_does_not_bring_them_back(desk):
    store = desk('automatic')
    admit(store, event('dana', 'tribe'))
    leave = {'account_id': BOT, 'conversation': {'type': 'group', 'id': 'tribe'}, 'sender_id': 'dana',
             'event_id': 'n-1', 'occurred_at': '2026-10-29T10:00:00Z'}
    assert channel_admission.depart(controller(store), 'acme', leave) == {'status': 'ended'}
    before = {**event('dana', 'tribe'), 'occurred_at': '2026-10-29T09:59:59Z'}         # sent while still a member
    assert admit(store, before)[1] is None
    assert store.config['channels']['acme']['routes']['auto-group-tribe']['members']['dana'].get('ended_at')
    after = {**event('dana', 'tribe'), 'occurred_at': '2026-10-29T10:00:05Z'}
    assert admit(store, after)[1] == 'returned'


def test_a_package_drops_what_it_kept_when_the_core_starts_again(desk):
    store = desk('automatic')
    first, second = Channels(controller(store)), Channels(controller(store))
    ask = {'account_id': BOT, 'asks': [{'conversation': {'type': 'dm', 'id': 'carolyn'}}]}
    epoch = first.admission('acme', ask)['epoch']
    assert first.admission('acme', ask)['epoch'] == epoch and first.routes('acme')['epoch'] == epoch
    assert second.admission('acme', ask)['epoch'] != epoch


def test_the_real_kinds_say_which_of_them_may_be_open():
    from asuna.config import ROOT
    packages = ROOT / 'packages' / 'channels'
    channel_kinds.load([{'python': packages / folder / 'python', 'module': module} for folder, module in
                        (('qq-bot', 'qq_bot'), ('agent-line', 'agent_line'), ('dsh-peer', 'dsh_peer'))])
    assert [channel_kinds.open_admission(kind) for kind in ('qq', 'qqbot', 'agent', 'dsh')] == [True, True, False, False]


def test_an_action_queued_for_a_group_that_was_blocked_since_does_not_go_out(desk):
    from asuna import group_admin
    from asuna.records import artifacts as artifact_records
    store = desk('explicit')
    route = store.config['channels']['acme']['routes']['crew']
    row = {'_id': 'ga-1', 'kind': 'group_action', 'channel_id': 'acme', 'scene_id': route['scene_id'], 'scope_key': 'scene:x',
           'policy_epoch': 1, 'episode_id': 'ep-1', 'target': route['target'], 'admin': {'kind': 'mute'}, 'state': 'QUEUED',
           'created_at': '2026-10-29T10:00:00+00:00'}
    artifact_records.save(store, row, stream='ga-1')
    store.config['channels']['acme']['blocked_groups'] = ['crew']
    assert group_admin.claim(store, 'acme') is None
    assert artifact_records.get(store, 'ga-1')['state'] == 'FAILED'
    store.config['channels']['acme']['blocked_groups'] = []
    artifact_records.save(store, {**row, '_id': 'ga-2'}, stream='ga-2')
    assert group_admin.claim(store, 'acme')['publication_id'] == 'ga-2'


def test_the_mark_on_a_line_reaches_the_conversation_she_reads(world):
    from asuna.people import ADMITTED_WORDS, People
    scene = next(row for row in scene_records.all(world) if row.get('kind') == 'group')
    person = scene['members'][0]
    people = People(world)
    lines = {how: people.transcript(scene, {'_id': 'x', 'author': person, 'text': 'hi', 'scene_id': scene['_id'],
                                            'received_at': '2026-10-29T10:00:00+00:00', 'scene_seq': 3,
                                            'event': {'admitted': how} if how else {}}).splitlines()[0]
             for how in (None, 'new', 'returned')}
    assert ADMITTED_WORDS['new'] in lines['new'] and ADMITTED_WORDS['returned'] in lines['returned']
    assert not any(words in lines[None] for words in ADMITTED_WORDS.values())


def test_a_platform_kind_that_cannot_be_open_is_named_when_the_deployment_opens_it(desk):
    store = desk('automatic')
    assert channel_admission.closed_by_kind(store.config) == []          # acme declares it; a home line is meant to be closed
    channel_kinds.register(stand_in('old'))
    store.config['channels']['old'] = {'account_id': BOT, 'token': 'o' * 24, 'admission': 'automatic', 'routes': {}}
    try:
        assert channel_admission.closed_by_kind(store.config) == ['old']
    finally:
        channel_kinds._KINDS.pop('old', None)


def test_the_routes_come_a_page_at_a_time_in_order(desk):
    store = desk('automatic')
    channels = Channels(controller(store))
    for index in range(7):
        store.config['channels']['acme']['routes']['auto-dm-user%d' % index] = {
            'scene_id': 'x%d' % index, 'target': {'type': 'dm', 'id': 'user%d' % index}}
    seen, after = [], ''
    while True:
        page = channels.routes('acme', {'limit': ['3'], 'after': [after]})
        seen += [row['route_id'] for row in page['routes']]
        after = page['next']
        if not after:
            break
    assert seen == sorted(store.config['channels']['acme']['routes']) and len(seen) == 8
    for bad in ({'limit': ['0']}, {'limit': ['x']}, {'limit': ['1001']}):
        with pytest.raises(ValueError, match='INVALID_ROUTES_QUERY'):
            channels.routes('acme', bad)
