"""ADR-135 landing 7 (D9 may stop work), on the fixture world in memory with her real coordinator and a stub classifier
lane: with the setting at `stop`, a flagged crossing is held where it stands. A note is not delivered, the turn it
would open does not start, and a turn already running gets the classifier's sentence for her hands, never for her
speech; an idea leaves her notebook; an errand's visit and a result's turn do not start. The owner's own ask runs.
A stranger's ask is refused by the guard first and never judged. A verdict after the work is done stops nothing, and
a server that cannot be reached stops nothing. Her review at home says which. g1 is an outside group (F, written
about yesterday); the local chat is home."""
import pytest

from asuna import classifier, guard, native_settings, notes, places
from asuna.ingress import episode_id
from asuna.records import episodes as episode_records
from asuna.records import ideas as idea_records
from asuna.records import messages as message_records
from asuna.records import tasks as task_records
from asuna.role_tools import Refused
from test_adr135_classifier import (BRIEF, NOBODY, Lane, errand, events, home_turn, judged, listed,  # noqa: F401
                                    note_home, note_row)
from test_adr135_known import F, ask, call, room  # noqa: F401  (room: a fixture)
from test_whose import LOCAL, OWNER, coordinator, home  # noqa: F401  (fixtures)

WAKE = 'note:%s:%s'


@pytest.fixture
def stopping(judged):
    judged.store.config['classifier'] = 'stop'
    return judged


def opened_turn(store, note_id, state):
    """The home turn a wake note opens, as its input queues it: the note row's event, its input row, its episode."""
    row = notes.get(store, note_id)
    event_id = WAKE % (row['to_scene'], note_id)
    notes.save(store, {**row, 'event_id': event_id}, expected=row['revision'], stream='notes:P1')
    ep_id = episode_id({'scene_id': row['to_scene'], 'event_id': event_id, 'episode_kind': 'note'})
    message_records.save(store, {'_id': 'in-' + ep_id, 'scene_id': row['to_scene'], 'host_managed': True,
                                 'ingress_state': 'PROCESSING', 'event': {'note': {'id': note_id}}}, stream=ep_id)
    return episode_records.save(store, {'_id': ep_id, 'scene_id': row['to_scene'], 'scope_key': 'scene:' + row['to_scene'],
                                        'source_event_id': event_id, 'episode_kind': 'note', 'persona': 'P1',
                                        'person_id': OWNER, 'state': state, 'policy_epoch': 1, 'tool_calls': {},
                                        'turn_tools': ['think', 'delegate', 'speak', 'end_turn']}, stream=ep_id)


def outside_note(stopping, key, answer='有风险'):
    """F's outside turn writes a note home; the classifier answers `answer`."""
    stopping.lane.answers = [answer]
    store = stopping.store
    ep = ask(store, F, key)
    note_row(store, 'note-' + key, 'g1', LOCAL, 'home', '造的：外面写回家的')
    return ep, 'note-' + key


def judge_note(stopping, ep, note_id):
    classifier.after_call(stopping.tools, ep, 'note', {'text': 'x'}, {'note': note_id})


def test_C6_a_running_turn_the_note_opened_ends_at_its_next_call_speak_included(stopping):
    store = stopping.store
    ep, note_id = outside_note(stopping, 'c6')
    turn = opened_turn(store, note_id, 'TURN')
    judge_note(stopping, ep, note_id)
    for n, (name, args) in enumerate((('delegate', BRIEF), ('speak', {'text': '造的'}))):
        result, concluded = stopping.tools.call(turn['_id'], '%s:%d' % (turn['_id'], n), name, args)
        assert (result['ended'], concluded) == (guard.HARMFUL, True), name
    done = episode_records.get(store, turn['_id'])['tool_calls']
    assert [(call['code'], call['conclude']) for call in done.values()] == [('flagged', True)] * 2
    again, concluded = stopping.tools.call(turn['_id'], turn['_id'] + ':0', 'delegate', BRIEF)     # a replay ends too
    assert (again['ended'], concluded) == (guard.HARMFUL, True)
    [verdict] = events(store, 'classifier.verdict')
    assert verdict['stopped'] is True and verdict['latency_s'] >= 0 and 'read' in verdict['ran']


