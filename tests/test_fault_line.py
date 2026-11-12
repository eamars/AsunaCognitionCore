"""Her line about a failed turn says what of it was lost (ADR-127 N1): the cause only through its table, what went out
and what was done by count and name, requested again and broken again said as such, and the inbox count left out
when it cannot be read. The records it reads are stand-ins."""
import pytest

from asuna import developer_inbox, faults
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
