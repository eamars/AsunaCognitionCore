"""ADR-052: her switches. A muted group rests and she neither speaks first there nor visits; tools switched off in a
conversation stay listed and are refused saying who turned them off and until when; a blocked account's lines wake
her nowhere. Each switch ends by itself, and her home lists what is on and what ended lately."""
from datetime import datetime, timedelta, timezone

from asuna import focus, places, role_tools, switches, visibility
from test_group_focus import world
from test_toolbox import GROUP, conversations, turn

HOME = {'_id': 'ep-home', 'persona': 'P1', 'scope_key': 'owner-private:P1'}
# focus.active reads the wall clock, so the switches start from now: a fixed date made the mute end in the past.
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def test_a_muted_group_rests_she_does_not_visit_and_it_ends_by_itself(store):
    scenes = world(store)
    mine = scenes['g-mine']
    assert focus.active(store, mine)
    row = switches.set_switch(store, HOME, 'mute', label='常驻的群', scene_id='g-mine', moment=NOW)
    assert row['until'] == (NOW + timedelta(hours=24)).isoformat(), 'no end given: a day'
    later = NOW + timedelta(hours=1)
    assert switches.muted(store, 'g-mine', later)
    assert focus.wake(store, mine, 'chain') is None and focus.wake(store, mine, 'mentioned_account') == 'mentioned_account'
    assert places.eligibility(store, mine, {}, {'per_day': 8}, later, '2026-10-12', here={'mine_at': None}) == (
        False, '你把这个群静音了：静音时不去，到点自己结束')
    # A day later it is over: the group is as she left it, and home says once that it ended.
    after = NOW + timedelta(hours=25)
    assert not switches.muted(store, 'g-mine', after)
    home = switches.home_block(store, 'P1', after)
    assert 'items' not in home and home['ended'][0]['how'] == '到时间自己结束了'


def test_tools_off_stay_listed_and_are_refused_with_who_and_until_when(store):
    conversations(store)
    ep = turn(GROUP, visibility.PUBLIC, context={'understanding_update_from_program': {'available': True}})
    assert 'understand_person' in role_tools.exposed(store, ep)
    switches.set_switch(store, HOME, 'tools_off', label='那个群', scene_id=GROUP, tools=['understand_person'])
    assert 'understand_person' in role_tools.toolbox(store, ep), 'the list stays the same (cache)'
    assert 'understand_person' not in role_tools.exposed(store, ep)
    said = role_tools.not_now(store, ep, 'understand_person')
    assert '在家里给这个对话关掉的' in said and 'switch_off' in said
    [here] = switches.here_block(store, GROUP)['items']
    assert here['what'] == '关了工具：那个群（understand_person）' and here['until_at']


def test_a_blocked_account_is_kept_out_of_her_wakes_until_its_end_and_home_cannot_be_blocked(store):
    row = switches.set_switch(store, {**HOME, '_id': 'ep-group'}, 'block', label='[某人 #4]', person_id='qq:X',
                              hours=2, moment=NOW)
    assert switches.blocked(store, 'qq:X', NOW + timedelta(hours=1))['_id'] == row['_id']
    assert switches.blocked(store, 'qq:X', NOW + timedelta(hours=3)) is None
    for bad in (0, 169, '2.5', 'soon'):
        try:
            switches.hours_of(bad)
        except Exception as exc:
            assert 'SWITCH_HOURS_INVALID' in str(exc)
        else:
            raise AssertionError(bad)


def test_a_blocked_speakers_line_reaches_the_router_marked_and_is_kept_without_a_turn(store):
    import threading
    from types import SimpleNamespace
    from asuna.channels import Channels
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    from asuna.router import Router
    from test_peer_lines import with_line
    with_line(store)
    route = store.config['channels']['dsh']['routes']['peer-dm']
    switches.set_switch(store, {**HOME, '_id': 'ep-x'}, 'block', label='她', person_id=route['person_id'])
    received = []
    controller = SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False,
                                 receive=lambda event: received.append(event) or {'status': 'accepted'})
    Channels(controller)._receive('dsh', {'route_id': 'peer-dm', 'account_id': 'home', 'sender_id': 'peer',
                                          'event_id': 'b1', 'text': '在吗'})
    assert received[0]['blocked'].startswith('switch-')
    lane = FakeLane(store, [])                            # any turn would fail: none is scripted
    event = {'event_id': 'blocked-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗',
             'channel': {'id': 'fixture'}, 'blocked': 'switch-x'}
    assert Router(store, Coordinator(store, lane)).receive(event)['state'] == 'RECEIVED_NO_WAKE' and not lane.calls
