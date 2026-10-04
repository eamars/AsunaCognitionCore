"""ADR-005 P1-c 宿主集成定向检查：按需群讨论整理、真实 Mongo 读取与 ToolBroker 围栏。

配置入口与既有测试相同：环境变量 ASUNA_P1C_CONFIG（默认 config/local.json），文件缺失
即 fail closed。只用固定授权库 asuna_v2_test_p1c_host_20260924（可用 ASUNA_P1C_DATABASE
指向另一个同等受限的库）：操作员账号只有这一库读写权，随机库名会在 listCollections 就
Unauthorized；库内隔离靠每个用例开头与结束清空本套件写的集合。
不依赖 ADR-001 seed 夹具，不碰生产库，不向真实 QQ 群发任何消息（这条路径全程只读）。
整理逻辑本身另有一份离线用例（tests/discussion_digest_cases.py，假集合真算），
这里补的是真实 Mongo 那一层：三支时间、游标续页、真实 ToolBroker 调用与取消围栏。
"""
import os
import uuid

import pytest

from asuna.config import ROOT, load
from conftest import isolated_database, drop_database
from asuna.state import Store, Denied
from asuna.tasks import TaskService, ToolBroker
from asuna.discussion_digest import DIGEST_TOOL_NAME, DiscussionDigestService

import discussion_digest_cases as cases

CONFIG_PATH = os.environ.get('ASUNA_P1C_CONFIG', 'config/local.json')
TEST_DATABASE = os.environ.get('ASUNA_P1C_DATABASE', 'asuna_v2_test_p1c_host_20260924')
CLEARED = ('scenes', 'messages', 'tasks', 'artifacts', 'sink_receipts', 'audit_events')
FULL = dict(cases.FULL)

TASK_BASE = dict(state='READY', fencing_token=0, intent_revision=1, tool_steps=0,
                 persona_revision='p1', integration_profile=None, raw_input_refs=[])


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


def seed(db, rows=None, sink=None):
    db.put('scenes', cases.scene_row(), stream='p1c')
    for doc in (rows if rows is not None else cases.discussion_rows()):
        db.put('messages', doc, stream='p1c')
    for row in (sink or []):
        db.put('sink_receipts', row, stream='p1c')


def make_task(db, capabilities, scope=None, epoch=cases.EPOCH):
    tid = 'task-p1c-' + str(abs(hash((tuple(capabilities), scope, epoch))))[:8]
    db.put('tasks', dict(TASK_BASE, _id=tid, request_key=tid, scene_id=cases.SCENE_ID,
                         scope_key=scope or ('scene:' + cases.SCENE_ID), requester_id=cases.A_ID,
                         policy_epoch=epoch, allowed_capabilities=list(capabilities)),
           stream='p1c')
    return db.db.tasks.find_one({'_id': tid})


@pytest.fixture
def broker_env(store):
    work = ROOT / '.runtime/work' / ('p1c-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    store.config.update(task_mode='workspace',
                        chat={'scene_id': cases.SCENE_ID, 'person_id': cases.A_ID,
                              'workspace': str(work)})
    service = TaskService(store)
    broker = ToolBroker(service)
    broker.history = None
    broker.digest = DiscussionDigestService(store, None)
    yield store, service, broker, work
    broker.close()


# ── 逻辑用例（同一套，离线也跑过）与可发现性 ──────────────────────


# ── 真实 Mongo：分类、覆盖范围、来源回读 ───────────────────────


def test_digest_pagination_no_loss_no_repeat(store):
    seed(store)
    task = make_task(store, [DIGEST_TOOL_NAME])
    service = DiscussionDigestService(store, None)
    seen, cursor, pages = [], None, 0
    while True:
        value = service.digest_for_task(task, dict(FULL, limit=2, cursor=cursor))
        assert not value['degraded'], value['why']
        seen += value['source_ids']
        assert bool(value['next_cursor']) == value['more']
        assert value['coverage']['complete'] is (not value['more'])
        if value['more']:
            assert value['next_cursor'] in value['text']       # 渲染里的 cursor 就是可用游标
        cursor = value['next_cursor']
        pages += 1
        assert pages < 20, 'pagination must terminate'
        if not value['more']:
            break
    expected = ['i1', 'i2', 'i3', 'i4', 'i5', 'o1', 'i6', 'o2']
    assert sorted(seen) == sorted(expected) and len(seen) == len(set(seen))


# ── ToolBroker：任务绑定、幂等、能力与取消围栏 ──────────────────


def test_broker_denies_without_capability_or_after_cancel(broker_env):
    store, service, broker, work = broker_env
    seed(store)
    plain = make_task(store, ['read_file'])
    broker.bind('s-plain', service.claim(plain['_id']), work)
    with pytest.raises(Denied, match='CAPABILITY_DENIED'):
        broker.call('s-plain', 'c1', DIGEST_TOOL_NAME, {})
    granted = make_task(store, [DIGEST_TOOL_NAME])
    broker.bind('s-granted', service.claim(granted['_id']), work)
    broker.digest = None
    with pytest.raises(Denied, match='DISCUSSION_DIGEST_UNAVAILABLE'):
        broker.call('s-granted', 'c1', DIGEST_TOOL_NAME, {})
    broker.digest = DiscussionDigestService(store, None)
    service.cancel(granted['_id'], person_id=cases.A_ID)
    with pytest.raises(Denied, match='STALE_TASK_FENCE'):
        broker.call('s-granted', 'c2', DIGEST_TOOL_NAME, {})


def test_service_refuses_when_scene_fence_moved(store):
    seed(store)
    service = DiscussionDigestService(store, None)
    stale_scope = make_task(store, [DIGEST_TOOL_NAME], scope='scene:some-other-binding')
    with pytest.raises(Denied, match='DIGEST_SCENE_FENCE_MISMATCH'):
        service.digest_for_task(stale_scope, dict(FULL))
    stale_epoch = make_task(store, [DIGEST_TOOL_NAME], epoch=cases.EPOCH + 1)
    with pytest.raises(Denied, match='DIGEST_SCENE_FENCE_MISMATCH'):
        service.digest_for_task(stale_epoch, dict(FULL))


