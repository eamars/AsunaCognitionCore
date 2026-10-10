"""Her restarts (ADR-034): the request desk, what she sees afterwards, and her tool."""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from queue import Queue
from types import SimpleNamespace

import pytest

from asuna import restarts

T0 = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)          # 14:00 in Pacific/Auckland


class Controller:
    def __init__(self):
        self.active = None
        self.active_task = None
        self.pending = Queue()
        self.task_queue = Queue()
        self.offered = []

    def offer_internal(self, kind, event_id, scene_id, person_id, text):
        self.offered.append((kind, event_id, scene_id, person_id, text))


def desk(store, tmp_path, clock):
    app = SimpleNamespace(store=store, config=store.config)
    return restarts.Desk(app, Controller(), root=tmp_path, zone='Pacific/Auckland', clock=lambda: clock[0])


def test_without_the_supervisor_nobody_takes_a_request(store, tmp_path, monkeypatch):
    monkeypatch.delenv('ASUNA_SUPERVISED', raising=False)
    d = desk(store, tmp_path, [T0])
    assert '没人接' in d.preview()['supervised']
    with pytest.raises(PermissionError, match='RESTART_NOT_SUPERVISED'):
        d.request('test')


def test_preview_says_what_a_restart_would_interrupt(store, tmp_path, monkeypatch):
    monkeypatch.setenv('ASUNA_SUPERVISED', '1')
    d = desk(store, tmp_path, [T0])
    assert d.preview()['interrupts'] == ['现在没有在跑的任务、排队的消息或马上要响的计划']
    store.db.tasks.insert_one({'_id': 'task-a', 'schema_version': 1, 'state': 'READY', 'title': '整理笔记'})
    store.db.plans.insert_one({'_id': 'plan-a', 'schema_version': 1, 'status': 'ACTIVE', 'intent': '看群', 'kind': None,
                               'next_fire_at': (T0 + timedelta(minutes=5)).isoformat()})
    store.db.plans.insert_one({'_id': 'plan-beat', 'schema_version': 1, 'status': 'ACTIVE', 'intent': '心跳', 'kind': 'presence',
                               'next_fire_at': (T0 + timedelta(minutes=5)).isoformat()})
    d.controller.pending.put('x')
    words = d.preview()['interrupts']
    assert any('排着队的任务 1 个' in w and '整理笔记' in w for w in words)
    assert any('排着队还没轮到的消息 1 条' in w for w in words)
    assert any('看群' in w for w in words) and not any('心跳' in w for w in words)


def test_quiet_waits_for_nothing_running_at_most_half_an_hour_and_a_time_waits_for_it(store, tmp_path, monkeypatch):
    monkeypatch.setenv('ASUNA_SUPERVISED', '1')
    clock = [T0]
    d = desk(store, tmp_path, clock)
    d.start = lambda: None                                            # no thread in a test
    d.request('JS change')
    d.controller.active = 'ep-busy'
    assert not d.due()
    clock[0] = T0 + timedelta(minutes=31)
    assert d.due()                                                    # waited long enough: goes anyway
    d.controller.active = None
    d.request('later', when='22:30')                                  # 09:30 UTC
    assert not d.due()
    clock[0] = datetime(2026, 10, 10, 9, 31, tzinfo=timezone.utc)
    assert d.due()
    d.request('now', when='now')
    d.controller.active = 'ep-busy'
    assert d.due()
    with pytest.raises(ValueError, match='RESTART_WHEN_INVALID'):
        d.request('x', when='tonight')
    assert d.cancel()['why'] == 'now' and not d.due()


def test_a_waiting_request_survives_a_restart_before_it_is_due(store, tmp_path, monkeypatch):
    monkeypatch.setenv('ASUNA_SUPERVISED', '1')
    monkeypatch.setattr(restarts.Desk, 'start', lambda self: None)
    d = desk(store, tmp_path, [T0])
    d.request('drill', when='04:30', drill=True)
    again = desk(store, tmp_path, [T0])                               # the Host was restarted by someone else
    assert again.pending == d.pending and again.pending['drill'] is True
    again.cancel()
    assert desk(store, tmp_path, [T0]).pending is None


