"""A line for coding agents (ADR-033): its own kind, one key per agent that opens only its line, and a CLI."""
import importlib.util
import json
import threading
from types import SimpleNamespace

import pytest

from asuna import channel_kinds, host, lines
from asuna.channels import ChannelServer, Channels, route_key
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
SCENE = 'agent:home:dm:claude-code'
OTHER = 'agent:home:dm:other'
spec = importlib.util.spec_from_file_location('agent_line_cli', ROOT / 'tools' / 'agent_line.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def route(name, scene, workspace):
    return {'person_id': 'agent:' + name, 'scene_id': scene, 'sender_id': name, 'display_name': name.title() + '（开发助手）',
            'target': {'type': 'dm', 'id': name}, 'workspace': str(workspace / name)}


def with_lines(store, tmp_path):
    store.config['channels'] = {'agent': {'account_id': 'home', 'token': 'a' * 32, 'routes': {
        'claude-code': route('claude-code', SCENE, tmp_path / 'channels'),
        'other': route('other', OTHER, tmp_path / 'channels')}}}
    for scene, person in ((SCENE, 'agent:claude-code'), (OTHER, 'agent:other')):
        store.put('scenes', {'_id': scene, 'scene_id': scene, 'kind': 'dm', 'members': [person],
                             'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'sequence': 0,
                             'channel_id': 'agent', 'channel_account_id': 'home'})


def test_each_home_place_has_its_own_working_folder_and_platform_places_are_not_home(tmp_path):
    """ADR-065: the Host makes her working copy in each home place's folder (her command writes only its own); the
    local chat, each agent line and the peer line are home, a platform place (the owner's QQ DM too) is not."""
    from asuna.grants import home_workspaces
    config = {'chat': {'person_id': 'owner', 'workspace': str(tmp_path / 'work' / 'local-user')}, 'channels': {
        'agent': {'account_id': 'home', 'routes': {'claude-code': route('claude-code', SCENE, tmp_path / 'channels'),
                                                   'other': route('other', OTHER, tmp_path / 'channels')}},
        'qq': {'account_id': '10001', 'routes': {'owner-dm': {
            'scene_id': 'qq:10001:dm:20002', 'target': {'type': 'dm', 'id': '20002'}, 'sender_id': '20002',
            'person_id': 'owner', 'workspace': str(tmp_path / 'channels' / 'qq-owner-dm')}}}}}
    assert home_workspaces(config) == [str((tmp_path / 'work' / 'local-user').resolve()),
                                       str((tmp_path / 'channels' / 'claude-code').resolve()),
                                       str((tmp_path / 'channels' / 'other').resolve())]
    assert home_workspaces({'chat': {}}) == []


def test_an_agent_line_is_a_trusted_home_line_of_its_own_kind():
    kind = channel_kinds.of_channel('agent')
    assert kind.HOME and kind.TEXT_ONLY and kind.PEER_LINE and kind.ROUTE_KEYS
    assert kind.person_id('claude-code') == 'agent:claude-code' and kind.scene_parts(SCENE) == ('home', 'dm', 'claude-code')
    assert channel_kinds.of(SCENE) is kind and channel_kinds.home(SCENE)


def test_setup_names_the_agent_and_writes_one_key_per_line(store, tmp_path, monkeypatch):
    with_lines(store, tmp_path)
    store.db.scenes.delete_many({'_id': {'$in': [SCENE, OTHER]}})
    monkeypatch.setattr(host, 'DATA', tmp_path)
    host.prepare_channels(store)
    assert store.db.identities.find_one({'_id': 'agent:claude-code'})['display_name'] == 'Claude-Code（开发助手）'
    names = host.write_route_keys(store.config, tmp_path)
    assert names == ['agent-claude-code.json', 'agent-other.json']
    line = json.loads((tmp_path / 'private' / 'route-keys' / 'agent-claude-code.json').read_text(encoding='utf-8'))
    assert line['key'] == route_key('a' * 32, 'claude-code') != route_key('a' * 32, 'other')
    assert line['url'].endswith('/v1/channels/agent') and line['sender_id'] == 'claude-code'
    del store.config['channels']['agent']['routes']['other']
    assert host.write_route_keys(store.config, tmp_path) == ['agent-claude-code.json']     # a removed line loses its key
    assert not (tmp_path / 'private' / 'route-keys' / 'agent-other.json').exists()


@pytest.fixture
def served(store, tmp_path):
    """The real channel server, with her turns run by the coordinator as a line arrives."""
    with_lines(store, tmp_path)
    store.config['channels']['qq'] = {'account_id': '10001', 'token': 'q' * 32, 'routes': {}}
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '是 Claude 在问。'})], '收到，我在。'),
                            FakeTurn([('think', {'thought': '另一个助手。'})], '你好。')])
    coordinator = Coordinator(store, lane)
    controller = SimpleNamespace(app=SimpleNamespace(store=store, evidence=SimpleNamespace(record=lambda *a: None)),
                                 stopping=threading.Event(), reconfiguring=False, ingress_lock=threading.Lock(),
                                 emit=lambda *a: None,
                                 receive=lambda event: {'status': 'accepted',
                                                        'episode_id': coordinator.ingest(event, persona='P1')['_id']})
    server = ChannelServer(Channels(controller), 0)
    port = server.server.server_port
    keys = {}
    for name in ('claude-code', 'other'):
        keys[name] = {'url': 'http://127.0.0.1:%d/v1/channels/agent' % port, 'route_id': name, 'account_id': 'home',
                      'sender_id': name, 'key': route_key('a' * 32, name)}
    try:
        yield SimpleNamespace(store=store, keys=keys, port=port)
    finally:
        controller.stopping.set()
        server.close()


