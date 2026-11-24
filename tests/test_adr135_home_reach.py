"""ADR-135 landing 9 (the closing step), on the fixture world in memory (test_adr087_step4's: dm-a is home, the owner
A's chat; g1 and g2 are outside groups): from home she can stop a task of any of her conversations, cancel a plan of
any of them (her rhythms excepted), and write a group's notes by the group's name. An outside turn, and a home turn a
note from outside opened, reach none of it: the plain sentence. Her review carries the task it is about."""
from types import SimpleNamespace

import pytest

from asuna import guard, notes, visibility
from asuna.records import plans as plan_records
from asuna.records import tasks as task_records
from asuna.role_tools import Refused
from asuna.tasks import TaskService
from test_adr087_step4 import her, turn  # noqa: F401  (her: a fixture)

PERSONA = 'P1'


@pytest.fixture
def reach(her):
    her.tools.coordinator.tasks = TaskService(her.store)
    her.tools.coordinator.collab = lambda *a, **k: None
    return her


def call(her, ep_id, name, args, n=0):
    return her.tools.call(ep_id, '%s:%d' % (ep_id, n), name, args)[0]


def denied(her, ep_id, name, args):
    with pytest.raises(Refused) as caught:
        call(her, ep_id, name, args)
    return caught.value


def outside_task(store, task_id='task-g1'):
    return task_records.save(store, {'_id': task_id, 'request_key': task_id, 'scene_id': 'g1', 'scope_key': 'scene:g1',
                                     'policy_epoch': 1, 'requester_id': 'B', 'state': 'RUNNING', 'intent_revision': 1,
                                     'fencing_token': 1, 'title': '造的', 'goal': '造的'}, stream=task_id)


def outside_plan(store, plan_id='plan-g1', kind='reconsider'):
    return plan_records.save(store, {'_id': plan_id, 'scene_id': 'g1', 'scope_key': 'scene:g1', 'policy_epoch': 1,
                                     'person_id': 'B', 'status': 'ACTIVE', 'kind': kind, 'intent': '造的：回头再看',
                                     'persona': PERSONA}, stream=plan_id)


def home(her, tools):
    return turn(her, tools, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE)


def outside(her, tools):
    return turn(her, tools, scene='g2', person='C', cls=visibility.PUBLIC)


