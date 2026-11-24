"""ADR-134: an input that ends without a turn ends the turn a restart left behind; a turn cut by a stop keeps its input
for the resume, and a second cut ends it, told. On the unit run's store (conftest.py)."""
from asuna import audit, faults, unfinished
from asuna.records import episodes as episode_records
from asuna.records import messages as message_records

EP = 'ep-u'


def _input(store, state='PROCESSING'):
    message_records.save(store, {'_id': 'in-' + EP, 'scene_id': 'g', 'host_managed': True, 'ingress_state': state},
                         stream=EP)


def _turn(store, state):
    return episode_records.save(store, {'_id': EP, 'scene_id': 'g', 'scope_key': 'scene:g', 'source_event_id': 'ev',
                                        'episode_kind': 'external', 'persona': 'demo', 'state': state}, stream=EP)


def _input_row(store):
    return message_records.get(store, 'in-' + EP)


def test_an_input_held_after_a_restart_ends_the_turn_it_had_already_made(store):
    _input(store)
    _turn(store, 'ATTENDING')                       # written before the crash; the recheck holds it after the start
    ended = unfinished.without_turn(store, EP, 'PROACTIVE_HELD')
    assert ended['state'] == 'SUPPRESSED' and ended['ended_by'] == 'PROACTIVE_HELD'
    assert episode_records.get(store, EP)['state'] == 'SUPPRESSED'
    row = _input_row(store)
    assert (row['ingress_state'], row['result_state']) == ('COMPLETE', 'PROACTIVE_HELD')
    rows = audit.events(store, 'episode.ended_without_turn', stream=EP, by='seq').rows()
    assert [(r['payload']['ended_by'], r['payload']['was']) for r in rows] == [('PROACTIVE_HELD', 'ATTENDING')]


def test_an_input_with_no_turn_or_a_finished_one_only_completes(store):
    _input(store)
    assert unfinished.without_turn(store, EP, 'SEEN_IN_TURN') is None
    assert _input_row(store)['ingress_state'] == 'COMPLETE'
    _turn(store, 'COMMITTED')
    assert unfinished.without_turn(store, EP, 'ERRAND_INTERRUPTED') is None
    assert episode_records.get(store, EP)['state'] == 'COMMITTED'
    assert audit.events(store, 'episode.ended_without_turn', stream=EP, by='seq').rows() == []


def test_a_cut_turn_keeps_its_input_and_a_second_cut_ends_it_with_her_cause(store):
    _input(store)
    ep = _turn(store, 'TURN')
    ep, ended = unfinished.cut(store, ep, 'Traceback ...\nRuntimeError: stopping')
    assert not ended and (ep['state'], ep['cuts']) == ('INTERRUPTED', 1)
    assert _input_row(store)['ingress_state'] == 'PROCESSING'        # recover_inputs puts it back at the start
    ep = episode_records.save(store, {**ep, 'state': 'TURN'}, expected=ep['revision'], stream=EP)   # resumed
    ep, ended = unfinished.cut(store, ep, 'Traceback ...\nRuntimeError: stopping')
    assert ended and (ep['state'], ep['cuts']) == ('FAILED_RUNTIME', 2)
    assert _input_row(store)['ingress_state'] == 'FAILED'
    assert faults.cause(ep['failure']) == 'TURN_CUT_TWICE'
    assert faults.CAUSES['TURN_CUT_TWICE'] == '两次被停机截断，程序不再续它'


# ── D5: a cancelled task ends the turns it opened ──
def _task(store, task_id='task-d5'):
    from asuna.records import tasks as task_records
    return task_records.save(store, {'_id': task_id, 'request_key': task_id, 'scene_id': 'g', 'scope_key': 'scene:g',
                                     'policy_epoch': 1, 'requester_id': 'p', 'state': 'RUNNING', 'intent_revision': 1,
                                     'fencing_token': 1, 'title': '造的', 'goal': '造的'}, stream=task_id)


def _task_turn(store, ep_id, kind, state, task_id='task-d5'):
    return episode_records.save(store, {'_id': ep_id, 'scene_id': 'g', 'scope_key': 'scene:g', 'source_event_id': ep_id,
                                        'episode_kind': kind, 'persona': 'demo', 'state': state, 'task_id': task_id},
                                stream=ep_id)


def _ended(store, ep_id):
    rows = audit.events(store, 'episode.ended_without_turn', stream=ep_id, by='seq').rows()
    return episode_records.get(store, ep_id)['state'], [r['payload']['ended_by'] for r in rows]


def test_D5_her_stop_ends_the_consult_turn_the_task_had_open(store):
    from asuna.coordinator import RESUMABLE
    from asuna.tasks import TaskService
    _task(store)
    _task_turn(store, 'ep-consult', 'consult', 'TURN')
    TaskService(store).cancel('task-d5', reason='character_stop', person_id='p')
    state, ended_by = _ended(store, 'ep-consult')
    assert state not in RESUMABLE and ended_by == ['TASK_CANCELLED:character_stop']


def test_D5_a_time_up_turn_ends_too_but_never_the_one_that_cancelled(store):
    from asuna.tasks import TaskService
    _task(store)
    _task_turn(store, 'ep-time', 'task_time', 'PREPARED')
    _task_turn(store, 'ep-time-own', 'task_time', 'TURN')
    TaskService(store).cancel('task-d5', reason='character_stop', person_id='p', turn='ep-time-own')
    assert _ended(store, 'ep-time') == ('SUPPRESSED', ['TASK_CANCELLED:character_stop'])
    assert _ended(store, 'ep-time-own') == ('TURN', [])            # it is the turn stopping the task: it goes on


def test_D5_an_operator_cancel_ends_them_the_same_way(store):
    from asuna.tasks import TaskService
    _task(store)
    _task_turn(store, 'ep-consult', 'consult', 'INTERRUPTED')
    TaskService(store).cancel('task-d5', operator=True)
    assert _ended(store, 'ep-consult') == ('SUPPRESSED', ['TASK_CANCELLED:user_cancelled'])


def test_D5_a_finished_turn_and_another_task_s_turn_are_left_alone(store):
    from asuna.tasks import TaskService
    _task(store)
    _task(store, 'task-other')
    _task_turn(store, 'ep-done', 'consult', 'COMMITTED')
    _task_turn(store, 'ep-other', 'consult', 'TURN', task_id='task-other')
    TaskService(store).cancel('task-d5', operator=True)
    assert _ended(store, 'ep-done') == ('COMMITTED', []) and _ended(store, 'ep-other') == ('TURN', [])
