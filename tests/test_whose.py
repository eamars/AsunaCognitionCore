"""ADR-111: whose work a task is. One record, decided from stored rows when a turn opens and carried along results,
plans and errands, never across a note from outside. On the unit run's store holding the fixture world (conftest.py)."""
import pytest

from asuna import channel_kinds, ingress, notes, visibility, whose
from asuna.config import ROOT
from asuna.records import scenes as scene_records

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


@pytest.fixture
def coordinator(home, monkeypatch):
    """Her coordinator on the fixture world, the sandbox available, sessions named by their conversation."""
    from asuna import sandbox_backend
    from asuna.coordinator import Coordinator
    monkeypatch.setattr(sandbox_backend, 'available', lambda config: True)
    found = Coordinator(home, None)
    found.native_session_resolver = lambda proto: 'session-' + proto['scene_id']
    return found


def test_development_only_where_whose_earns_it(coordinator):
    store = coordinator.store
    earns = lambda found: whose.earns_development(store, found)
    assert earns(whose.record('words', LOCAL, OWNER)) and earns(whose.record('words', 'dm-owner', OWNER))
    assert earns(whose.record('words', LINE, AGENT)) and earns(whose.record('standing', LOCAL, OWNER))
    # A home group's other member, someone in a public group, her own work and outside work earn nothing.
    for found in (whose.record('words', 'g2', 'C'), whose.record('words', 'g1', 'A'), whose.record('own', LOCAL, OWNER),
                  whose.record('outside', 'g1', chosen=True)):
        assert not earns(found), found
    # A task gets the grant its whose earns, never the turn's; its continuation keeps the task's.
    asked = turn(store, LOCAL, OWNER, 'k1')
    task = coordinator.delegate(asked, 'c1', '标题', '交代')
    assert task['development_grant'] is True
    mine = coordinator.delegate(asked, 'c2', '标题', '交代', whose=whose.record('own', LOCAL, OWNER))
    assert mine['development_grant'] is False
    done = task_records_get(store, mine['_id'])
    store.put('tasks', {**done, 'state': 'RETURNED'}, expected=done['revision'])
    later = turn(store, LOCAL, OWNER, 'k2')
    said = coordinator.message_action(later, 'c3', task_records_get(store, mine['_id']), '再做一趟')
    continued = task_records_get(store, said['task'])
    assert continued['development_grant'] is False and continued['whose']['by'] == 'own'


def task_records_get(store, task_id):
    from asuna.records import tasks as task_records
    return task_records.get(store, task_id)


def test_outside_work_named_on_a_line_runs_home(coordinator):
    from asuna import places
    from asuna.records import messages as message_records
    from asuna.role_tools import Refused
    store = coordinator.store
    asked = turn(store, LINE, AGENT, 'k3')
    named = coordinator.tools._for(asked, places.place_id('g1'))
    assert named == whose.record('outside', 'g1', chosen=True)
    for wrong in (places.place_id('g2'), places.place_id(LOCAL), 'nowhere'):      # a home group, home, nothing
        with pytest.raises(Refused):
            coordinator.tools._for(asked, wrong)
    task = coordinator.delegate(asked, 'c4', '标题', '交代', whose=named)
    local = scene_records.get(store, LOCAL)
    assert (task['scene_id'], task['requester_id'], task['scope_key'], task['policy_epoch']) == \
        (LOCAL, OWNER, local['scope_key'], local['policy_epoch'])
    assert task['native_session_id'] == 'session-' + LOCAL
    assert task['development_grant'] is False and task['integration_profile'] is None
    assert whose.moved(task, asked)
    # Read within the task's scope (the executor, the consult), the line's words are not its request.
    assert message_records.get(store, task['raw_input_refs'][0], scope=task['scope_key'],
                               epoch=task['policy_epoch']) is None
    # A plan made in its result turn on the Web chat fires there with the same whose.
    assert whose.for_plan(store, task['whose'], LOCAL, OWNER) == task['whose']


def test_a_group_task_is_the_person_she_names(coordinator):
    from asuna.people import People
    from asuna.role_tools import Refused
    store = coordinator.store
    asked = turn(store, 'g1', 'A', 'k5', group_context={'wake_reason': 'mentioned_account'})
    _, waiting = line(store, 'g1', 'B', 'k6', text='帮我查一下', group_context={'wake_reason': 'mentioned_account'})
    asked = store.put('episodes', {**asked, 'manifest': {**asked['manifest'], 'people_shown': {'A': 1, 'B': 1}},
                                   'context': {'people_from_program': {'items': []}}},
                      expected=asked['revision'], stream=asked['_id'])
    label = People(store, PERSONA).speaker(scene_records.get(store, 'g1'), 'B')
    named = coordinator.tools._for(asked, label)
    assert named == whose.record('words', 'g1', 'B', chosen=True)
    with pytest.raises(Refused):
        coordinator.tools._for(asked, '不在这里的人')
    task = coordinator.delegate(asked, 'c5', '标题', '交代', whose=named)
    assert task['requester_id'] == 'B' and task['raw_input_refs'] == ['in-' + waiting]
    assert task['development_grant'] is False


def test_a_walk_cut_short_answers_own_and_says_so(home, monkeypatch):
    """A chain of results longer than STEPS_MOST answers `own` (earning nothing) and leaves an audit row."""
    store = home
    monkeypatch.setattr(whose, 'STEPS_MOST', 0)
    asked = turn(store, LOCAL, OWNER, 'w1')
    store.put('tasks', {'_id': 'task-w', 'request_key': 'task-w', 'scene_id': LOCAL, 'requester_id': OWNER,
                        'episode_id': asked['_id'], 'development_grant': True})
    found = whose.of_turn(store, None, {'event_id': 'w2', 'scene_id': LOCAL, 'person_id': OWNER,
                                        'episode_kind': 'task_feedback', 'task_id': 'task-w'}, steps=1)
    assert found['by'] == 'own' and not whose.earns_development(store, found)
    from asuna import audit
    assert audit.count(store, 'whose.walk_cut') == 1


def test_a_note_from_outside_has_one_door_home(home):
    """The owner (11-03): from a public conversation a note goes home only to the Web chat, her work channel; not his
    own direct chats, not an agent line, so a full day's cap never sends outside work to another private line."""
    homes = {sid for sid, kind in notes.targets(home, 'g1', visibility.PUBLIC).values() if kind == 'home'}
    assert homes == {LOCAL}
