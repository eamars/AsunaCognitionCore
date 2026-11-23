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