def test_an_agent_talks_to_her_and_polls_only_its_own_line(served):
    mine, theirs = served.keys['claude-code'], served.keys['other']
    assert cli.send(mine, '我是 Claude，在吗')['status'] == 'accepted'
    assert cli.send(theirs, '我是另一个助手')['status'] == 'accepted'
    event = served.store.db.messages.find_one({'scene_id': SCENE, 'direction': 'inbound'})
    assert event['author'] == 'agent:claude-code' and event['text'] == '我是 Claude，在吗'
    got, state, owner = cli.poll(mine, 0)
    assert (got, state, owner) == (['收到，我在。'], 'open', [])                                  # not the other line's answer
    row = served.store.db.messages.find_one({'scene_id': SCENE, 'direction': 'outbound'})
    assert row['delivery_state'] == 'DELIVERED'
    assert served.store.db.messages.find_one({'scene_id': OTHER, 'direction': 'outbound'})['delivery_state'] == 'QUEUED_EXTERNAL'
    assert cli.poll(theirs, 0) == (['你好。'], 'open', [])


def test_a_route_key_opens_nothing_else(served):
    mine = served.keys['claude-code']
    with pytest.raises(SystemExit, match='403'):
        cli.call(mine, 'POST', '/events', {'route_id': 'other', 'account_id': 'home', 'sender_id': 'other',
                                           'event_id': 'x1', 'text': '冒名'})
    with pytest.raises(SystemExit, match='403'):
        cli.call(mine, 'POST', '/members', {'group_id': '1', 'members': []})
    cli.send(served.keys['other'], '我是另一个助手')
    other = served.store.db.messages.find_one({'scene_id': OTHER, 'direction': 'outbound'})
    served.store.db.messages.update_one({'_id': other['_id']}, {'$set': {'delivery_state': 'SENDING', 'attempt_id': 'a1'}})
    with pytest.raises(SystemExit, match='403'):                                   # nor confirm another line's words
        cli.call(mine, 'POST', '/outbox/%s/receipt' % other['_id'],
                 {'attempt_id': 'a1', 'status': 'platform_accepted', 'platform_message_id': 'p', 'response': {}})
    qq = {**mine, 'url': mine['url'].replace('/agent', '/qq'), 'key': route_key('q' * 32, 'claude-code')}
    with pytest.raises(SystemExit, match='403'):                                   # a kind without route keys
        cli.call(qq, 'GET', '/outbox?wait_seconds=0')


def test_when_she_closes_the_line_it_shuts_at_once(served):
    mine = served.keys['claude-code']
    cli.send(mine, '在吗')
    lines.set_line(served.store, SCENE, closed=True, choice='until_reopened')
    assert cli.send(mine, '还在吗')['status'] == 'line_closed'
    assert cli.poll(mine, 0) == ([], 'closed', [])                                     # her words wait
    lines.set_line(served.store, SCENE, closed=False)
    assert cli.poll(mine, 0) == (['收到，我在。'], 'open', [])


