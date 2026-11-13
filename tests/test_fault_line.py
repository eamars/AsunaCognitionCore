"""Her line about a failed turn says what of it was lost (ADR-127 N1): the cause only through its table, what went out
and what was done by count and name, requested again and broken again said as such, and the inbox count left out
when it cannot be read. The records it reads are stand-ins.

ADR-128: a turn that fails its check is ended where every turn ends and told to the developer and to her (D3), with
her words for the cause (D2), and a failed hand-back goes down ADR-030's ladder instead of being run again (D1). On
the unit run's store holding the fixture world (conftest.py)."""
import pytest

from asuna import developer_inbox, faults, handover, ingress, role_tools, visibility, whose
from asuna.coordinator import Coordinator, ProtocolFailure
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import tasks as task_records
from asuna.tasks import TaskService
from asuna.records import episodes as episode_records
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records

ZONE = {'name': 'UTC'}


class Lines:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


@pytest.fixture
def turn(monkeypatch):
    made = {'sent': 0, 'calls': {}, 'unread': 3, 'marks': []}
    monkeypatch.setattr(message_records, 'turn_parts', lambda store, ep, **kw: Lines(made['sent']))
    monkeypatch.setattr(episode_records, 'get', lambda store, ep, fields=None: {'tool_calls': made['calls']})

    def unread(store):
        if made['unread'] is None:
            raise RuntimeError('inbox unreadable')
        return [{}] * made['unread']
    monkeypatch.setattr(developer_inbox, 'unread', unread)
    monkeypatch.setattr('asuna.schedule_rules.line_stamp', lambda zone, at: '11-11 21:40')
    return made


def line(fault):
    return faults.her_line(None, {'fault': {'at': 'x', 'episode_id': 'ep-1', **fault}}, ZONE)


def test_nothing_went_out_nothing_done(turn):
    said = line({'cause': 'MALFORMED_RESPONSE'})
    assert said == ('你在这里 11-11 21:40 那一回合没跑成：是程序出了错（模型回来的工具参数不成形），不是你做错了什么。'
                    '那一拍你没说出口一个字、也没做成任何事——那件事到现在还是没做。'
                    '这条已经记进开发者收件箱；开发者收件箱里还有 3 条没被读过。')


def test_requested_again_and_broken_again(turn):
    said = line({'cause': 'MALFORMED_RESPONSE', 'retried': True})
    assert '程序为重请求过一次，第二次还是没跑成，没再自动重跑——那件事到现在还是没做。' in said
    assert '没说出口一个字' not in said


def test_what_went_out_and_what_was_done_by_name_only(turn):
    turn['sent'] = 2
    turn['calls'] = {'c3': {'tool': 'write_document', 'seq': 2, 'result': {}},
                     'c1': {'tool': 'speak', 'seq': 0, 'result': {}},
                     'c2': {'tool': 'remember', 'seq': 1, 'result': {}},
                     'c4': {'tool': 'visit', 'seq': 3, 'refused': 'no'},
                     'c5': {'tool': 'remember', 'seq': 4, 'result': {}}}
    said = line({'cause': 'TRANSPORT'})
    assert ('那一拍你发出去 2 句、做成了这些工具：remember、write_document。'
            '已经送出去的话不用重发；列出来的工具先核它落地没有，再决定要不要重做。') in said
    turn['calls'] = {}
    said = line({'cause': 'TRANSPORT'})
    assert '那一拍你发出去 2 句。已经送出去的话不用重发。' in said and '工具' not in said


def test_a_cause_not_in_the_table_is_never_shown_as_its_text(turn):
    assert '（出错类型未辨）' in line({'cause': 'RuntimeError'})
    assert '（出错类型未辨）' in line({'cause': '她写的半句话'})
    assert '（原因没记下来）' in line({})


def test_the_unread_count_is_left_out_when_it_cannot_be_read(turn):
    turn['unread'] = None
    said = line({'cause': 'TIMEOUT'})
    assert said.endswith('这条已经记进开发者收件箱。') and '0 条' not in said


def test_the_retried_mark_and_the_episode_are_kept_with_the_fault(monkeypatch):
    marks = []
    monkeypatch.setattr(developer_inbox, 'leave', lambda *a, **k: {'_id': 'n1'})
    monkeypatch.setattr(developer_inbox, 'bump', lambda store, row: None)
    monkeypatch.setattr(scene_records, 'note_fault', lambda store, scene, fault: marks.append(fault))
    store = type('S', (), {'config': {'chat': {'persona': 'p'}}})()
    ep = {'_id': 'ep-9', 'scene_id': 'dm-a', 'persona': 'p'}
    faults.turn_failed(store, ep, 'Traceback\nRuntimeError: ASUNA_RETRIED_ONCE\nMALFORMED_RESPONSE: Error: cut')
    faults.turn_failed(store, ep, 'Traceback\nRuntimeError: TRANSPORT: Error: down')
    assert [(m['cause'], m['episode_id'], m.get('retried')) for m in marks] == [
        ('MALFORMED_RESPONSE', 'ep-9', True), ('TRANSPORT', 'ep-9', None)]


