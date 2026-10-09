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
    got, state = cli.poll(mine, 0)
    assert (got, state) == (['收到，我在。'], 'open')                                  # not the other line's answer
    row = served.store.db.messages.find_one({'scene_id': SCENE, 'direction': 'outbound'})
    assert row['delivery_state'] == 'DELIVERED'
    assert served.store.db.messages.find_one({'scene_id': OTHER, 'direction': 'outbound'})['delivery_state'] == 'QUEUED_EXTERNAL'
    assert cli.poll(theirs, 0) == (['你好。'], 'open')


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
    assert cli.poll(mine, 0) == ([], 'closed')                                     # her words wait
    lines.set_line(served.store, SCENE, closed=False)
    assert cli.poll(mine, 0) == (['收到，我在。'], 'open')
