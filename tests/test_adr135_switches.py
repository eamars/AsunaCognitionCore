"""ADR-135 landing 1 (D2, D3), on the fixture world in memory: a tool switched off in a conversation, by the owner's
`tasks` setting for its place or by her own switch, is not in that conversation's list while it is off, and the list
does not change between a switch's start and its end; the place set to off stays off when her switch ends; the block
listing her switches is built at home only; a `tasks` setting naming no conversation stops the start with the key
named. g1 is an outside group (A and B), dm-a the owner A's chat (home)."""
from datetime import timedelta
from itertools import count

import pytest

from asuna import clock, role_tools, switches, visibility
from asuna.records import tasks as task_records
from asuna.role_tools import Refused, RoleTools
from test_channel_admission import desk  # noqa: F401  (a fixture: a store holding an open-capable channel)

PERSONA = 'P1'
TASK_TOOLS = {'delegate', 'task'}
SERIAL = count(1)


@pytest.fixture
def her(world):
    from types import SimpleNamespace
    world.config['chat'] = {**(world.config.get('chat') or {}), 'scene_id': 'dm-a', 'person_id': 'A',
                            'persona': PERSONA}
    world.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'},
               'members': {'s-a': {'person_id': 'A'}, 's-b': {'person_id': 'B'}}}}}
    coordinator = SimpleNamespace(store=world, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator))


def group_turn(her, person='B'):
    """A turn in g1 as the program prepares one: its tools are what the conversation lists and this turn may use."""
    serial = next(SERIAL)
    ep = {'_id': 'ep-135-%d' % serial, 'scene_id': 'g1', 'scope_key': 'scene:g1', 'policy_epoch': 1,
          'persona': PERSONA, 'person_id': person, 'episode_kind': 'external', 'state': 'TURN',
          'source_event_id': 'evt-%d' % serial, 'monologue_refs': [],
          'context': {'action_capabilities_from_program': {'available': True}},
          'manifest': {'session_class': visibility.PUBLIC}, 'turn_thought': True, 'tool_calls': {}}
    ep['turn_tools'] = role_tools.exposed(her.store, ep)
    her.store.put('episodes', ep, stream=ep['_id'])
    return ep


def shown(her):
    """The tools the model is shown in g1 (role_tools.toolbox: the stage's `tools`, the request's tool list)."""
    return role_tools.toolbox(her.store, {'scene_id': 'g1', 'persona': PERSONA,
                                          'manifest': {'session_class': visibility.PUBLIC}})


def her_switch(her, tools, at, hours=2):
    return switches.set_switch(her.store, {'_id': 'ep-home', 'persona': PERSONA, 'scope_key': 'scene:dm-a'},
                               'tools_off', label='一群', scene_id='g1', tools=tools, hours=hours, moment=at)


def at(monkeypatch, moment):
    monkeypatch.setattr(clock, 'now', lambda: moment)


def test_L1_a_place_set_to_off_does_not_list_the_task_tools_and_a_call_makes_no_task(her):
    her.store.config['channels']['qq']['tasks'] = {'group:G1': 'off'}
    assert not TASK_TOOLS & set(shown(her))
    ep = group_turn(her)
    assert not any(name.split('.')[0] in TASK_TOOLS for name in ep['turn_tools'])
    with pytest.raises(Refused):
        her.tools.call(ep['_id'], ep['_id'] + ':0', 'delegate', {'title': '查一下', 'brief': '查一下天气'})
    assert task_records.of_episode(her.store, ep['_id']).rows() == []


def test_L2_a_place_not_set_keeps_the_task_tools(her):
    assert TASK_TOOLS <= set(shown(her))
    her.store.config['channels']['qq']['tasks'] = {'group:G1': 'on'}
    assert TASK_TOOLS <= set(shown(her)) and 'delegate' in group_turn(her)['turn_tools']


def test_L3_her_switch_takes_the_tool_out_of_the_list_until_it_ends_and_the_list_holds_still_meanwhile(her, monkeypatch):
    start = clock.now()
    at(monkeypatch, start)
    before = shown(her)
    her_switch(her, ['delegate'], start)
    during = []
    for minutes in (0, 1, 60, 119):
        at(monkeypatch, start + timedelta(minutes=minutes))
        during.append(shown(her))
        assert 'delegate' not in group_turn(her)['turn_tools']
    assert all(lists == during[0] for lists in during), 'the list does not change between turns while the switch is on'
    assert 'delegate' not in during[0] and during[0] == [name for name in before if name != 'delegate']
    at(monkeypatch, start + timedelta(hours=2, seconds=1))
    assert shown(her) == before


def test_L3_the_block_of_her_switches_is_built_at_home_only(her, monkeypatch):
    from test_her_clock import prepared
    her_switch(her, ['delegate'], clock.now())
    assert 'switches_from_program' not in prepared(her.store, monkeypatch, 'g1')
    assert 'switches_from_program' in prepared(her.store, monkeypatch, 'dm-a')


def test_L4_her_switch_ending_on_a_place_set_to_off_leaves_it_off(her, monkeypatch):
    her.store.config['channels']['qq']['tasks'] = {'group:G1': 'off'}
    start = clock.now()
    her_switch(her, ['delegate', 'task'], start)
    at(monkeypatch, start + timedelta(hours=2, seconds=1))
    assert not switches.on(her.store, scene_id='g1') and not TASK_TOOLS & set(shown(her))


def test_L5_a_tasks_key_naming_no_conversation_stops_the_start_with_the_key_named(desk):
    from asuna import host
    from test_channel_admission import admit, event
    store = desk('automatic')
    admit(store, event('carolyn', 'tribe'))                 # admitted places are places as much as listed ones
    admit(store, event('carolyn'))
    channel = store.config['channels']['acme']
    channel['tasks'] = {'group:crew': 'off', 'group:tribe': 'off', 'dm:carolyn': 'on'}
    host.prepare_channels(store, dry_run=True)
    for setting, words in (({'group:trbe': 'off'}, 'CHANNEL_TASKS_PLACE_UNKNOWN: channels.acme.tasks names "group:trbe"'),
                           ({'tribe': 'off'}, 'CHANNEL_TASKS_PLACE_UNKNOWN: channels.acme.tasks names "tribe"'),
                           ({'group:tribe': 'of'}, 'INVALID_CHANNEL_TASKS: channels.acme.tasks."group:tribe"'),
                           (['group:tribe'], 'INVALID_CHANNEL_TASKS: channels.acme.tasks is an object')):
        channel['tasks'] = setting
        with pytest.raises(ValueError) as raised:
            host.prepare_channels(store, dry_run=True)
        assert str(raised.value).startswith(words), setting
