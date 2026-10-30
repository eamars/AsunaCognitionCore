"""ADR-111: whose work a task is. One record, decided from stored rows when a turn opens and carried along results,
plans and errands, never across a note from outside; the development grant follows it; work for someone outside that
she takes on in a home conversation runs on the home line (the Web chat); in a group she may name whose request it is.
On the unit run's store holding the fixture world (conftest.py); the native scheduler and the session resolver are
recording stand-ins, and no model runs."""
import time
from types import SimpleNamespace

import pytest

from asuna import channel_kinds, ingress, notes, places, visibility, whose
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.people import People
from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.role_tools import Refused
from asuna.schedule import ScheduleService
from asuna.tasks import Executor, TaskService
from test_plan_zone_service import NativeStandIn

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
LINE, AGENT = 'agent:home:dm:claude-code', 'agent:claude-code'
LOCAL, OWNER = 'local-dm', 'local-user'
PERSONA = 'P1'
# The agent's own lines arrive on its route, which carries the narrow integration grant (integration.event_profile).
ON_LINE = {'channel': {'id': 'agent', 'target': {'type': 'dm', 'id': 'claude-code'}, 'account_id': 'home'}}
# The owner's own lines on the Web chat carry his integration grant (Chat.submit).
ON_CHAT = {'integration_profile': 'owner'}
TO_HER = {'group_context': {'wake_reason': 'mentioned_account'}}


@pytest.fixture
def home(world, tmp_path):
    """The fixture world with the Web chat, an agent line, a DM of the owner's, g1 and g2 on a channel (g2 a home
    group the owner is in), self-development and integration on."""
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
            'g2': {'scene_id': 'g2', 'target': {'type': 'group', 'id': 'g2'},
                   'members': {'A': member('A'), 'C': member('C'), 'O': member(OWNER)}}}},
        'agent': {'account_id': 'home', 'routes': {'claude-code': {
            'scene_id': LINE, 'sender_id': 'claude-code', 'target': {'type': 'dm', 'id': 'claude-code'},
            **member(AGENT)}}}}
    config['home_groups'] = ['g2']
    config['self_development'] = {'enabled': True}
    config['integration'] = {'enabled': True, 'scene_id': LOCAL, 'person_id': OWNER}
    for scene_id, kind, members in ((LOCAL, 'dm', [OWNER]), (LINE, 'dm', [AGENT, OWNER]), ('dm-owner', 'dm', [OWNER])):
        scene_records.save(world, {'_id': scene_id, 'kind': kind, 'scope_key': 'scene:' + scene_id, 'policy_epoch': 1,
                                   'sequence': 0, 'members': members})
    g2 = scene_records.get(world, 'g2')
    scene_records.save(world, {**g2, 'members': [*g2['members'], OWNER]}, expected=g2['revision'])
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


def result_turn(store, event):
    """The result turn a hand-back opens, as ingest records it."""
    event = {'intent_revision': 1, **event}
    ingress.persist_input(store, event)
    ep_id = ingress.episode_id(event)
    return store.put('episodes', {
        '_id': ep_id, 'scene_id': event['scene_id'], 'scope_key': 'scene:' + event['scene_id'], 'policy_epoch': 1,
        'persona': PERSONA, 'person_id': event['person_id'], 'episode_kind': 'task_feedback', 'state': 'TURN',
        'source_event_id': event['event_id'], 'task_id': event['task_id'], 'monologue_refs': [], 'context': {},
        'manifest': {'session_class': visibility.OWNER_PRIVATE, 'persona_revision': 1}, 'tool_calls': {},
        'whose': whose.of_turn(store, None, event)}, stream=ep_id)


def finished(store, task, text='做好了'):
    current = task_records.get(store, task['_id'])
    return task_records.save(store, {**current, 'state': 'DONE', 'feedback_state': 'READY', 'finished_at':
                                     current['created_at'], 'result': {'status': 'done', 'text': text}},
                             expected=current['revision'], stream=task['_id'])


def continued(store, task):
    return task_records.continuations(store, [task['_id']]).first()


def tools(store):
    rt = Coordinator(store, None).tools
    rt.collecting, rt.problems = False, []
    return rt


