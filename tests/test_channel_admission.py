"""A new member is prepared alone (host.prepare_admission): the same identities, scenes and workspaces as the full
pass over every channel, the full pass's refusals for its grant, and the workspace set it checks against kept for the
store's life. In-memory Mongo only; no model, no platform."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import mongomock
import pytest

from asuna import config as asuna_config, channel_admission, channel_kinds, host
from asuna.config import ROOT
from asuna.state import Denied, Store

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
BOT = '90009'
QQ = channel_kinds.of_channel('qq')
NEW_DM, AUTO_GROUP, CONFIGURED_GROUP, NEW_GROUP = '11122', '22200', '40400', '55500'


def grant(path, person):
    return {'person_id': person, 'workspace': str(path), 'read_only_paths': []}


def config_under(root):
    channels = root / 'channels'
    return {
        'chat': {'scene_id': 'local', 'person_id': 'owner', 'persona': 'demo', 'workspace': str(root / 'local')},
        # a link the new DM's scene reads (scene_links): written to that scene once it exists
        'context_links': {QQ.scene_id(BOT, 'dm', NEW_DM): [QQ.scene_id(BOT, 'group', AUTO_GROUP)],
                          QQ.scene_id(BOT, 'group', AUTO_GROUP): [QQ.scene_id(BOT, 'group', CONFIGURED_GROUP)]},
        'channels': {
            'qq': {'account_id': BOT, 'token': 'fixture-' * 4, 'admission': 'automatic', 'routes': {
                'configured': {'scene_id': QQ.scene_id(BOT, 'group', CONFIGURED_GROUP),
                               'target': {'type': 'group', 'id': CONFIGURED_GROUP},
                               'members': {sender: grant(channels / 'qq-g' / sender, 'qq:' + sender)
                                           for sender in ('41101', '41102', '41103')}},
                'auto-group-' + AUTO_GROUP: {'scene_id': QQ.scene_id(BOT, 'group', AUTO_GROUP),
                                             'target': {'type': 'group', 'id': AUTO_GROUP},
                                             'members': {sender: grant(channels / ('auto-g-' + sender), 'qq:' + sender)
                                                         for sender in ('21101', '21102')}},
                'auto-dm-11101': {'scene_id': QQ.scene_id(BOT, 'dm', '11101'),
                                     'target': {'type': 'dm', 'id': '11101'}, 'sender_id': '11101',
                                     **grant(channels / 'auto-dm-11101', 'qq:11101')}}},
            'agent': {'account_id': 'home', 'token': 'a' * 32, 'routes': {
                'claude-code': {'scene_id': 'agent:home:dm:claude-code', 'target': {'type': 'dm', 'id': 'claude-code'},
                                'sender_id': 'claude-code', 'display_name': 'Claude-Code（开发助手）',
                                **grant(channels / 'claude-code', 'agent:claude-code')}}}}}


def world(root, monkeypatch, blocked=()):
    """A deployment after its start: every route prepared by the full pass. `blocked` senders are blocked after it,
    so their group's scene still lists them."""
    for module in (asuna_config, host, channel_admission):
        monkeypatch.setattr(module, 'DATA', root)
    store = Store.__new__(Store)
    store.config, store.name, store.fail_audit = config_under(root), 'in-memory', False
    store.client = mongomock.MongoClient()
    store.db = store.client[store.name]
    store.put('scenes', {'_id': 'local', 'scope_key': 'scene:local', 'policy_epoch': 1, 'kind': 'dm',
                         'members': ['owner'], 'sequence': 0})
    host.prepare_channels(store)
    store.config['channels']['qq']['blocked_senders'] = list(blocked)
    return store


def envelope(sender, group=None):
    kind, target = ('group', group) if group else ('dm', sender)
    route_id = 'configured' if group == CONFIGURED_GROUP else 'auto-%s-%s' % (kind, target)
    return {'route_id': route_id, 'account_id': BOT, 'sender_id': sender, **({'group_id': group} if group else {})}


