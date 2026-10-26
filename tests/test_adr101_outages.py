"""ADR-101: what happened to her, in her own block. A worker that was down while the Host ran on is one outage row,
said in words with its cause; a planned restart names who marked it; her path names come from the table she is checked
against; every turn that does not ask for her thought leaves one row, and her week reads them in either mode."""
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from asuna import host_stops, local_roots, restarts, tools_week
from asuna.lanes import FakeLane, FakeTurn
from test_local_roots import TABLES

ZONE = {'tz': ZoneInfo('UTC'), 'name': 'UTC', 'source': 'config'}
MOMENT = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def span(**extra):
    return {'since': '2026-10-27T06:29:45.155Z', 'cause': 'start_failed:AutoReconnect', 'tries': 2, 'inside': 0, **extra}


# ---- 1. a worker that was down ------------------------------------------------------------------------------------

def test_a_span_handed_over_is_one_row_and_handing_it_over_again_writes_no_second(store):
    first = host_stops.worker_down(store, span(), back_at='2026-10-27T09:15:00+00:00')
    again = host_stops.worker_down(store, span(tries=5), back_at='2026-10-27T10:00:00+00:00')
    assert first['_id'] == again['_id'] and store.db.host_stops.count_documents({}) == 1
    row = store.db.host_stops.find_one()
    assert (row['how'], row['cause'], row['tries'], row['shown_at']) == ('worker_down', 'start_failed:AutoReconnect', 2, None)


def test_she_reads_it_in_words_with_its_cause_and_how_long(store):
    host_stops.worker_down(store, span(), back_at='2026-10-27T09:15:00+00:00')
    said = host_stops.block(store, ZONE, MOMENT)
    assert said['count'] == '过去一天里停了 1 次'
    assert said['stops'] == [{
        'what': '宿主一直在运行，但替你处理一切的那部分程序停了，没有马上起来：启动时出错（AutoReconnect），程序隔一阵自己重试，第 3 次起来了',
        'when': '最后确认还在运行约是 10/27 06:29，重新起来是 10/27 09:15，中间约 2 小时 45 分钟你没有运行'}]


@pytest.mark.parametrize('cause, tries, words', [
    ('exited:1', 1, '它自己退出了（退出码 1），程序把它重新拉起来'),
    ('exited:none', 3, '它自己退出了（没有退出码），程序把它重新拉起来，之后又有 2 次没起来'),
    ('unknown', 1, '为什么停的没记下来'),
    ('start_failed:x; drop table', 1, '为什么停的没记下来'),          # outside the closed list: not known, not passed on
    ('AutoReconnect: 192.0.2.10:27017: reset', 1, '为什么停的没记下来'),
])
def test_each_cause_kind_has_its_words_and_an_error_text_never_reaches_her(store, cause, tries, words):
    host_stops.worker_down(store, span(cause=cause, tries=tries), back_at='2026-10-27T09:15:00+00:00')
    what = host_stops.block(store, ZONE, MOMENT)['stops'][0]['what']
    assert what.endswith(words) and '192.0.2' not in what


def test_what_is_not_known_is_said_and_a_host_stop_inside_the_span_is_part_of_it(store):
    host_stops.worker_down(store, {'since': None, 'cause': 'unknown', 'tries': 1, 'inside': 2,
                                   'opened': '2026-10-27T07:00:00Z'}, back_at='2026-10-27T09:15:00+00:00')
    stop = host_stops.block(store, ZONE, MOMENT)['stops'][0]
    assert stop['when'] == '这一段从什么时候开始不知道（记录读坏了），重新起来是 10/27 09:15'
    assert stop['what'].endswith('为什么停的没记下来；这段时间里宿主也停过 2 次')


def test_a_cut_list_says_how_many_there_were_and_how_many_it_leaves_out(store):
    for hour in range(5):
        host_stops.record(store, MOMENT - timedelta(hours=10 - hour, minutes=5),
                          back_at=(MOMENT - timedelta(hours=10 - hour)).isoformat())
    said = host_stops.block(store, ZONE, MOMENT)
    assert said['count'] == '过去一天里停了 5 次' and said['not_listed'] == '更早的 2 次没有列出'
    assert len(said['stops']) == 3 and said['stops'][0]['when'].startswith('最后确认还在运行约是 10/27 05:55，重新起来是 10/27 06:00')


def test_rows_from_before_are_shown_for_their_day_only(store):
    """A row without `shown_at` (written before ADR-101) keeps the old rule: the day alone."""
    store.db.host_stops.insert_one({'_id': 'stop-old', 'how': 'killed', 'alive_until': '2026-10-20T09:00:00+00:00',
                                    'back_at': '2026-10-20T09:10:00+00:00', 'scope_key': 'operator', 'schema_version': 1})
    assert host_stops.block(store, ZONE, MOMENT) is None


def lease(planned=False, by=None, at=datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)):
    return SimpleNamespace(left_behind=at, planned=planned, planned_by=by)