def test_whose_by_turn_kind(home):
    store = home
    assert whose.of_turn(store, None, {'event_id': 'e1', 'scene_id': 'g1', 'person_id': 'A'}) == \
        whose.record('words', 'g1', 'A')
    asked = turn(store, 'dm-a', 'A', 'e2')
    store.put('tasks', {'_id': 'task-new', 'request_key': 'task-new', 'scene_id': 'dm-a', 'requester_id': 'A',
                        'episode_id': asked['_id'], 'whose': asked['whose'], 'development_grant': False})
    # A result turn has its task's whose, and never earns more than the task stored.
    assert whose.of_turn(store, None, {'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'task_feedback',
                                       'task_id': 'task-new'}) == {**asked['whose'], 'earns': False}
    granted = turn(store, LOCAL, OWNER, 'e2b')
    store.put('tasks', {'_id': 'task-granted', 'request_key': 'task-granted', 'scene_id': LOCAL, 'requester_id': OWNER,
                        'episode_id': granted['_id'], 'whose': granted['whose'], 'development_grant': True})
    assert whose.of_turn(store, None, {'scene_id': LOCAL, 'person_id': OWNER, 'episode_kind': 'task_feedback',
                                       'task_id': 'task-granted'}) == granted['whose']
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
    assert earns('words', LINE, AGENT) and earns('standing', LOCAL, OWNER) and earns('words', 'g2', OWNER)
    assert not earns('words', 'g2', 'A')                       # a home group's other member
    assert not earns('words', 'g1', 'A') and not earns('words', 'g1', OWNER)      # a public group, the owner too
    assert not earns('words', LINE, 'someone-else')            # not that line's agent
    assert not earns('own', LOCAL, OWNER) and not earns('outside', 'g1')
    assert not earns('words', LOCAL, OWNER, earns=False)       # an old row that stored no grant
    # A continuation keeps its task's grant, never more: the owner's task made while self-development was off,
    # continued later from a turn with nothing to give, gets no development tools now that it is on. (His lines
    # here carry no integration grant, so that check, which compares profiles, lets the words through.)
    coordinator = Coordinator(store, None)
    store.config['self_development'] = {'enabled': False}
    asked = turn(store, LOCAL, OWNER, 'o1', text='整理一下笔记')
    plain = finished(store, coordinator.delegate(asked, 'c1', '整理', '整理笔记'))
    store.config['self_development'] = {'enabled': True}
    granted = finished(store, coordinator.delegate(turn(store, LOCAL, OWNER, 'o2'), 'c1', '改', '改一处'))
    assert plain['development_grant'] is False and granted['development_grant'] is True
    outside = finished(store, coordinator.delegate(asked, 'c2', '长文', '写一篇长文',
                                                   whose=whose.record('outside', 'g1', chosen=True)))
    for_outside = result_turn(store, {'event_id': 'r-out', 'scene_id': LOCAL, 'person_id': OWNER, 'text': '有了结果',
                                      'episode_kind': 'task_feedback', 'task_id': outside['_id']})
    assert for_outside['whose']['by'] == 'outside'
    coordinator.message_action(for_outside, 'm1', plain, '再加一段')
    assert continued(store, plain)['development_grant'] is False and continued(store, plain)['whose']['by'] == 'words'
    # A turn without the grant adds nothing to work that has it; the owner's own turn continues it with it.
    with pytest.raises(Refused):
        coordinator.message_action(for_outside, 'm2', granted, '再改一处')
    coordinator.message_action(turn(store, LOCAL, OWNER, 'o3'), 'm3', granted, '再改一处')
    assert continued(store, granted)['development_grant'] is True
    # Outside work carries no integration grant; the owner may still continue it from his own line, which carries his.
    coordinator.message_action(turn(store, LOCAL, OWNER, 'o4', **ON_CHAT), 'm4', outside, '换个开头')
    assert continued(store, outside)['integration_profile'] is None
    assert continued(store, outside)['development_grant'] is False