def test_an_agent_line_lists_read_image_though_it_carries_no_pictures(store, tmp_path):
    """At home a ref from any of her conversations is readable (owner 2026-10-11): the line's toolbox has the tool."""
    from asuna import role_tools
    with_lines(store, tmp_path)
    store.config.update(character={**store.config.get('character', {}), 'input_modalities': ['text', 'image']})
    ep = {'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'person_id': 'agent:claude-code', 'persona': 'P1',
          'manifest': {'session_class': role_tools.visibility.OWNER_PRIVATE}, 'context': {}}
    assert 'read_image' in role_tools.toolbox(store, ep)
    store.config['character']['input_modalities'] = ['text']
    assert 'read_image' not in role_tools.toolbox(store, ep), 'not when her model cannot see'


def test_the_owner_joins_a_line_without_starting_it_over(store, tmp_path, monkeypatch):
    """ADR-051: the owner is a member of each agent line; joining keeps the conversation (no new policy epoch)."""
    with_lines(store, tmp_path)
    monkeypatch.setattr(host, 'DATA', tmp_path)
    host.prepare_channels(store)
    owner = store.config['chat']['person_id']
    scene = store.db.scenes.find_one({'_id': SCENE})
    assert scene['members'] == ['agent:claude-code', owner] and scene['policy_epoch'] == 1
    assert channel_kinds.owner_joins(SCENE) and not channel_kinds.owner_joins('qq:1:dm:2')


def test_the_owner_on_a_line_is_his_own_voice_and_the_agent_sees_it(served, monkeypatch):
    """What the owner writes on a line from the Web is his, gets her answer there, and the line's agent sees it once."""
    from asuna.integration import owner_line
    store, mine = served.store, served.keys['claude-code']
    owner = store.config['chat']['person_id']
    store.db.scenes.update_one({'_id': SCENE}, {'$push': {'members': owner}})
    assert owner_line(store.config, SCENE, owner) and not owner_line(store.config, SCENE, 'agent:claude-code')
    assert not owner_line(store.config, store.config['chat']['scene_id'], owner)          # the home chat is not a line
    Coordinator(store, FakeLane(store, [FakeTurn([('think', {'thought': '主人来了。'})], '主人好。')])).ingest(
        {'event_id': 'web-1', 'scene_id': SCENE, 'person_id': owner, 'text': '这条线上的事我也看着'}, persona='P1')
    row = store.db.messages.find_one({'scene_id': SCENE, 'direction': 'inbound'})
    assert row['author'] == owner
    got, state, shown = cli.poll(mine, 0)
    assert (got, state) == (['主人好。'], 'open') and shown[0].endswith(' 这条线上的事我也看着') and shown[0].startswith('#')
    assert cli.poll(mine, 0) == ([], 'open', [])                                     # each owner line once
    lines.set_line(store, SCENE, closed=True, choice='until_reopened')
    store.db.messages.insert_one({'_id': 'in-web-2', 'schema_version': 1, 'scene_id': SCENE, 'direction': 'inbound', 'author': owner,
                                  'text': '还有一件', 'scene_seq': 99})
    assert cli.poll(mine, 0) == ([], 'closed', [])                                   # a closed line shows the agent nothing
    lines.set_line(store, SCENE, closed=False)
    assert cli.poll(mine, 0) == ([], 'open', ['#99 还有一件'])


def test_the_owner_on_a_line_works_in_his_own_workspace(store, tmp_path):
    """ADR-051 found live: his turn on a line looks up a workspace; he is no route member there, so it is his own."""
    from asuna.grants import workspace_grant
    with_lines(store, tmp_path)
    owner = store.config['chat']['person_id']
    assert workspace_grant(store.config, SCENE, owner) == store.config['chat']
    assert workspace_grant(store.config, SCENE, 'agent:claude-code')['person_id'] == 'agent:claude-code'
    with pytest.raises(Exception, match='WORKSPACE_NOT_AUTHORIZED'):
        workspace_grant(store.config, 'qq:1:dm:2', owner)