def test_a_capped_failed_check_gets_her_second_word(monkeypatch):
    store = type('S', (), {'config': {'chat': {'persona': 'p'}}})()
    marks = []
    monkeypatch.setattr(developer_inbox, 'leave', lambda *a, **k: {'_id': 'n1'})
    monkeypatch.setattr(developer_inbox, 'bump', lambda store, row: None)
    monkeypatch.setattr(scene_records, 'note_fault', lambda store, scene, fault: marks.append(fault))
    spent = {str(n): {} for n in range(role_tools.CALLS_HARD + 1)}      # the last call ran: every later one ends
    for calls in (spent, dict(list(spent.items())[:-1])):
        faults.turn_failed(store, {'_id': 'ep-c', 'scene_id': 'dm-a', 'tool_calls': calls},
                           'INVALID_TURN_OUTPUT: {"problem": "x"}')
    faults.turn_failed(store, {'_id': 'ep-r', 'scene_id': 'dm-a', 'tool_calls': spent}, 'TRANSPORT: Error: down')
    assert [m.get('capped') for m in marks] == [True, None, None]


def test_her_words_for_a_failed_check(turn):
    assert '是程序出了错（收尾的检查三次没过），不是你做错了什么' in line({'cause': 'INVALID_TURN_OUTPUT'})
    assert '是程序出了错（工具次数已经用完，收尾过不去），不是你做错了什么' in line(
        {'cause': 'INVALID_TURN_OUTPUT', 'capped': True})


LOCAL, OWNER, PERSONA = 'local-dm', 'local-user', 'P1'
CUT = FakeTurn([], '', finish_reason='length')        # cut at the length limit, nothing said, nothing written


@pytest.fixture
def home(world, tmp_path, monkeypatch):
    from asuna import sandbox_backend
    monkeypatch.setattr(sandbox_backend, 'available', lambda config: True)
    world.config['chat'] = {**world.config['chat'], 'scene_id': LOCAL, 'person_id': OWNER, 'persona': PERSONA,
                            'workspace': str(tmp_path / 'local')}
    scene_records.save(world, {'_id': LOCAL, 'kind': 'dm', 'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1,
                               'sequence': 0, 'members': [OWNER]})
    return world


def notes(store):
    return [row for row in developer_inbox.unread(store) if (row.get('source') or {}).get('kind') == 'turn_failed']


def failed_rows(store, ep_id):
    return [row for row in store.collection('audit_events').find({'type': 'phase.failed'})
            if row['stream_id'] == ep_id]


def test_a_local_turn_cut_three_times_is_ended_and_told_where_it_ends(home):
    lane = FakeLane(home, [CUT] * 3)
    ep = Coordinator(home, lane).ingest({'event_id': 'e1', 'scene_id': LOCAL, 'person_id': OWNER, 'text': '在吗',
                                         'episode_kind': 'external'}, persona=PERSONA)
    assert ep['state'] == 'FAILED_PROTOCOL' and ep['failure'].startswith('INVALID_TURN_OUTPUT: ')
    assert len(lane.calls) == 3 and len(failed_rows(home, ep['_id'])) == 1
    assert [(n['source']['cause'], n.get('count')) for n in notes(home)] == [('INVALID_TURN_OUTPUT', 1)]
    fault = scene_records.get(home, LOCAL)['fault']
    assert (fault['cause'], fault['kind'], fault['episode_id'], fault.get('capped')) == (
        'INVALID_TURN_OUTPUT', 'external', ep['_id'], None)
    from asuna import schedule_rules
    said = faults.her_line(home, scene_records.get(home, LOCAL), schedule_rules.her_zone(home.config))
    assert '（收尾的检查三次没过）' in said and faults.REPORTED in said
    # Ended: advanced again, it runs nothing (the lane has no output left) and tells no one again.
    again = Coordinator(home, FakeLane(home, [])).advance(ep['_id'])
    assert again['state'] == 'FAILED_PROTOCOL' and len(failed_rows(home, ep['_id'])) == 1 and len(notes(home)) == 1


def asked_task(home, key='k1'):
    """A task she sent from the Web chat, as delegate makes it."""
    event = {'event_id': key, 'scene_id': LOCAL, 'person_id': OWNER, 'text': '帮我查一下', 'episode_kind': 'external',
             'adapter_id': 'local'}
    ingress.persist_input(home, event)
    ep_id = ingress.episode_id(event)
    scene = scene_records.get(home, LOCAL)
    asked = home.put('episodes', {
        '_id': ep_id, 'scene_id': LOCAL, 'scope_key': scene['scope_key'], 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': OWNER, 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': key, 'monologue_refs': [],
        'context': {}, 'manifest': {'session_class': visibility.session_class(home.config, home, scene, OWNER),
                                    'persona_revision': 1},
        'tool_calls': {}, 'whose': whose.of_turn(home, None, event)}, stream=ep_id)
    coordinator = Coordinator(home, None)
    coordinator.native_session_resolver = lambda proto: 'session-' + proto['scene_id']
    return coordinator, coordinator.delegate(asked, 'c-' + key, '标题', '交代')


