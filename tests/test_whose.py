"""ADR-111: whose work a task is. One record, decided from stored rows when a turn opens and carried along results,
plans and errands, never across a note from outside; the development grant follows it; work for someone outside that
she takes on in a home conversation runs on the home line (the Web chat); in a group she may name whose request it is.
On the unit run's store holding the fixture world (conftest.py)."""
from types import SimpleNamespace

import pytest

from asuna import channel_kinds, ingress, notes, places, visibility, whose
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.people import People
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records
from asuna.role_tools import Refused, RoleTools

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
LINE, AGENT = 'agent:home:dm:claude-code', 'agent:claude-code'
LOCAL, OWNER = 'local-dm', 'local-user'
PERSONA = 'P1'


@pytest.fixture
def home(world, tmp_path):
    """The fixture world with the Web chat, an agent line, a DM of the owner's, g1 and g2 on a channel (g2 a home
    group), self-development on."""
    config = world.config
    config['chat'] = {**config['chat'], 'scene_id': LOCAL, 'person_id': OWNER, 'persona': PERSONA,
                      'workspace': str(tmp_path / 'local')}
    def member(person):
        return {'person_id': person, 'workspace': str(tmp_path / ('ws-' + person)), 'read_only_paths': []}
    config['channels'] = {
        'fixture': {'token': 'f' * 32, 'account_id': 'fixture-bot', 'routes': {
            'dm-a': {'scene_id': 'dm-a', 'sender_id': 'A', 'target': {'type': 'dm', 'id': 'A'}, **member('A')},
            'dm-owner': {'scene_id': 'dm-owner', 'sender_id': 'O', 'target': {'type': 'dm', 'id': 'O'}, **member(OWNER)},
            'g1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'g1'}, 'members': {'A': member('A'), 'B': member('B')}},
            'g2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'g2'}, 'members': {'A': member('A'), 'C': member('C')}}}},
        'agent': {'account_id': 'home', 'routes': {'claude-code': {
            'scene_id': LINE, 'sender_id': 'claude-code', 'target': {'type': 'dm', 'id': 'claude-code'},
            **member(AGENT)}}}}
    config['home_groups'] = ['g2']
    config['self_development'] = {'enabled': True}
    for scene_id, kind, members in ((LOCAL, 'dm', [OWNER]), (LINE, 'dm', [AGENT, OWNER]), ('dm-owner', 'dm', [OWNER])):
        scene_records.save(world, {'_id': scene_id, 'kind': kind, 'scope_key': 'scene:' + scene_id, 'policy_epoch': 1,
                                   'sequence': 0, 'members': members})
    return world


def line(store, scene_id, person_id, key, text='在吗', kind='external', **extra):
    """An input stored as ingress stores it; its episode id."""
    event = {'event_id': key, 'scene_id': scene_id, 'person_id': person_id, 'text': text, 'episode_kind': kind,
             'adapter_id': 'fixture', **extra}
    ingress.persist_input(store, event)
    return event, ingress.episode_id(event)


def turn(store, scene_id, person_id, key, **extra):
    """A turn of hers in a conversation, with the `whose` ingest records."""
    event, ep_id = line(store, scene_id, person_id, key, **{k: v for k, v in extra.items() if k != 'episode'})
    scene = scene_records.get(store, scene_id)
    cls = visibility.session_class(store.config, store, scene, person_id)
    return store.put('episodes', {
        '_id': ep_id, 'scene_id': scene_id, 'scope_key': scene['scope_key'], 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': person_id, 'episode_kind': event['episode_kind'], 'state': 'TURN', 'source_event_id': key,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': cls, 'persona_revision': 1},
        'tool_calls': {}, 'whose': whose.of_turn(store, None, event), **extra.get('episode', {})}, stream=ep_id)


def test_whose_by_turn_kind(home):
    store = home
    assert whose.of_turn(store, None, {'event_id': 'e1', 'scene_id': 'g1', 'person_id': 'A'}) == \
        whose.record('words', 'g1', 'A')
    asked = turn(store, 'dm-a', 'A', 'e2')
    store.put('tasks', {'_id': 'task-new', 'request_key': 'task-new', 'scene_id': 'dm-a', 'requester_id': 'A',
                        'episode_id': asked['_id'], 'whose': asked['whose'], 'development_grant': False})
    assert whose.of_turn(store, None, {'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'task_feedback',
                                       'task_id': 'task-new'}) == asked['whose']
    # A task made before ADR-111: read from the turn that made it, never earning more than it stored.
    store.put('tasks', {'_id': 'task-old', 'request_key': 'task-old', 'scene_id': LOCAL, 'requester_id': OWNER,
                        'episode_id': turn(store, LOCAL, OWNER, 'e3')['_id'],
                        'development_grant': False})
    old = whose.of_turn(store, None, {'scene_id': LOCAL, 'person_id': OWNER, 'episode_kind': 'task_feedback',
                                      'task_id': 'task-old'})
    assert old['by'] == 'words' and old['unrecorded'] and old['earns'] is False
    assert not whose.earns_development(store, old)
    # A plan made on an errand (home's whose, living in the destination) is her own where it fires.
    home_turn = turn(store, LOCAL, OWNER, 'e4')
    store.put('plans', {'_id': 'plan-old', 'scene_id': 'g1', 'person_id': 'A', 'source_episode_id': home_turn['_id']})
    assert whose.of_turn(store, None, {'scene_id': 'g1', 'person_id': 'A', 'episode_kind': 'scheduled',
                                       'scheduled_plan_id': 'plan-old'}) == whose.record('own', 'g1', 'A')
    # An errand carries home: the home turn's whose.
    errand = {'event_id': 'e5', 'scene_id': 'g1', 'person_id': 'A', 'episode_kind': 'visit',
              'visit': {'intent': 'errand', 'from': home_turn['_id']}}
    assert whose.of_turn(store, None, errand) == home_turn['whose']
    # A note from outside at home: the writing turn's own place; one written on an errand acts as that conversation;
    # a gone note acts for no one.
    writer = turn(store, 'g1', 'A', 'e6')
    errand_writer = turn(store, 'g1', 'A', 'e7', episode={'errand': {'from': home_turn['_id'], 'scene_id': LOCAL}})
    for note_id, from_episode in (('note-out', writer['_id']), ('note-errand', errand_writer['_id'])):
        store.put('notes', {'_id': note_id, 'from_episode': from_episode, 'from_scene': 'g1', 'from_class': 'public',
                            'trust': notes.UNTRUSTED, 'to_scene': LOCAL})
    store.put('notes', {'_id': 'note-home', 'from_episode': home_turn['_id'], 'from_scene': LINE, 'trust': notes.TRUSTED,
                        'to_scene': LOCAL})
    at_home = {'scene_id': LOCAL, 'person_id': OWNER, 'episode_kind': 'note'}
    assert whose.of_turn(store, None, {**at_home, 'note': {'id': 'note-out'}}) == writer['whose']
    assert whose.of_turn(store, None, {**at_home, 'note': {'id': 'note-errand'}}) == whose.record('own', 'g1', 'A')
    assert whose.of_turn(store, None, {**at_home, 'note': {'id': 'gone'}}) is None
    assert whose.of_turn(store, None, {**at_home, 'note': {'id': 'note-home'}}) == whose.record('own', LOCAL, OWNER)
    # An erased writer (no stored whose, no input) answers own where it was.
    store.put('episodes', {'_id': 'ep-erased', 'scene_id': 'g1', 'source_event_id': 'x', 'episode_kind': 'external'})
    store.put('notes', {'_id': 'note-erased', 'from_episode': 'ep-erased', 'trust': notes.UNTRUSTED, 'to_scene': LOCAL})
    assert whose.of_turn(store, None, {**at_home, 'note': {'id': 'note-erased'}}) == whose.record('own', 'g1', None)
    assert whose.of_turn(store, None, {'scene_id': 'g1', 'person_id': 'A', 'episode_kind': 'visit',
                                       'visit': {'intent': 'check_in'}}) == whose.record('own', 'g1', 'A')
    assert whose.of_turn(store, None, {'scene_id': LOCAL, 'person_id': OWNER,
                                       'episode_kind': 'self_development'}) == whose.record('standing', LOCAL, OWNER)
    assert whose.of_turn(store, None, {'scene_id': LOCAL, 'person_id': OWNER,
                                       'episode_kind': 'presence'}) == whose.record('own', LOCAL, OWNER)


def test_development_only_where_whose_earns_it(home):
    store = home
    earns = lambda *args, **extra: whose.earns_development(store, whose.record(*args, **extra))
    assert earns('words', LOCAL, OWNER) and earns('words', 'dm-owner', OWNER) and earns('words', LINE, OWNER)
    assert earns('words', LINE, AGENT) and earns('standing', LOCAL, OWNER)
    assert not earns('words', 'g2', 'A')                       # a home group's other member
    assert not earns('words', 'g1', 'A') and not earns('words', 'g1', OWNER)      # a public group, the owner too
    assert not earns('words', LINE, 'someone-else')            # not that line's agent
    assert not earns('own', LOCAL, OWNER) and not earns('outside', 'g1')
    assert not earns('words', LOCAL, OWNER, earns=False)       # an old row that stored no grant


def test_outside_work_named_on_a_line_runs_home(home):
    store = home
    coordinator = Coordinator(store, None)
    ep = turn(store, LINE, AGENT, 'e-line', text='帮群里那位客户写一篇长文')
    own_task = coordinator.delegate(ep, 'c1', '查日志', '看一下这次发布的日志')
    assert own_task['scene_id'] == LINE and own_task['development_grant'] is True     # the agent's, on its line
    named = whose.record('outside', 'g1', chosen=True)
    task = coordinator.delegate(ep, 'c2', '长文', '写一篇长文', whose=named)
    assert (task['scene_id'], task['requester_id'], task['scope_key']) == (LOCAL, OWNER, 'scene:' + LOCAL)
    assert task['whose'] == named and task['development_grant'] is False and task['integration_profile'] is None
    assert whose.moved(task, ep) and not whose.moved(own_task, ep)
    # Its input is the line's line, which no model-facing read inside the Web chat returns.
    assert message_records.get(store, task['raw_input_refs'][0], scope=task['scope_key'],
                               epoch=task['policy_epoch']) is None
    # Its follow-ups stay home: a plan made in its result turn on the Web chat keeps the outside whose; a plan she
    # makes at home that fires on a line is her own there.
    assert whose.for_plan(store, named, LOCAL, OWNER) == named
    assert whose.for_plan(store, whose.record('words', LOCAL, OWNER), LINE, AGENT) == whose.record('own', LINE, AGENT)


def tools(store):
    rt = RoleTools(SimpleNamespace(store=store))
    rt.collecting, rt.problems = False, []
    return rt


def test_a_group_task_is_the_person_she_names(home):
    store = home
    _, b_line = line(store, 'g1', 'B', 'b-asks', text='能帮我画张图吗')
    ep = turn(store, 'g1', 'A', 'a-opens', episode={'manifest': {'session_class': visibility.PUBLIC,
                                                                  'persona_revision': 1,
                                                                  'people_shown': {'A': [], 'B': []}}})
    label = People(store, PERSONA).speaker(scene_records.get(store, 'g1'), 'B')
    named = tools(store)._delegate_for(ep, label)
    assert named == whose.record('words', 'g1', 'B', chosen=True)
    with pytest.raises(Refused):
        tools(store)._delegate_for(ep, '不在这回合的人')
    task = Coordinator(store, None).delegate(ep, 'c1', '画图', '画一张图', whose=named)
    assert (task['scene_id'], task['requester_id'], task['raw_input_refs']) == ('g1', 'B', ['in-' + b_line])
    # At home `for` names an outside place; a home group is not one.
    home_ep = turn(store, LINE, AGENT, 'e-home')
    assert tools(store)._delegate_for(home_ep, places.place_id('g1')) == whose.record('outside', 'g1', chosen=True)
    with pytest.raises(Refused):
        tools(store)._delegate_for(home_ep, places.place_id('g2'))
