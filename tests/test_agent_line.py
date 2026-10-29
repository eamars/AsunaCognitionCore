"""A line for coding agents (ADR-033): its own kind, one key per agent that opens only its line, and a CLI."""
import importlib.util


from asuna import channel_kinds
from asuna.config import ROOT

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
SCENE = 'agent:home:dm:claude-code'
OTHER = 'agent:home:dm:other'
spec = importlib.util.spec_from_file_location('agent_line_cli', ROOT / 'tools' / 'agent_line.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def route(name, scene, workspace):
    return {'person_id': 'agent:' + name, 'scene_id': scene, 'sender_id': name, 'display_name': name.title() + '（开发助手）',
            'target': {'type': 'dm', 'id': name}, 'workspace': str(workspace / name)}


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