def test_a_consult_that_never_answers_is_ended_told_and_answered_with_its_failure(home):
    coordinator, task = asked_task(home)
    made = task_records.get(home, task['_id'])
    task = home.put('tasks', {**made, 'state': 'RUNNING', 'fencing_token': 1, 'lease_expires_at': 4e9},
                    expected=made['revision'], stream=made['_id'])
    # Her calls spent (the 24th refused, the 25th runs and ends the turn), then she tries to answer: each answer is
    # past the hard line and runs nothing.
    spent = [('think', {'thought': '想第%d遍。' % n}) for n in range(1, role_tools.CALLS_HARD + 2)]
    answer = ('task', {'do': 'answer', 'answer': '用第一个。'})
    coordinator.character = FakeLane(home, [FakeTurn(spent, ''), FakeTurn([answer], ''), FakeTurn([answer], '')])
    with pytest.raises(ProtocolFailure) as caught:
        coordinator.consult(task, 'call-1', {'question': '用哪一个？'})
    assert str(caught.value).startswith('CONSULT_NOT_ANSWERED: INVALID_TURN_OUTPUT: ')
    consult = list(home.collection('episodes').find({'episode_kind': 'consult'}))
    assert [ep['state'] for ep in consult] == ['FAILED_PROTOCOL']
    calls = sorted(consult[0]['tool_calls'].values(), key=lambda call: call['seq'])
    assert [(call['tool'], call.get('code')) for call in calls[-2:]] == [('task', role_tools.CALLS_OVER)] * 2
    assert all('result' not in call for call in calls[-2:]) and not consult[0].get('answer')
    assert len(failed_rows(home, consult[0]['_id'])) == 1
    assert [(n['source']['cause'], n.get('count')) for n in notes(home)] == [('INVALID_TURN_OUTPUT', 1)]
    fault = scene_records.get(home, LOCAL)['fault']
    assert (fault['kind'], fault.get('capped')) == ('consult', True)
    from asuna import schedule_rules
    said = faults.her_line(home, scene_records.get(home, LOCAL), schedule_rules.her_zone(home.config))
    assert '（工具次数已经用完，收尾过不去）' in said and 'task' not in said     # an answer that never ran is no deed
    # The same call asked again runs no turn under the same key: it is answered with the failure again.
    coordinator.character = FakeLane(home, [])
    with pytest.raises(ProtocolFailure):
        coordinator.consult(task, 'call-1', {'question': '用哪一个？'})


def test_a_failed_hand_back_goes_down_the_ladder_and_is_never_run_again(home):
    coordinator, task = asked_task(home)
    done = task_records.get(home, task['_id'])
    home.put('tasks', {**done, 'state': 'RETURNED', 'feedback_state': 'READY'}, expected=done['revision'],
             stream=done['_id'])
    service, seen = TaskService(home), []
    service.on_collab = lambda task, entry: seen.append(entry)
    coordinator.character = FakeLane(home, [CUT] * 3)
    full = service.feedback(task_records.get(home, task['_id']), coordinator)
    assert full['state'] == 'FAILED_PROTOCOL'
    assert task_records.get(home, task['_id'])['feedback_state'] == 'READY'
    assert [(e['state'], e.get('cause'), e.get('error')) for e in seen if e['kind'] == 'handback'][-1] == (
        'missed', 'turn', 'INVALID_TURN_OUTPUT')
    # Handed back again, the failed turn is returned as it is: no new generation, no delivery.
    coordinator.character = FakeLane(home, [])
    again = service.feedback(task_records.get(home, task['_id']), coordinator, again=True)
    assert again['_id'] == full['_id'] and again['state'] == 'FAILED_PROTOCOL'
    assert not list(home.collection('audit_events').find({'type': 'feedback.continued'}))
    # The watchdog's ladder: the short version next, a new episode; when it fails too, give up.
    current = task_records.get(home, task['_id'])
    assert handover.next_step(home, current) == handover.SHORT and handover.cause(home, current) == 'turn'
    coordinator.character = FakeLane(home, [CUT] * 3)
    short = service.feedback(current, coordinator, short=True, again=True)
    assert short['_id'] != full['_id'] and short['state'] == 'FAILED_PROTOCOL'
    assert handover.next_step(home, task_records.get(home, task['_id'])) == handover.GIVE_UP
