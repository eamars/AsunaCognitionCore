"""ADR-135 landing 1 (D2, D3), on the fixture world in memory: a tool her switch turns off in a conversation is not in
that conversation's list while the switch is on, and the list does not change between turns meanwhile; a switch lasts
until she ends it unless she gives it hours, and the program refuses no open-ended switch; the block listing her
switches is built at home only. g1 is an outside group (A and B), dm-a the owner A's chat (home)."""
from datetime import timedelta
from itertools import count

import pytest

from asuna import clock, role_tools, switches, visibility
from asuna.records import tasks as task_records
from asuna.role_tools import Refused, RoleTools

PERSONA = 'P1'
SERIAL = count(1)
HOME = {'_id': 'ep-home', 'persona': PERSONA, 'scope_key': 'scene:dm-a'}


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


def her_switch(her, tools, at, hours=None):
    return switches.set_switch(her.store, HOME, 'tools_off', label='一群', scene_id='g1', tools=tools, hours=hours,
                               moment=at)


def at(monkeypatch, moment):
    monkeypatch.setattr(clock, 'now', lambda: moment)


def test_L1_her_switch_takes_delegate_out_of_the_list_and_a_call_makes_no_task(her):
    before = shown(her)
    her_switch(her, ['delegate'], clock.now())
    assert 'delegate' in before and 'delegate' not in shown(her)
    ep = group_turn(her)
    assert 'delegate' not in ep['turn_tools']
    with pytest.raises(Refused):
        her.tools.call(ep['_id'], ep['_id'] + ':0', 'delegate', {'title': '查一下', 'brief': '查一下天气'})
    assert task_records.of_episode(her.store, ep['_id']).rows() == []


def test_L2_with_no_switch_on_the_task_tools_are_listed(her):
    assert {'delegate', 'task'} <= set(shown(her)) and 'delegate' in group_turn(her)['turn_tools']


def test_L3_an_open_switch_holds_until_she_ends_it_and_one_with_hours_ends_at_its_time(her, monkeypatch):
    start = clock.now()
    at(monkeypatch, start)
    before = shown(her)
    row = her_switch(her, ['delegate'], start)
    assert 'until' not in row and switches.ends(row) == {'lasts': switches.OPEN}
    during = []
    for hours in (0, 1, 24, 24 * 30):
        at(monkeypatch, start + timedelta(hours=hours))
        during.append(shown(her))
        assert 'delegate' not in group_turn(her)['turn_tools']
    assert all(lists == during[0] for lists in during), 'the list does not change between turns while the switch is on'
    assert during[0] == [name for name in before if name != 'delegate']
    switches.clear(her.store, HOME, row['_id'])                      # set_policy's switch_off
    assert shown(her) == before
    timed = her_switch(her, ['delegate'], clock.now(), hours=2)
    assert 'delegate' not in shown(her) and switches.ends(timed) == {'until_at': timed['until']}
    at(monkeypatch, clock.now() + timedelta(hours=2, seconds=1))
    assert shown(her) == before


def test_L3_the_block_of_her_switches_is_built_at_home_only_and_says_an_open_one_has_no_end(her, monkeypatch):
    from test_her_clock import prepared
    her_switch(her, ['delegate'], clock.now())
    assert 'switches_from_program' not in prepared(her.store, monkeypatch, 'g1')
    block = prepared(her.store, monkeypatch, 'dm-a')['switches_from_program']
    assert [item.get('lasts') for item in block['items']] == [switches.OPEN] and 'until_at' not in block['items'][0]


def test_L6_the_program_refuses_no_open_ended_switch_and_no_long_one(her):
    start = clock.now()
    open_ended = her_switch(her, ['delegate'], start)
    long = switches.set_switch(her.store, HOME, 'mute', label='一群', scene_id='g1', hours=1000, moment=start)
    assert 'until' not in open_ended and clock.moment(long['until']) == start + timedelta(hours=1000)
    assert switches.hours_of(None) is None and switches.hours_of('1000') == 1000
    assert {row['_id'] for row in switches.on(her.store, scene_id='g1')} == {open_ended['_id'], long['_id']}
    her.tools.problems, her.tools.collecting, her.tools.checked = [], False, False      # a handler's call state
    blocked = her.tools._block(group_turn(her), None)               # watch's block, with no hours given
    assert blocked['lasts'] == switches.OPEN and 'until' not in switches.blocked(her.store, 'B')