def opened_from_outside(her, tools):
    """A home turn a note from g2 opened (it acts for g2; g1 is elsewhere)."""
    if not notes.get(her.store, 'note-reach'):
        notes.save(her.store, {'_id': 'note-reach', 'persona': PERSONA, 'from_scene': 'g2', 'from_class': visibility.PUBLIC,
                           'to_scene': 'dm-a', 'kind': 'home', 'text': '造的', 'trust': notes.UNTRUSTED, 'seen_in': [],
                               'created_at': '2026-09-24T04:58:00+00:00', 'mode': notes.WAKE, 'hop': 0},
                   stream='notes:' + PERSONA)
    return turn(her, tools, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE, kind='note',
                event={'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'note', 'note': {'id': 'note-reach'}})


STOP = {'do': 'stop', 'task': 'task-g1', 'why': '造的：不做了'}
CANCEL = {'do': 'cancel', 'plan_id': 'plan-g1'}
NOTES = {'doc': 'group_notes', 'group': None, 'do': 'append_section', 'heading': '造的', 'content': '造的：记一笔', 'why': '造的'}


def test_a_at_home_she_stops_a_task_of_another_conversation(reach):
    outside_task(reach.store)
    result = call(reach, home(reach, ['task.stop']), 'task', STOP)
    task = task_records.get(reach.store, 'task-g1')
    assert result['state'] == 'CANCELLED' and (task['state'], task['cancel_reason']) == ('CANCELLED', 'character_stop')


def test_b_at_home_she_cancels_a_plan_of_another_conversation_and_never_a_rhythm(reach):
    outside_plan(reach.store)
    call(reach, home(reach, ['plan']), 'plan', CANCEL)
    assert plan_records.get(reach.store, 'plan-g1')['status'] == 'CANCELLED'
    outside_plan(reach.store, 'plan-rhythm', kind='presence')
    refusal = denied(reach, home(reach, ['plan']), 'plan', {**CANCEL, 'plan_id': 'plan-rhythm'})
    assert list(refusal.codes) == ['PLAN_RHYTHM'] and plan_records.get(reach.store, 'plan-rhythm')['status'] == 'ACTIVE'


def test_c_at_home_she_writes_a_group_s_notes_by_its_name(reach):
    from asuna.documents import DocumentStore
    from asuna.group_admin import notes_slug
    from asuna.people import People
    from asuna.records import scenes as scene_records
    store = reach.store
    scene_records.next_seq(store, 'g1', name='造的群')    # a name of its own, as a named line writes it
    name = People(store, PERSONA).scene_title(scene_records.get(store, 'g1'))
    assert name == '群聊「造的群」'
    call(reach, home(reach, ['write_document']), 'write_document', {**NOTES, 'group': name})
    sections = (DocumentStore(store, PERSONA).read(notes_slug('g1'))[1] or {}).get('sections') or []
    assert [section['heading'] for section in sections] == ['造的']
    refusal = denied(reach, home(reach, ['write_document']), 'write_document', {**NOTES, 'group': '造的：没有这个群'})
    assert list(refusal.codes) == ['GROUP_UNKNOWN']


@pytest.mark.parametrize('where', [outside, opened_from_outside])
def test_none_of_it_reaches_from_outside_or_from_a_turn_a_note_from_outside_opened(reach, where):
    store = reach.store
    outside_task(store)
    outside_plan(store, 'plan-g1')
    from asuna.people import People
    name = People(store, PERSONA).scene_title(store.collection('scenes').get('g1'))
    for name_, args, tools in (('task', STOP, ['task.stop']), ('plan', CANCEL, ['plan']),
                               ('write_document', {**NOTES, 'group': name}, ['write_document'])):
        ep_id = where(reach, tools)
        refusal = denied(reach, ep_id, name_, args)
        # the plain sentence; a turn a note from outside opened may meet the home-authority row first
        assert str(refusal) == guard.NOT_DONE and refusal.codes[0] in ('not_listed', 'outside_turn'), (name_, refusal.codes)
    assert task_records.get(store, 'task-g1')['state'] == 'RUNNING'
    assert plan_records.get(store, 'plan-g1')['status'] == 'ACTIVE'


def test_her_review_carries_the_task_it_is_about(reach):
    store = reach.store
    task = outside_task(store, 'task-review')
    with pytest.raises(guard.TaskGuarded):
        guard.guard_task(store, task, 'sandbox_run', {'argv': ['python3', '-V']})
    since, before = guard.review_window(store, '今天')
    [item] = guard.review(store, PERSONA, since, before)['items']
    assert item['tried']['task_id'] == 'task-review'


def test_at_home_task_stop_is_offered_while_a_task_of_any_conversation_runs(reach):
    from asuna import role_tools
    store = reach.store
    ep = store.collection('episodes').get(home(reach, []))
    assert 'task.stop' not in role_tools.exposed(store, ep)
    outside_task(store)
    assert 'task.stop' in role_tools.exposed(store, ep)
    assert 'task.stop' not in role_tools.exposed(store, store.collection('episodes').get(outside(reach, [])))


def test_a_group_name_two_groups_share_is_refused(reach):
    store = reach.store
    from asuna.people import People
    titles = {People(store, PERSONA).scene_title(store.collection('scenes').get(g)) for g in ('g1', 'g2')}
    if len(titles) == 1:                                  # untitled groups read alike
        refusal = denied(reach, home(reach, ['write_document']), 'write_document', {**NOTES, 'group': titles.pop()})
        assert list(refusal.codes) == ['GROUP_AMBIGUOUS']
    else:
        pytest.skip('the fixture groups have names of their own')
