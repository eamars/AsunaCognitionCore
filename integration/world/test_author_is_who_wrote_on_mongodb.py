"""ADR-089 on MongoDB: a line's author is who wrote it. On an agent line, the agent is shown only what the owner wrote
there: never a due plan's or the program's line, never another line's (leak)."""
from types import SimpleNamespace

import pytest

from asuna.channels import Channels
from asuna.ingress import persist_input

pytestmark = pytest.mark.world                # `store` is the fixture world

SCENE = 'agent:home:dm:claude-code'
OTHER = 'agent:home:dm:other'


def plan_firing(key, scene='dm-a', person='A'):
    """A due plan as schedule.py queues it: a core notice, no channel envelope."""
    return {'event_id': 'schedule:' + key, 'scene_id': scene, 'person_id': person, 'adapter_id': 'scheduler',
            'episode_kind': 'scheduled', 'scheduled_plan_id': 'plan-' + key, 'scene_tick': True,
            'text': '你之前安排的计划「喝水」现在到期了。请重新判断是否继续；到期本身不是新授权或已完成的行动。'}


def said(store, key, text, scene='dm-a', person='A'):
    return persist_input(store, {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text})[0]


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


def test_an_agent_line_shows_the_agent_only_what_the_owner_wrote(store, tmp_path):
    with_lines(store, tmp_path)
    owner_id = store.config['chat']['person_id']
    store.raw.scenes.update_one({'_id': SCENE}, {'$push': {'members': owner_id}})
    persist_input(store, plan_firing('line', scene=SCENE, person=owner_id))
    said(store, 'web-1', '这条线上的事我也看着', scene=SCENE, person=owner_id)
    shown = Channels(SimpleNamespace(app=SimpleNamespace(store=store))).owner_lines('agent', 'claude-code')
    assert [item['text'] for item in shown] == ['这条线上的事我也看着']