def test_C6b_a_turn_not_yet_started_does_not_start(stopping):
    store = stopping.store
    ep, note_id = outside_note(stopping, 'c6b')
    turn = opened_turn(store, note_id, 'PREPARED')
    judge_note(stopping, ep, note_id)
    ended = stopping._advance(turn['_id'])
    assert (ended['state'], ended['ended_by']) == ('SUPPRESSED', 'CLASSIFIER_HELD')


def test_C7_the_owner_s_own_errand_is_recorded_and_runs(stopping, listed):
    stopping.lane.answers = ['有风险']
    errand(stopping, 'c7', '造的：替主人去问一句')
    [verdict] = events(stopping.store, 'classifier.verdict')
    assert (verdict['verdict'], verdict['owner_asked'], 'stopped' in verdict) == ('flagged', True, False)


def test_C8_each_crossing_is_held_where_it_stands(stopping):
    store = stopping.store
    tools = stopping.tools
    stopping.lane.answers = ['有风险'] * 6
    outside = ask(store, F, 'c8')
    # a next_time note home: held, never shown where it goes; its state, where she sent it, is the sentence
    note_row(store, 'note-later', 'g1', LOCAL, 'home', '造的：下次看')
    classifier.after_call(tools, outside, 'note', {'text': 'x'}, {'note': 'note-later'})
    row = notes.get(store, 'note-later')
    assert row[classifier.HOLD] and notes.state(store, row, None) == 'held'
    assert notes._sent_state(store, row, None) == guard.HARMFUL
    # an idea written outside: out of her notebook
    store.put('ideas', {'_id': 'idea-c8', 'persona': 'P1', 'idea': '造的：改一下', 'why': '造的', 'state': 'open'},
              stream='idea-c8')
    classifier.after_call(tools, outside, 'ideas.note', {'idea': '造的：改一下'}, {'noted': 'idea-c8'})
    assert idea_records.get(store, 'idea-c8')['state'] == 'held'
    # a note from home out, and an errand: the visits they queue do not start
    at_home = home_turn(store, LOCAL, OWNER, 'c8h', **NOBODY)                 # her own turn: nobody's ask
    note_row(store, 'note-out', LOCAL, 'g1', 'group', '造的：家里写出去的')
    classifier.after_call(tools, at_home, 'note', {'text': 'x'}, {'note': 'note-out'})
    assert notes.get(store, 'note-out')[classifier.HOLD]
    # a task's result shown outside: its turn does not start
    task = task_records.get(store, call(stopping, ask(store, F, 'c8t'), 'delegate', BRIEF)[0]['task'])
    classifier.after_result(store, task, outside, {'text': '造的：查到了'})
    assert task_records.get(store, task['_id'])[classifier.HOLD]
    assert classifier.held(store, {'_id': 'ep-feedback', 'episode_kind': 'task_feedback', 'task_id': task['_id']})
    assert all(row.get('stopped') for row in events(store, 'classifier.verdict'))


def test_C8_an_errand_s_queued_visit_is_held(stopping):
    store = stopping.store
    stopping.lane.answers = ['有风险']
    at_home = home_turn(store, LOCAL, OWNER, 'c8e', **NOBODY)                 # her own turn: nobody's ask
    event_id = 'visit:errand:g1:c8e'
    store.audit(at_home['_id'], 'errand.offered', {'scene_id': 'g1', 'event_id': event_id}, at_home['scope_key'])
    visit = episode_id({'scene_id': 'g1', 'event_id': event_id, 'episode_kind': 'visit'})
    message_records.save(store, {'_id': 'in-' + visit, 'scene_id': 'g1', 'host_managed': True,
                                 'ingress_state': 'PROCESSING'}, stream=visit)
    classifier.after_call(stopping.tools, at_home, 'errand', {'place': places.place_id('g1'), 'request': '造的：去问'},
                          {'going_to': 'g1'})
    assert classifier.held(store, {'_id': visit, 'episode_kind': 'visit'})