def test_a_lease_left_behind_inside_an_open_span_is_the_same_outage(store):
    assert host_stops.left_behind(store, lease(), down=span()) is True
    assert store.db.host_stops.count_documents({}) == 0, 'no killed row: one outage, one row'
    assert host_stops.left_behind(store, lease(), down=None) is False
    assert store.db.host_stops.find_one()['how'] == 'killed', 'with no span open it is recorded as before'


def test_a_planned_stop_is_recorded_even_inside_a_span_and_keeps_who_marked_it(store):
    assert host_stops.left_behind(store, lease(planned=True, by='claude'), down=span()) is False
    row = store.db.host_stops.find_one()
    assert (row['how'], row['by']) == ('planned', 'claude')
    assert host_stops.block(store, ZONE, MOMENT) is None, 'not an outage'


# ---- 2. a planned restart ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('by, words', [('claude', '（claude 事先标好的）'), ('developer', '（developer 事先标好的）'),
                                       (None, '（谁标的没记下来）')])
def test_the_restart_block_names_who_marked_a_planned_launcher_start(store, tmp_path, by, words):
    import json
    (tmp_path / 'restart').mkdir()
    (tmp_path / 'restart' / 'last.json').write_text(json.dumps({
        'asked': 'launcher', 'down_at': '2026-10-27T09:50:47Z', 'back_at': '2026-10-27T09:51:15Z', 'result': 'running'}))
    plain = restarts.block(store, ZONE, MOMENT, root=tmp_path)['what']
    assert plain == '启动：从启动器开的，不是你要的重启'
    host_stops.record(store, datetime(2026, 10, 27, 9, 50, tzinfo=timezone.utc), back_at='2026-10-27T09:50:56+00:00',
                      planned=True, by=by)
    assert restarts.block(store, ZONE, MOMENT, root=tmp_path)['what'] == '启动：从启动器开的，是计划内的重启%s，不是你要的' % words


# ---- 3. her path names from the table -----------------------------------------------------------------------------

@pytest.mark.parametrize('host', sorted(TABLES))
def test_her_path_line_names_exactly_the_names_she_is_checked_against(monkeypatch, host):
    table = TABLES[host]
    monkeypatch.setattr(local_roots, 'TABLE', table)
    monkeypatch.setattr(local_roots, 'REFUSED', None)
    line = local_roots.context_line(True)
    listed = re.search('这台机器上的名字只有这些：(.*?)。', line).group(1)
    named = [entry.split(' ', 1)[0] for entry in listed.split('，')]
    assert sorted(named) == sorted(table.names)
    for name in named:                                   # each name it teaches is one the check accepts
        assert not [code for code, _ in table.problems('${ASUNA_%s}/x' % name, True) if code == 'PATH_NAME_UNKNOWN']
    for kind in ('TEMP', 'FS', 'DSH_HOME', 'DRIVE_X'):
        if kind not in table.names:
            assert kind + ' ' not in line