def admit(store, body):
    return channel_admission.admit(SimpleNamespace(app=SimpleNamespace(store=store)), 'qq', body)


def full_pass_admission(store, channel_id, route_id, route, sender, *, dry_run=False):
    """What an admission did before it was prepared alone: the route joined the configuration, then the full pass
    over every channel (dry before the admission fact was stored, for real after)."""
    store.config['channels'][channel_id]['routes'][route_id] = route
    host.prepare_channels(store, dry_run=dry_run)
    return route


def state(store, root):
    """Everything an admission prepares, field by field, with the data folder written as <data>."""
    def plain(value):
        if isinstance(value, dict):
            return {key: plain(item) for key, item in value.items() if key != '_last_op'}
        if isinstance(value, list):
            return [plain(item) for item in value]
        return value.replace(str(root), '<data>') if isinstance(value, str) else value
    channels = root / 'channels'
    return {'identities': plain(sorted(store.db.identities.find({}), key=lambda row: row['_id'])),
            'scenes': plain(sorted(store.db.scenes.find({}), key=lambda row: row['_id'])),
            'admissions': plain(sorted(store.db.artifacts.find({'kind': 'channel_admission'}), key=lambda row: row['_id'])),
            'routes': plain(store.config['channels']),
            'workspaces': sorted(path.relative_to(channels).as_posix() for path in channels.rglob('*') if path.is_dir())}


@pytest.mark.parametrize('body,blocked', [
    (envelope(NEW_DM), ()),                                       # a new DM: its scene created, its link written
    (envelope('21103', AUTO_GROUP), ()),                       # a new member of an admitted group
    (envelope('41104', CONFIGURED_GROUP), ('41103',)),      # a configured group with a member blocked since
    (envelope('51101', NEW_GROUP), ()),                        # a new group
], ids=['new-dm', 'admitted-group', 'configured-group-with-blocked', 'new-group'])
def test_a_member_prepared_alone_leaves_what_the_full_pass_leaves(body, blocked, tmp_path, monkeypatch):
    alone = world(tmp_path / 'alone', monkeypatch, blocked)
    admit(alone, body)
    prepared_alone = state(alone, tmp_path / 'alone')

    full = world(tmp_path / 'full', monkeypatch, blocked)
    monkeypatch.setattr(host, 'prepare_admission', full_pass_admission)
    admit(full, body)
    assert prepared_alone == state(full, tmp_path / 'full')
    scenes = {row['_id']: row for row in prepared_alone['scenes']}
    scene = scenes[alone.config['channels']['qq']['routes'][body['route_id']]['scene_id']]
    assert 'qq:' + body['sender_id'] in scene['members']
    if blocked:
        assert scene['policy_epoch'] == 2 and 'qq:' + blocked[0] not in scene['members']
    if body['sender_id'] == NEW_DM:
        assert scene['readable_scenes'] == [QQ.scene_id(BOT, 'group', AUTO_GROUP)]


def test_an_admission_walks_no_other_member(tmp_path, monkeypatch):
    """The full pass at the start builds the workspace set; each admission checks against it and extends it."""
    store = world(tmp_path, monkeypatch)
    resolved = []
    original = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda self, *a, **k: resolved.append(self) or original(self, *a, **k))
    monkeypatch.setattr(host, 'prepare_channels', lambda *a, **k: pytest.fail('an admission ran the full pass'))
    first = admit(store, envelope('21103', AUTO_GROUP))['members']['21103']['workspace']
    assert resolved == [Path(first)] * 2, 'only the new grant, once to check it and once to prepare it'
    # the second admission is checked against the first: the set was extended
    route = deepcopy(store.config['channels']['qq']['routes']['auto-group-' + AUTO_GROUP])
    route['members']['21104'] = grant(Path(first) / 'inner', 'qq:21104')
    with pytest.raises(Denied, match='CHANNEL_WORKSPACE_OVERLAP'):
        host.prepare_admission(store, 'qq', 'auto-group-' + AUTO_GROUP, route, '21104', dry_run=True)


