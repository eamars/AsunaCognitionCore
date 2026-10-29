"""ADR-005 P1-b on MongoDB: history_query through ToolBroker's trusted call, refused once the conversation's fence
moved. On the fixture world's throwaway database, the collections this file writes cleared first."""
import pytest

from asuna.state import Denied
from asuna.history_query import HISTORY_TOOL_NAME, HistoryQueryService, query_history

pytestmark = pytest.mark.world                # `store` is the fixture world

BOT = '100357'
GID = '300941'
SCENE_ID = 'qq:' + BOT + ':group:' + GID
ACCOUNT = '100853'
PERSON = 'qq:' + ACCOUNT
EPOCH = 7

PEER = {'person_id': PERSON, 'account_id': ACCOUNT, 'scene': 'group:' + GID,
        'group_id': GID, 'display': '雾灯修理工', 'nickname': '示例昵称', 'card': '雾灯修理工',
        'role': 'admin', 'verified': True, 'aliases': ['旧名片']}


CLEARED = ('scenes', 'messages', 'tasks', 'artifacts', 'sink_receipts', 'audit_events')


@pytest.fixture
def store(store):
    for name in CLEARED:
        store.raw[name].delete_many({})
    return store


def scene_row(scene_id):
    return {'_id': scene_id, 'scene_id': scene_id, 'kind': 'group',
            'members': [PERSON, 'demo'], 'scope_key': 'scene:' + scene_id,
            'policy_epoch': EPOCH, 'sequence': 0}


def seed_scenes(db, *scene_ids):
    for scene_id in [SCENE_ID] + list(scene_ids):
        db.put('scenes', scene_row(scene_id), stream='p1b')


def message(db, mid, seq, at, text, direction='inbound', scene=SCENE_ID, epoch=EPOCH,
            author=PERSON, peer=PEER, phase='SPEAK', delivery='DELIVERED',
            receipt_at=None, receipt=None):
    """行形状按真实写入链：入站 occurred_at（ingress），平台回执 receipt_at（channels），
    本机 Web 出站只有指向 sink_receipts 的 receipt 引用；三类时间不能混。"""
    doc = {'_id': mid, 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': epoch,
           'scene_seq': seq, 'text': text, 'author': author, 'direction': direction,
           'adapter_id': 'p1b-fixture', 'platform_event_id': 'pe-' + mid}
    if direction == 'inbound':
        doc['delivery_state'] = 'RECEIVED'
        doc['occurred_at'] = at
        if peer is not None:
            doc['event'] = {'raw': {'asuna_peer': dict(peer)},
                            'channel': {'id': 'qq', 'sender_id': author.split(':')[-1],
                                        'target': {'type': 'group', 'id': scene.rsplit(':', 1)[-1]}}}
    else:
        doc['phase'] = phase
        doc['delivery_state'] = delivery
        if receipt_at:
            doc['receipt_at'] = receipt_at
        if receipt:
            doc['receipt'] = receipt
    db.put('messages', doc, stream='p1b')
    return doc


TASK_BASE = dict(state='READY', fencing_token=0, intent_revision=1, tool_steps=0,
                 persona_revision='p1', integration_profile=None, raw_input_refs=[])


def make_task(db, capabilities, scene_id=SCENE_ID, scope=None, epoch=EPOCH, requester=PERSON):
    # 确定值而非 uuid：artifacts 键由 (task_id, intent_revision, call_id) 派生，
    # 用例中断留下的 INTENT 行会在重跑时撞 DUPLICATE_ID；tasks 每用例已清空，这里求双层保险。
    tid = 'task-p1b-' + str(abs(hash((scene_id, tuple(capabilities), scope, epoch))))[:8]
    db.put('tasks', dict(TASK_BASE, _id=tid, request_key=tid, scene_id=scene_id,
                         scope_key=scope or ('scene:' + scene_id), requester_id=requester,
                         policy_epoch=epoch, allowed_capabilities=list(capabilities)),
           stream='p1b')
    return tid


def task_doc(db, tid):
    return db.raw.tasks.find_one({'_id': tid})


# ── 模块与可发现性 ──────────────────────────────────────────────────


# ── 查询主干：时间来源、作者、原文、范围 ────────────────────────


# ── 真实 Mongo 分页：不重不漏；回退支翻到底才敢 more=false ──────────────


# ── 语义候选：附加、可区分、失败不拖垮字面 ──────────────────────


# ── ToolBroker 受信调用：授权绑定、幂等、取消围栏 ────────────────────


def test_service_refuses_when_scene_fence_moved(store):
    seed_scenes(store)
    message(store, 'i1', 1, '2026-09-22T12:00:00Z', '雾灯')
    service = HistoryQueryService(store, None)
    stale_scope = make_task(store, [HISTORY_TOOL_NAME], scope='scene:some-other-binding')
    with pytest.raises(Denied, match='HISTORY_SCENE_FENCE_MISMATCH'):
        service.query_for_task(task_doc(store, stale_scope), {})
    stale_epoch = make_task(store, [HISTORY_TOOL_NAME], epoch=EPOCH + 1)
    with pytest.raises(Denied, match='HISTORY_SCENE_FENCE_MISMATCH'):
        service.query_for_task(task_doc(store, stale_epoch), {})
    degraded = query_history(None, store, {'scene_id': SCENE_ID}, '雾灯')
    assert degraded['degraded'] and degraded['why'] == 'no_scope'   # 场景不完整就拒查，不裸扫


# ── 隔离探针复现：预算裁剪与游标筛选连续性（2026-09-24 第三轮反馈）──────────────