def test_with_no_table_the_line_says_nothing_can_be_handed_over(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', None)
    monkeypatch.setattr(local_roots, 'REFUSED', 'ROOT_TABLE_REFUSED: test')
    assert local_roots.context_line(True) == local_roots.NO_TABLE_LINE


# ---- 4. every turn that does not ask for her thought leaves one row ------------------------------------------------

class CarryingLane(FakeLane):
    """As FakeLane, but the call at `carry` (an index) carries the model's thinking, as the plugin's first call of a
    stage does; the others carry none. Calls arrive in order, so a call without thinking can come first."""
    def __init__(self, store, outputs, carry=None, thinking=None):
        super().__init__(store, outputs)
        self.carry, self.thinking = carry, thinking

    def _run_turn(self, operation, turn, tools, handler):
        def carrying(call_id, name, args):
            index = int(call_id.rsplit('#', 1)[1])
            return handler(call_id, name, args, **({'thinking': self.thinking} if index == self.carry else {}))
        value = super()._run_turn(operation, turn, tools, carrying)
        # A native lane reports the calls it made (FakeLane does only for a call that ends the turn).
        value.tool_calls = value.tool_calls or [{'type': 'tool-call', 'name': name, 'id': operation + '#' + str(i)}
                                                for i, (name, _) in enumerate(turn.calls)]
        return value


def rows(store, ep_id):
    return [(row['type'], (row.get('payload') or {}).get('why')) for row in store.db.audit_events.find(
        {'stream_id': ep_id, 'type': {'$in': ['thought.taken', 'thought.none']}})]


def turn(store, tmp_path, lane):
    from asuna.coordinator import Coordinator
    from test_local_images import world
    world(store, tmp_path)
    store.config['thoughts'] = 'thinking'                 # no turn asks for her thought
    return Coordinator(store, lane).ingest({'event_id': 'm1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})


CALLS = [('recall', {'query': '猫'}), ('recall', {'query': '狗'})]


def test_a_turn_whose_calls_carried_no_thinking_ends_with_one_not_carried_row(store, tmp_path):
    ep = turn(store, tmp_path, CarryingLane(store, [FakeTurn(CALLS, '在。')]))
    assert rows(store, ep['_id']) == [('thought.none', 'not_carried')]


def test_a_call_without_thinking_arriving_first_does_not_cost_the_call_that_carries_it(store, tmp_path):
    lane = CarryingLane(store, [FakeTurn(CALLS, '在。')], carry=1, thinking={'text': '想起那只猫。', 'redacted': False})
    ep = turn(store, tmp_path, lane)
    assert rows(store, ep['_id']) == [('thought.taken', None)], 'taken from the second call, and no not_carried after it'


def test_a_turn_with_no_call_keeps_its_own_row_and_gets_no_second(store, tmp_path):
    ep = turn(store, tmp_path, CarryingLane(store, [FakeTurn([], '在。')]))
    assert rows(store, ep['_id']) == [('thought.none', 'no_thinking')]


def test_her_week_reads_the_rows_in_either_mode_and_says_they_are_the_programs_capture(store):
    since, until = '2026-10-20T00:00:00+00:00', '2026-10-27T00:00:00+00:00'
    assert tools_week._thoughts(store, since, until) is None
    store.audit('ep-1', 'thought.none', {'why': 'not_carried'}, 'scene:x')
    store.db.audit_events.update_many({}, {'$set': {'occurred_at': '2026-10-25T00:00:00+00:00'}})
    text = tools_week._thoughts(store, since, until)
    assert '那一拍的调用没带上模型的思考 1' in text and tools_week.THOUGHTS_FROM in text


# ---- failure modes of the failure path ------------------------------------------------------------------------------

def test_the_worker_reads_the_plugins_span_and_never_needs_it_passed(store, tmp_path):
    """A JS and a Python of different versions run together (her core candidate restarts only the worker): the span is
    a file both read, not an argument an older worker would refuse."""
    assert host_stops.open_span(tmp_path) is None
    (tmp_path / host_stops.SPAN_FILE).write_text('{"since": "2026-10-27T06:29:45Z", "cause": "exited:1", "tries": 1}')
    assert host_stops.open_span(tmp_path)['cause'] == 'exited:1'
    assert host_stops.left_behind(store, lease(), host_stops.open_span(tmp_path)) is True
    assert store.db.host_stops.count_documents({}) == 0
    import inspect
    from asuna.native_worker import BusinessWorker
    assert 'down' not in inspect.signature(BusinessWorker.initialize).parameters


@pytest.mark.parametrize('content', [b'{not json', b'[1, 2]', b'{"since": 1}', b'{"cause": "x"' + b' ' * 70000 + b'}'],
                         ids=['torn', 'a list', 'no cause', 'past the size cap'])
def test_a_span_file_that_is_not_one_is_still_an_open_span_with_its_start_not_known(tmp_path, content):
    (tmp_path / host_stops.SPAN_FILE).write_bytes(content)
    assert host_stops.open_span(tmp_path) == {'since': None, 'cause': 'unknown'}


def test_a_clock_that_moved_between_the_two_moments_says_how_long_is_not_known(store):
    host_stops.worker_down(store, span(since='2026-10-27T10:00:00Z'), back_at='2026-10-27T09:15:00+00:00')
    when = host_stops.block(store, ZONE, MOMENT)['stops'][0]['when']
    assert when.endswith('中间多久不知道（时钟对不上）')


def test_a_mount_point_by_index_is_not_called_a_drive_letter(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', TABLES['linux'])
    monkeypatch.setattr(local_roots, 'REFUSED', None)
    line = local_roots.context_line(True)
    assert 'DRIVE_1 第 1 个挂载的盘' in line and 'DRIVE_C C 盘' in line


def test_a_row_it_cannot_write_never_fails_her_turn(store, tmp_path, monkeypatch):
    lane = CarryingLane(store, [FakeTurn(CALLS, '在。')])
    real = store.audit
    def failing(stream, kind, *rest, **named):
        if kind == 'thought.none':
            raise RuntimeError('AutoReconnect: reset')
        return real(stream, kind, *rest, **named)
    monkeypatch.setattr(store, 'audit', failing)
    ep = turn(store, tmp_path, lane)
    assert ep['state'] in ('COMMITTED', 'SPEAK_ACCEPTED')


def test_a_stamp_it_cannot_write_leaves_the_stop_shown_again(store, monkeypatch):
    from asuna import faults
    row = host_stops.record(store, MOMENT - timedelta(hours=2), back_at=(MOMENT - timedelta(hours=1)).isoformat())
    monkeypatch.setattr(host_stops, 'shown', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('reset')))
    faults.told(store, {'scene_id': 'x', 'manifest': {'told': {'host_stops': [row['_id']]}}})
    assert store.db.host_stops.find_one({'_id': row['_id']})['shown_at'] is None