def test_a_due_request_goes_to_the_supervisor_as_a_planned_stop(store, tmp_path, monkeypatch):
    monkeypatch.setenv('ASUNA_SUPERVISED', '1')
    marked = []
    from asuna import host_lease
    monkeypatch.setattr(host_lease, 'mark_planned', lambda config, by: marked.append(by) or True)
    d = desk(store, tmp_path, [T0])
    d.start = lambda: None
    d.request('publish needs it', drill=True)
    request = d.go()
    written = json.loads((tmp_path / 'restart' / 'request.json').read_text(encoding='utf-8'))
    assert written == request and written['asked'] == 'xiaoman' and written['drill'] is True
    assert written['interrupted'] and marked == ['xiaoman'] and d.pending is None
    assert store.db.audit_events.find_one({'type': 'restart.requested'})


def record(**fields):
    return {'id': 'restart-1', 'asked': 'xiaoman', 'why': 'JS change', 'down_at': (T0 - timedelta(minutes=3)).isoformat(),
            'back_at': T0.isoformat(), 'result': 'running', 'attempts': [{'rung': 0, 'ok': True}],
            'loaded': {'commit': 'abc1234', 'packages': {'@asuna/cognition-core': '12d47a38aaaa'}}, **fields}


def write(tmp_path, value):
    (tmp_path / 'restart').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'restart' / 'last.json').write_text(json.dumps(value), encoding='utf-8')


def test_her_home_turns_carry_the_supervisors_record_for_a_day(store, tmp_path):
    assert restarts.block(store, 'Pacific/Auckland', T0, root=tmp_path) is None
    write(tmp_path, record())
    seen = restarts.block(store, 'Pacific/Auckland', T0, root=tmp_path)
    assert seen['what'] == '重启：你自己要的' and seen['result'] == restarts.RESULT_WORDS['running']
    assert '中间约 3 分钟' in seen['when'] and seen['loaded']['commit'] == 'abc1234'
    assert 'qq_adapter' not in seen                                   # no adapter health file here
    store.db.tasks.insert_one({'_id': 'task-p', 'schema_version': 1, 'state': 'PAUSED', 'pause_reason': 'host_restart', 'title': '查资料',
                               'paused_at': (T0 - timedelta(minutes=2)).isoformat()})
    health = tmp_path / 'integration' / 'owner' / 'service-data'
    health.mkdir(parents=True)
    (health / 'health.json').write_text('{}', encoding='utf-8')
    alive = (T0 + timedelta(minutes=1)).timestamp()
    os.utime(health / 'health.json', (alive, alive))                  # the adapter wrote it after she came back
    later = restarts.block(store, 'Pacific/Auckland', T0, root=tmp_path)
    assert '查资料' in later['paused_tasks'][0] and later['qq_adapter'] == '起来了，在跑'
    assert restarts.block(store, 'Pacific/Auckland', T0 + timedelta(hours=25), root=tmp_path) is None


def test_a_fallback_calls_her_once(store, tmp_path):
    controller = Controller()
    write(tmp_path, record(result='running'))
    assert not restarts.call_after_fallback(store, controller, store.config, root=tmp_path, moment=T0)
    write(tmp_path, record(result='fell_back', reverted=['core: returned to the previous running version'],
                           attempts=[{'rung': 0, 'ok': False, 'reason': 'exited'}, {'rung': 1, 'ok': True}]))
    assert restarts.call_after_fallback(store, controller, store.config, root=tmp_path, moment=T0)
    assert not restarts.call_after_fallback(store, controller, store.config, root=tmp_path, moment=T0)
    [(kind, event_id, scene, person, text)] = controller.offered
    assert kind == 'presence' and event_id == 'presence:restart-restart-1' and scene == store.config['chat']['scene_id']
    assert '上一个能跑的版本' in text
    seen = restarts.block(store, 'Pacific/Auckland', T0, root=tmp_path)
    assert seen['result'] == restarts.RESULT_WORDS['fell_back'] and seen['reverted']


def test_at_home_she_previews_and_asks_with_the_tool(store, tmp_path, monkeypatch):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_engineering_m1 import event
    monkeypatch.setenv('ASUNA_SUPERVISED', '1')
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': 'dm-a', 'person_id': 'A'}
    d = desk(store, tmp_path, [T0])
    d.start = lambda: None
    monkeypatch.setattr(restarts, 'DESK', d)
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '新版要重启才生效。'}), ('restart', {'op': 'preview'}),
                                      ('restart', {'op': 'request', 'why': '前端改了', 'when': '04:30'})], '交给监工了。')])
    ep = Coordinator(store, lane).ingest(event('restart-1'), persona='P1')
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert 'restart' in lane.calls[0]['tools']
    results = [row for row in lane.tool_results if row[2] == 'restart']
    assert results[0][5] and results[1][5], results
    assert d.pending['why'] == '前端改了' and d.pending['when'] == '04:30'