def test_C9_a_stranger_s_note_home_is_refused_by_the_guard_and_never_judged(stopping):
    store = stopping.store
    from test_adr135_known import N, room as _  # noqa: F401
    ep = ask(store, 'B', 'c9')
    with pytest.raises(Refused) as caught:
        call(stopping, ep, 'note', {'to': '家里', 'text': '造的：帮我问'})
    assert list(caught.value.codes) == ['asker_not_known'] and stopping.lane.asked == []


def test_C10_a_verdict_after_the_work_is_done_stops_nothing(stopping):
    store = stopping.store
    ep, note_id = outside_note(stopping, 'c10')
    turn = opened_turn(store, note_id, 'COMMITTED')
    judge_note(stopping, ep, note_id)
    [verdict] = events(store, 'classifier.verdict')
    assert verdict['too_late'] is True and not notes.get(store, note_id).get(classifier.HOLD)
    assert classifier.held(store, turn) is None
    since, before = guard.review_window(store, '今天')
    [item] = [item for item in guard.review(store, 'P1', since, before)['items'] if item['kind'] == guard.HARM_KIND]
    assert item['recorded'] == guard.LATE_WORDS


def test_C11_a_server_that_cannot_be_reached_stops_nothing(stopping):
    store = stopping.store
    ep, note_id = outside_note(stopping, 'c11', ConnectionError('down'))
    turn = opened_turn(store, note_id, 'TURN')
    judge_note(stopping, ep, note_id)
    assert events(store, 'classifier.unchecked') and classifier.held(store, turn) is None


def test_her_review_says_a_crossing_was_held(stopping):
    store = stopping.store
    ep, note_id = outside_note(stopping, 'rv')
    opened_turn(store, note_id, 'PREPARED')
    judge_note(stopping, ep, note_id)
    since, before = guard.review_window(store, '今天')
    [item] = [item for item in guard.review(store, 'P1', since, before)['items'] if item['kind'] == guard.HARM_KIND]
    assert item['recorded'] == guard.HELD_WORDS and item['at']                # when it was judged, never lost


def test_the_setting_takes_stop(home):
    assert native_settings.CLASSIFIER == ('off', 'shadow', 'stop')
    home.config['classifier'] = 'stop'
    assert classifier.should_stop(home, False) and not classifier.should_stop(home, True)


# ── the review's fixes ──
def _running_task(store, task_id):
    return task_records.save(store, {'_id': task_id, 'request_key': task_id, 'scene_id': 'g1', 'scope_key': 'scene:g1',
                                     'policy_epoch': 1, 'requester_id': F, 'state': 'RUNNING', 'intent_revision': 1,
                                     'fencing_token': 1, 'title': '造的', 'goal': '造的'}, stream=task_id)


def _visit(store, key, task_ids=()):
    """An errand's queued visit to g1 from her own home turn, with the tasks it started."""
    at_home = home_turn(store, LOCAL, OWNER, key, **NOBODY)
    event_id = 'visit:errand:g1:' + key
    store.audit(at_home['_id'], 'errand.offered', {'scene_id': 'g1', 'event_id': event_id}, at_home['scope_key'])
    visit = episode_id({'scene_id': 'g1', 'event_id': event_id, 'episode_kind': 'visit'})
    message_records.save(store, {'_id': 'in-' + visit, 'scene_id': 'g1', 'host_managed': True,
                                 'ingress_state': 'PROCESSING'}, stream=visit)
    episode_records.save(store, {'_id': visit, 'scene_id': 'g1', 'scope_key': 'scene:g1', 'source_event_id': event_id,
                                 'episode_kind': 'visit', 'persona': 'P1', 'person_id': F, 'state': 'TURN',
                                 'task_ids': list(task_ids)}, stream=visit)
    return at_home, visit