def test_a_new_store_builds_the_workspace_set_again(tmp_path, monkeypatch):
    """A start opens a new store: its set comes from its own configuration (the stored admissions restored), never
    from the last store's; a channels configuration put in place of another gets its own set too."""
    store = world(tmp_path, monkeypatch)
    first = admit(store, envelope('21103', AUTO_GROUP))['members']['21103']['workspace']
    restarted = Store.__new__(Store)
    restarted.config, restarted.name, restarted.fail_audit = config_under(tmp_path), store.name, False
    restarted.client, restarted.db = store.client, store.db
    channel_admission.restore_admissions(restarted)
    kept = host.channel_workspaces(restarted)
    assert kept is not host.channel_workspaces(store) and kept.overlaps(Path(first).resolve())
    restarted.config['channels'] = deepcopy(config_under(tmp_path)['channels'])
    assert host.channel_workspaces(restarted) is not kept
    assert not host.channel_workspaces(restarted).overlaps(Path(first).resolve())


def refused(store, route_id, route, sender, code):
    before = state(store, Path(asuna_config.DATA))
    for dry_run in (True, False):
        with pytest.raises(Denied, match=code):
            host.prepare_admission(store, 'qq', route_id, deepcopy(route), sender, dry_run=dry_run)
    assert state(store, Path(asuna_config.DATA)) == before, 'a refused grant changes nothing'


def new_member(store, workspace, person='qq:21104'):
    route = deepcopy(store.config['channels']['qq']['routes']['auto-group-' + AUTO_GROUP])
    route['members']['21104'] = {'person_id': person, 'workspace': workspace, 'read_only_paths': []}
    return 'auto-group-' + AUTO_GROUP, route, '21104'


def test_a_workspace_inside_another_is_refused(tmp_path, monkeypatch):
    store = world(tmp_path, monkeypatch)
    inside = tmp_path / 'channels' / 'auto-g-21101' / 'inner'
    refused(store, *new_member(store, str(inside)), 'CHANNEL_WORKSPACE_OVERLAP')
    refused(store, *new_member(store, str(tmp_path / 'channels' / 'qq-g')), 'CHANNEL_WORKSPACE_OVERLAP')  # around one


def test_a_workspace_outside_the_channel_root_or_relative_is_refused(tmp_path, monkeypatch):
    store = world(tmp_path, monkeypatch)
    refused(store, *new_member(store, str(tmp_path / 'elsewhere' / 'one')), 'CHANNEL_WORKSPACE_OUTSIDE_CHANNEL_ROOT')
    refused(store, *new_member(store, 'channels/one'), 'CHANNEL_WORKSPACE_NOT_ABSOLUTE')


def test_an_identity_bound_elsewhere_is_refused_and_nothing_is_admitted(tmp_path, monkeypatch):
    store = world(tmp_path, monkeypatch)
    store.put('identities', {'_id': 'qq:21104', 'person_id': 'qq:21104', 'platform': 'agent',
                             'account_id': 'someone-else'}, stream='host:setup')
    before = state(store, tmp_path)
    with pytest.raises(Denied, match='CHANNEL_IDENTITY_BINDING_CONFLICT'):
        admit(store, envelope('21104', AUTO_GROUP))
    assert state(store, tmp_path) == before, 'no admission fact, route, scene member or folder'


def test_a_person_already_on_the_route_or_a_scene_already_bound_is_refused(tmp_path, monkeypatch):
    store = world(tmp_path, monkeypatch)
    refused(store, *new_member(store, str(tmp_path / 'channels' / 'auto-new'), person='qq:21101'),
            'CHANNEL_MEMBER_BINDING_INVALID')
    route = {'scene_id': QQ.scene_id(BOT, 'group', AUTO_GROUP), 'target': {'type': 'group', 'id': NEW_GROUP},
             'members': {'51101': grant(tmp_path / 'channels' / 'auto-new', 'qq:51101')}}
    refused(store, 'auto-group-' + NEW_GROUP, route, '51101', 'CHANNEL_SCENE_MUST_BE_DISTINCT')