def test_outside_work_named_on_a_line_runs_home(home):
    store = home
    coordinator = Coordinator(store, None)
    coordinator.native_session_resolver = lambda proto: 'session-of-' + proto['scene_id']
    ep = turn(store, LINE, AGENT, 'e-line', text='帮群里那位客户写一篇长文', episode={'native_session_id': 'session-line'},
              **ON_LINE)
    own_task = coordinator.delegate(ep, 'c1', '查日志', '看一下这次发布的日志')
    assert (own_task['scene_id'], own_task['native_session_id']) == (LINE, 'session-line')
    assert own_task['development_grant'] is True and own_task['integration_profile'] == 'agent_home'
    named = whose.record('outside', 'g1', chosen=True)
    task = coordinator.delegate(ep, 'c2', '长文', '写一篇长文', whose=named)
    assert (task['scene_id'], task['requester_id'], task['scope_key'], task['policy_epoch']) == \
        (LOCAL, OWNER, 'scene:' + LOCAL, 1)
    assert task['native_session_id'] == 'session-of-' + LOCAL
    assert task['whose'] == named and task['development_grant'] is False and task['integration_profile'] is None
    assert whose.moved(task, ep) and not whose.moved(own_task, ep)
    # A resumed turn gets the task it made, deciding nothing again (the Web chat's session need not be at hand).
    coordinator.native_session_resolver = lambda proto: (_ for _ in ()).throw(RuntimeError('NOT_READY'))
    assert coordinator.delegate(ep, 'c2', '长文', '写一篇长文', whose=named)['_id'] == task['_id']

    # The action brain reads its input within the Web chat: the line's words are not its request.
    executor = Executor.__new__(Executor)
    executor.service, executor.broker = SimpleNamespace(store=store), SimpleNamespace(bind=lambda *args: None)
    executor._run_workspace = lambda task, binding, source, healthy: source
    assert executor._run_claimed(task, None, None) is None
    assert executor._run_claimed(own_task, None, None)['text'] == '帮群里那位客户写一篇长文'

    # Its consult is answered in the Web chat's session, with nothing of the line.
    running = task_records.save(store, {**task, 'state': 'RUNNING', 'lease_expires_at': time.time() + 600},
                                expected=task['revision'], stream=task['_id'])
    asked = {}
    coordinator.context = SimpleNamespace(prepare=lambda event, persona: asked.update(event=event) or
                                          (None, {}, {'system_ref': {'persona_doc_revision': 1}}))
    coordinator._turn = lambda ep: {**ep, 'state': 'COMMITTED', 'answer': '两千字'}
    assert coordinator.consult(running, 'q1', {'question': '写多长？'})['answer'] == '两千字'
    assert (asked['event']['scene_id'], asked['event']['person_id']) == (LOCAL, OWNER)
    assert asked['event']['trusted_context_events'][0]['original_input'] is None
    consulted = episode_records.of_source(store, 'q1', kind='consult')
    assert consulted['native_session_id'] == 'session-of-' + LOCAL and consulted['whose'] == named

    # Its result is handed back on the Web chat, in the task's session, with nothing of the line.
    handed = []
    TaskService(store).feedback(finished(store, running), SimpleNamespace(
        ingest=lambda event, persona: handed.append(event) or {'_id': 'ep-handed', 'state': 'COMMITTED'}))
    event = handed[0]
    assert (event['scene_id'], event['person_id'], event['native_session_id']) == (LOCAL, OWNER, 'session-of-' + LOCAL)
    assert event['trusted_context_events'][0]['original_input'] is None and 'integration_profile' not in event
    # One made when the Web chat had no session at hand is handed back in none, never in the line's.
    coordinator.native_session_resolver = None
    bare = coordinator.delegate(ep, 'c3', '短文', '写一篇短文', whose=named)
    TaskService(store).feedback(finished(store, bare), SimpleNamespace(
        ingest=lambda event, persona: handed.append(event) or {'_id': 'ep-bare', 'state': 'COMMITTED'}))
    assert bare['native_session_id'] is None and 'native_session_id' not in handed[1]

    # A plan made in its result turn lives there with the outside whose; a plan she makes at home that fires on a
    # line is her own there.
    back = result_turn(store, event)
    assert back['whose'] == named
    service = ScheduleService.__new__(ScheduleService)
    service.app, service.store, service.lane = SimpleNamespace(config=store.config, store=store), store, NativeStandIn()
    plan = service.create(back, {'intent': '明天再看一遍长文', 'after_seconds': 3600}, plan_id='plan-follow')
    assert (plan['scene_id'], plan['whose']) == (LOCAL, named)
    at_home = turn(store, LOCAL, OWNER, 'e-home', **ON_CHAT)
    line_plan = service.create(at_home, {'intent': '问一下那边', 'after_seconds': 3600}, plan_id='plan-line',
                               where={'scene_id': LINE, 'person_id': AGENT})
    assert line_plan['whose'] == whose.record('own', LINE, AGENT)
    # A plan of the owner's that this result turn rewrites is the outside work's from then on; a new time alone
    # keeps whose it is.
    his = service.create(at_home, {'intent': '周五提醒我', 'after_seconds': 7200}, plan_id='plan-his')
    assert his['whose'] == at_home['whose']
    assert service.update(back, 'plan-his', {'schedule': {'after_seconds': 5400}})['whose'] == at_home['whose']
    assert service.update(back, 'plan-his', {'intent': '周五把长文发过去'})['whose'] == named