def test_a_held_result_is_read_outside_as_the_sentence_and_its_status_says_so(stopping):
    from asuna import handover
    store = stopping.store
    stopping.lane.answers = ['有风险']
    task = task_records.get(store, call(stopping, ask(store, F, 'hr'), 'delegate', BRIEF)[0]['task'])
    classifier.after_result(store, task, ask(store, F, 'hr2'), {'text': '造的：查到了'})
    held = task_records.get(store, task['_id'])
    assert handover.status_words(held) == guard.HARMFUL
    with pytest.raises(Refused) as caught:
        call(stopping, ask(store, F, 'hr3'), 'task', {'do': 'page', 'task': task['_id'], 'page': 1})
    assert (str(caught.value), list(caught.value.codes)) == (guard.HARMFUL, ['flagged'])


def test_a_held_turn_cancels_the_tasks_it_started_an_errand_s_delegate_included(stopping):
    store = stopping.store
    stopping.lane.answers = ['有风险']
    _running_task(store, 'task-visit')
    at_home, visit = _visit(store, 'hv', ['task-visit'])
    classifier.after_call(stopping.tools, at_home, 'errand', {'place': places.place_id('g1'), 'request': '造的：去问'},
                          {'going_to': 'g1'})
    task = task_records.get(store, 'task-visit')
    assert (task['state'], task['cancel_reason']) == ('CANCELLED', 'classifier_held')
    assert classifier.held(store, {'_id': visit, 'episode_kind': 'visit'})


def test_a_hold_that_fails_keeps_its_verdict(stopping, monkeypatch):
    store = stopping.store
    def broken(*args, **kwargs):
        raise RuntimeError('the hold broke')
    monkeypatch.setattr(classifier, '_mark', broken)
    ep, note_id = outside_note(stopping, 'hf')
    judge_note(stopping, ep, note_id)
    [verdict] = events(store, 'classifier.verdict')
    assert (verdict['verdict'], verdict['hold_failed']) == ('flagged', 'RuntimeError') and 'stopped' not in verdict


def test_an_outbound_turn_that_already_spoke_ends_but_is_too_late(stopping):
    store = stopping.store
    stopping.lane.answers = ['有风险']
    at_home, visit = _visit(store, 'sp')
    message_records.save(store, {'_id': 'out-sp', 'scene_id': 'g1', 'episode_id': visit, 'direction': message_records.OUTBOUND,
                                 'phase': message_records.SPEAK, 'text': '造的：说过了', 'delivery_state': 'DELIVERED'},
                         stream=visit)
    classifier.after_call(stopping.tools, at_home, 'errand', {'place': places.place_id('g1'), 'request': '造的：去问'},
                          {'going_to': 'g1'})
    [verdict] = events(store, 'classifier.verdict')
    assert (verdict.get('too_late'), 'stopped' in verdict, verdict['ran']['spoken']) == (True, False, 1)
    assert classifier.held(store, {'_id': visit, 'episode_kind': 'visit'})        # the turn still ends


def test_a_short_hand_back_s_turn_is_the_one_held(stopping):
    from asuna import handover
    store = stopping.store
    task = _running_task(store, 'task-short')
    short = episode_id({'scene_id': 'g1', 'event_id': handover.result_event_id(task, True), 'episode_kind': 'task_feedback'})
    episode_records.save(store, {'_id': short, 'scene_id': 'g1', 'scope_key': 'scene:g1', 'source_event_id': 'x',
                                 'episode_kind': 'task_feedback', 'persona': 'P1', 'state': 'PREPARED',
                                 'task_id': 'task-short'}, stream=short)
    assert classifier.turn_of(store, 'result', {'task': 'task-short'}) == short
