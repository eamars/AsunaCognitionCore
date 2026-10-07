"""ADR-021: her self-development comes in stages through the night, one at a time, never stacked."""
from datetime import datetime, timezone
from types import SimpleNamespace

from asuna import schedule as schedule_module
from asuna.rhythm import night_stage_block
from asuna.schedule import NIGHT_PLAN, ScheduleService, night_stage_busy


def service(store, offered):
    store.config['self_development'] = {'enabled': True}
    store.config['timezone'] = 'UTC'
    controller = SimpleNamespace(settings={'persona': 'demo', 'scene_id': 'dm-a', 'person_id': 'A'},
                                 offer_self_development=lambda event_id, **kw: offered.append((event_id, kw)))
    app = SimpleNamespace(store=store, config=store.config)
    svc = ScheduleService.__new__(ScheduleService)
    svc.app, svc.controller, svc.store = app, controller, store
    store.put('plans', {'_id': NIGHT_PLAN, 'kind': 'self_development', 'night': True, 'scene_id': 'dm-a',
                        'person_id': 'A', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'status': 'ACTIVE',
                        'rule': {'every_seconds': 600}})
    return svc


def at(monkeypatch, hour, minute=0):
    moment = datetime(2026, 10, 8, hour, minute, tzinfo=timezone.utc)
    monkeypatch.setattr(schedule_module, 'now', lambda: moment.isoformat())
    return moment


def test_a_stage_comes_inside_her_window_at_her_pace(store, monkeypatch):
    offered = []
    svc = service(store, offered)
    plan = lambda: store.db.plans.find_one({'_id': NIGHT_PLAN})
    at(monkeypatch, 12)
    assert svc._night_stage(plan(), 'occ-1') == 'OUTSIDE_NIGHT'          # default window 01:00–06:00
    at(monkeypatch, 1, 5)
    assert svc._night_stage(plan(), 'occ-2') == 'ENQUEUED'
    event_id, kw = offered[-1]
    assert event_id == 'self-development:night:occ-2' and kw['stage']['window'] == '01:00–06:00'
    at(monkeypatch, 1, 15)
    assert svc._night_stage(plan(), 'occ-3') == 'NOT_DUE'                 # 30 minutes apart by default
    at(monkeypatch, 1, 35)
    assert svc._night_stage(plan(), 'occ-4') == 'ENQUEUED'
    at(monkeypatch, 5, 40)
    plan_doc = plan()
    store.put('plans', {**plan_doc, 'last_stage_at': '2026-10-08T05:00:00+00:00'}, expected=plan_doc['revision'])
    assert svc._night_stage(plan(), 'occ-5') == 'ENQUEUED' and offered[-1][1]['stage']['last_stage']
    store.config['self_development']['night'] = False                       # the owner's switch
    at(monkeypatch, 2, 30)
    assert svc._night_stage(plan(), 'occ-6') == 'NIGHT_OFF'


def test_a_stage_never_stacks_on_open_work(store, monkeypatch):
    offered = []
    svc = service(store, offered)
    at(monkeypatch, 2)
    store.put('episodes', {'_id': 'ep-dev', 'episode_kind': 'self_development', 'state': 'WAITING_TASK',
                           'scene_id': 'dm-a'})
    store.put('tasks', {'_id': 'task-dev', 'episode_id': 'ep-dev', 'state': 'RUNNING'})
    assert night_stage_busy(store) == 'STAGE_BUSY'
    assert svc._night_stage(store.db.plans.find_one({'_id': NIGHT_PLAN}), 'occ') == 'STAGE_BUSY' and not offered
    task = store.db.tasks.find_one({'_id': 'task-dev'})
    store.put('tasks', {**task, 'state': 'RETURNED'}, expected=task['revision'])
    store.put('sink_receipts', {'_id': 'self-publish-x', 'kind': 'self_development_publish', 'state': 'HOST_RESTART_REQUIRED',
                                'project': 'demo', 'task_id': 'task-dev'})
    assert night_stage_busy(store) == 'PUBLISH_NOT_RUNNING'                 # waits until it runs
    receipt = store.db.sink_receipts.find_one({'_id': 'self-publish-x'})
    store.put('sink_receipts', {**receipt, 'state': 'ACTIVE'}, expected=receipt['revision'])
    assert night_stage_busy(store) is None


def test_she_reads_which_stage_of_the_night_this_is():
    block = night_stage_block({'window': '01:00–06:00', 'every_min': 30, 'last_stage': True})
    assert block['window'] == '01:00–06:00' and block['pace'] == '每 30 分钟一段' and block['last'] == '这是今晚最后一段'
    assert '一段一件事' in block['note'] and '宿主重启以后才生效' in block['note']