def test_a_group_task_is_the_person_she_names(home):
    store = home
    g1 = scene_records.get(store, 'g1')
    shown = {'manifest': {'session_class': visibility.PUBLIC, 'persona_revision': 1, 'people_shown': {'A': [], 'B': []}}}
    ep = turn(store, 'g1', 'A', 'a-opens', **TO_HER, episode=shown)
    _, b_line = line(store, 'g1', 'B', 'b-asks', text='能帮我画张图吗', **TO_HER)
    line(store, 'g1', 'B', 'b-later', text='还有一件', **TO_HER)                # after her turn was prepared
    people = People(store, PERSONA)
    b_label, a_label = people.speaker(g1, 'B'), people.speaker(g1, 'A')
    rt = tools(store)
    said, _ = rt.tool_delegate(ep, 'c1', {'title': '画图', 'brief': '画一张图', 'for': b_label})
    task = task_records.get(store, said['task'])
    assert (task['scene_id'], task['requester_id'], task['raw_input_refs']) == ('g1', 'B', ['in-' + b_line])
    assert task['whose'] == whose.record('words', 'g1', 'B', chosen=True)
    assert said['for'] == whose.TASK['words'] % b_label + '；' + whose.RESULT_HERE
    assert rt._delegate_for(ep, a_label) is None                  # the opener is the turn's own answer
    with pytest.raises(Refused):
        rt._delegate_for(ep, '不在这回合的人')
    with pytest.raises(Refused):
        rt._delegate_for({**ep, 'errand': {'from': 'ep-home', 'scene_id': LOCAL}}, b_label)
    # Her result turn on B's task is B's; a task she hands over there takes that turn's input, not B's line again.
    back = result_turn(store, {'event_id': 'r-b', 'scene_id': 'g1', 'person_id': 'B', 'text': '有了结果',
                               'episode_kind': 'task_feedback', 'task_id': task['_id']})
    follow = Coordinator(store, None).delegate(back, 'c2', '再画一张', '照这个再画一张')
    assert (follow['requester_id'], follow['raw_input_refs']) == ('B', ['in-' + back['_id']])

    # In a home group she names a person in her turn, as in any group, or an outside place, as at home: the owner's
    # request in a turn someone else opened is his, with his grant; a home group is not an outside place.
    g2 = scene_records.get(store, 'g2')
    at_home = turn(store, 'g2', 'A', 'g2-opens', **TO_HER, episode={'manifest': {
        'session_class': visibility.OWNER_PRIVATE, 'persona_revision': 1, 'people_shown': {'A': [], OWNER: []}}})
    _, his_line = line(store, 'g2', OWNER, 'g2-owner', text='顺便把那段代码改一下', **TO_HER)
    said, _ = rt.tool_delegate(at_home, 'c1', {'title': '改代码', 'brief': '改一下那段代码',
                                               'for': people.speaker(g2, OWNER)})
    his = task_records.get(store, said['task'])
    assert (his['requester_id'], his['raw_input_refs'], his['development_grant']) == (OWNER, ['in-' + his_line], True)
    assert rt._delegate_for(at_home, places.place_id('g1')) == whose.record('outside', 'g1', chosen=True)
    sister = Coordinator(store, None).delegate(at_home, 'c2', '查', '查一下')
    assert sister['requester_id'] == 'A' and sister['development_grant'] is False
    with pytest.raises(Refused):
        rt._delegate_for(at_home, places.place_id('g2'))
    # At home `for` names an outside place; a home group is not one.
    line_ep = turn(store, LINE, AGENT, 'e-home')
    assert rt._delegate_for(line_ep, places.place_id('g1')) == whose.record('outside', 'g1', chosen=True)
    with pytest.raises(Refused):
        rt._delegate_for(line_ep, places.place_id('g2'))
