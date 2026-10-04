"""ADR-005 P3 宿主定向检查：一条计划只有一行、改期不多出第二个有效版本、取消不被复活。

配置入口沿用既有约定：ASUNA_P3_CONFIG（默认 config/local.json），文件缺失就直接报错。
只用固定授权库 asuna_v2_test_p3_host_20260924（ASUNA_P3_DATABASE 可换同等受限的库）：
操作员账号只有这一库读写权，随机库名会在 listCollections 就 Unauthorized；库内隔离靠
用例开头与结尾清空本套件写的集合。

原生定时那一侧用假 lane 顶掉（DSH 没起也能跑）：真验的是 plans 集合、真 CAS、审计与
给她看的投影。逻辑本身另有一份零依赖离线用例 tests/p3_schedule_cases.py（本机 36/36），
这里第一个用例就把它跑一遍，不许两套口径各自漂移。真群里\"她能不能听懂明天九点\"不在这份
检查里：那要 owner 真启用一个场景才知道。
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from asuna.config import load
from asuna.schedule import ScheduleService
from conftest import isolated_database, drop_database
from asuna.state import Denied, Store

import p2_summary_loop_cases as p2

CONFIG_PATH = os.environ.get('ASUNA_P3_CONFIG', 'config/local.json')
TEST_DATABASE = os.environ.get('ASUNA_P3_DATABASE', 'asuna_v2_test_p3_host_20260924')
CLEARED = ('identities', 'scenes', 'messages', 'memory_units', 'state_heads', 'state_revisions',
           'audit_events', 'plans', 'tasks', 'episodes')


class Lane:
    '''原生定时替身：只认 /schedule/events|create|delete，事件日志按真顺序追加。'''
    scheduler_session = 's-p3-test'

    def __init__(self):
        self.events = []
        self.created = 0

    def schedule(self, path, payload=None):
        if path == '/schedule/events':
            return [dict(e) for e in self.events]
        if path == '/schedule/create':
            self.created += 1
            native_id = 'native-%d' % self.created
            step = payload.get('after_seconds', payload.get('every_seconds', 3600))     # daily/weekly: native recurring
            at = (datetime.now(timezone.utc) + timedelta(seconds=step)).isoformat(timespec='seconds')
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'create',
                'schedule': dict({'id': native_id, 'prompt': 'ASUNA_PLAN:' + payload['plan_id'],
                                  'kind': next((k for k in ('daily', 'weekly') if k in payload), 'every' if 'every_seconds' in payload else 'after'),
                                  'scheduledAt': at},
                                 **{k: v for k, v in payload.items() if k != 'plan_id'})}})
            return {'id': native_id, 'scheduledAt': at, 'kind': self.events[-1]['data']['schedule']['kind']}
        if path == '/schedule/delete':
            self.events.append({'seq': len(self.events) + 1,
                                'data': {'operation': 'delete', 'id': payload['id']}})
            return {'deleted': True}
        raise AssertionError('UNEXPECTED_NATIVE_CALL:' + path)

    def live(self, plan_id):
        recurring = {e['data']['schedule']['id'] for e in self.events if e['data'].get('operation') == 'create'
                     and e['data']['schedule']['kind'] in ('every', 'daily', 'weekly')}
        fired = {e['data']['id'] for e in self.events if e['data'].get('operation') == 'dispatch'} - recurring
        gone = {e['data']['id'] for e in self.events if e['data'].get('operation') == 'delete'}
        return [e['data']['schedule'] for e in self.events if e['data'].get('operation') == 'create'
                and e['data']['schedule']['prompt'] == 'ASUNA_PLAN:' + plan_id
                and e['data']['schedule']['id'] not in fired | gone]


class Controller:
    def __init__(self):
        self.received = []

    def receive(self, event):
        self.received.append(event)


class Evidence:
    def record(self, kind, payload):
        return {}


@pytest.fixture
def store():
    db = Store(load(CONFIG_PATH), isolated_database(TEST_DATABASE))
    db.migrate()
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})
    db.client.close()
    drop_database(db.config, db.name)


@pytest.fixture
def driven(store):
    '''绕开 ScheduleService.__init__：它要起 HTTP 与真 DSH lane，这里只换掉那一侧。'''
    service = ScheduleService.__new__(ScheduleService)
    import threading
    service.store = store
    service.controller = Controller()
    service.lane = Lane()
    service.deliver_lock = threading.RLock()
    service.app = type('App', (), {'config': store.config, 'evidence': Evidence(),
                                   'store': store})()
    return service


EP = {'_id': 'ep-p3-1', 'scene_id': p2.SCENE, 'person_id': p2.PERSON, 'scope_key': p2.SCOPE,
      'policy_epoch': p2.EPOCH}
DAILY = {'intent': '每天提醒我喝水', 'clock': {'time': '09:00'}}


def test_reschedule_keeps_one_row_and_one_live_native(store, driven):
    p2.seed_real(store)
    plan = driven.create(EP, DAILY)
    old = plan['schedule_id']
    updated = driven.update(EP, plan['_id'], {'plan_id': plan['_id'],
                                              'schedule': {'at': (datetime.now(timezone.utc) +
                                                                   timedelta(hours=6)).isoformat(
                                                                       timespec='seconds')}})
    assert list(store.db.plans.find({'_id': plan['_id']}))[0]['revision'] == updated['revision']
    assert store.db.plans.count_documents({}) == 1, '改期不许多出第二行'
    assert updated['plan_version'] == 2 and updated['schedule_id'] != old
    assert len(driven.lane.live(plan['_id'])) == 1, '底层同时有效的只有那一条'
    assert [e['data']['id'] for e in driven.lane.events
            if e['data'].get('operation') == 'delete'] == [old], '旧的那一次被删掉了'
    kinds = [row['type'] for row in store.db.audit_events.find({'stream_id': plan['_id']})]
    assert 'schedule.updated' in kinds, kinds


def test_cancelled_plan_is_not_resurrected(store, driven):
    p2.seed_real(store)
    plan = driven.create(EP, DAILY)
    driven.cancel(plan['_id'], p2.SCENE, p2.PERSON, p2.EPOCH)
    driven.reconcile()
    driven.reconcile()
    row = store.db.plans.find_one({'_id': plan['_id']})
    assert row['status'] == 'CANCELLED' and row['next_fire_at'] is None, row
    assert not driven.lane.live(plan['_id']), '取消后原生那边不该还留着钟'
    with pytest.raises(Denied):
        driven.update(EP, plan['_id'], {'plan_id': plan['_id'], 'intent': '算了还是要'})


def test_foreign_plan_update_is_denied(store, driven):
    p2.seed_real(store)
    driven.create(EP, DAILY)
    with pytest.raises(Denied):
        driven.update({'_id': 'ep-other', 'scene_id': p2.SCENE, 'person_id': 'qq:STRANGER',
                       'scope_key': p2.SCOPE, 'policy_epoch': p2.EPOCH},
                      'plan-p3-1', {'plan_id': 'plan-p3-1', 'intent': '替别人改'})


