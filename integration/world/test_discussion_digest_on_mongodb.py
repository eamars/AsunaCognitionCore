"""ADR-005 P1-c on MongoDB: the discussion digest, refused once the conversation's fence moved. On the fixture world's
throwaway database, the collections this file writes cleared first; the digest itself has offline cases
(tests/discussion_digest_cases.py)."""
import pytest

from asuna.state import Denied
from asuna.discussion_digest import DIGEST_TOOL_NAME, DiscussionDigestService

import discussion_digest_cases as cases

pytestmark = pytest.mark.world                # `store` is the fixture world

CLEARED = ('scenes', 'messages', 'tasks', 'artifacts', 'sink_receipts', 'audit_events')
FULL = dict(cases.FULL)

TASK_BASE = dict(state='READY', fencing_token=0, intent_revision=1, tool_steps=0,
                 persona_revision='p1', integration_profile=None, raw_input_refs=[])


@pytest.fixture
def store(store):
    for name in CLEARED:
        store.raw[name].delete_many({})
    return store


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
    return db.raw.tasks.find_one({'_id': tid})


# ── 逻辑用例（同一套，离线也跑过）与可发现性 ──────────────────────


# ── 真实 Mongo：分类、覆盖范围、来源回读 ───────────────────────


# ── ToolBroker：任务绑定、幂等、能力与取消围栏 ──────────────────


def test_service_refuses_when_scene_fence_moved(store):
    seed(store)
    service = DiscussionDigestService(store, None)
    stale_scope = make_task(store, [DIGEST_TOOL_NAME], scope='scene:some-other-binding')
    with pytest.raises(Denied, match='DIGEST_SCENE_FENCE_MISMATCH'):
        service.digest_for_task(stale_scope, dict(FULL))
    stale_epoch = make_task(store, [DIGEST_TOOL_NAME], epoch=cases.EPOCH + 1)
    with pytest.raises(Denied, match='DIGEST_SCENE_FENCE_MISMATCH'):
        service.digest_for_task(stale_epoch, dict(FULL))


