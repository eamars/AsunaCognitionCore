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
from asuna.state import Store, Denied
from asuna.tasks import TaskService, ToolBroker, TOOLS, WORKSPACE_TOOLS
from asuna.history_query import HISTORY_TOOL_NAME, HistoryQueryService
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
    db = Store(load(CONFIG_PATH), TEST_DATABASE)
    db.migrate()
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})
    db.client.close()


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

def test_offline_cases_all_pass():
    failed = [(name, why) for name, ok, why in cases.run_all() if not ok]
    assert not failed, failed


def test_tool_registered_for_action_brain_and_native_plugin(broker_env):
    store, service, broker, work = broker_env
    assert [t['name'] for t in TOOLS].count(DIGEST_TOOL_NAME) == 1
    assert [t['name'] for t in WORKSPACE_TOOLS].count(DIGEST_TOOL_NAME) == 1
    row = next(r for r in broker.rows if r['id'] == 'asuna-controlled-tools')
    assert DIGEST_TOOL_NAME in [t['name'] for t in row['config']['tools']]
    spec = next(t for t in WORKSPACE_TOOLS if t['name'] == DIGEST_TOOL_NAME)
    for word in ('参与者', '更正', '未决', '覆盖范围', 'cursor'):
        assert word in spec['description']


# ── 真实 Mongo：分类、覆盖范围、来源回读 ───────────────────────

def test_digest_on_real_mongo_separates_categories(store):
    seed(store)
    task = make_task(store, [DIGEST_TOOL_NAME])
    value = DiscussionDigestService(store, None).digest_for_task(task, dict(FULL))
    assert value['degraded'] is False and value['why'] == ''
    people = dict((person['display'], person) for person in value['participants'])
    assert sorted(people) == sorted([cases.A_CARD, cases.B_CARD, 'xiaoman']), people
    assert people[cases.A_CARD]['identity'] == 'peer' and people[cases.A_CARD]['role'] == '管理员'
    assert people['xiaoman']['identity'] == 'author' and people['xiaoman']['side'] == '我说'
    assert [item['message_id'] for item in value['corrections']] == ['i4']
    assert value['corrections'][0]['basis'] == 'reply_link'
    assert value['corrections'][0]['corrects'] == 'i1'
    assert set(item['message_id'] for item in value['opinions']) == {'i2', 'i3'}
    assert [item['message_id'] for item in value['open_items']] == ['i6']
    assert value['resolved'][0]['answered_by'] == 'o2'
    cov = value['coverage']
    assert (cov['read'], cov['inbound'], cov['outbound']) == (8, 6, 2)
    assert cov['covered_from'] == '2026-09-22T12:00:00Z'
    assert cov['covered_to'] == '2026-09-22T12:07:00Z'
    assert cov['excluded'] == {'undelivered_outbound': 1, 'non_speak_outbound': 1}, cov
    assert cov['complete'] is True and value['more'] is False
    assert value['scope']['scene_id'] == cases.SCENE_ID
    assert value['readback']['tool'] == HISTORY_TOOL_NAME      # 来源回读沿 P1-b 那条
    assert '机械标注' in value['text'] and 'message_id' in value['text']


def test_digest_carries_sink_receipt_time(store):
    rows = [cases.inbound('i1', 1, '2026-09-22T12:04:00Z', '那工具谁带？',
                          author=cases.B_ID, peer=cases.PEER_B),
            cases.outbound('o1', 2, '工具我来带', reply_to='i1', receipt_at=None)]
    rows[1]['receipt'] = 'sr-1'
    seed(store, rows, sink=[{'_id': 'sr-1', 'received_at': '2026-09-22T12:07:00Z', 'sink': 'web'}])
    task = make_task(store, [DIGEST_TOOL_NAME])
    value = DiscussionDigestService(store, None).digest_for_task(task, dict(FULL))
    assert value['coverage']['time_sources'] == {'messages.occurred_at': 1,
                                                'sink_receipts.received_at': 1}, value['coverage']
    assert value['resolved'][0]['answered_by'] == 'o1'


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


def test_partial_coverage_blocks_completion_claim(store):
    seed(store)
    task = make_task(store, [DIGEST_TOOL_NAME])
    service = DiscussionDigestService(store, None)
    first = service.digest_for_task(task, dict(FULL, limit=3))
    assert first['more'] is True and first['coverage']['complete'] is False
    assert '部分覆盖' in first['text'] and '还有更早的没读' in first['text']
    second = service.digest_for_task(task, dict(FULL, limit=3, cursor=first['next_cursor']))
    # 跨页的链不猜：回答在本页、被回答的那条还没读到，就不能说已被回应
    assert second['source_ids'] == ['i3', 'i4', 'i5']
    assert second['corrections'][0]['basis'] == 'reply_link_out_of_scope'
    assert [item['message_id'] for item in second['open_items']] == ['i5']


# ── ToolBroker：任务绑定、幂等、能力与取消围栏 ──────────────────

def test_broker_call_is_task_bound_and_idempotent(broker_env):
    store, service, broker, work = broker_env
    seed(store)
    other = cases.inbound('x1', 30, '2026-09-22T13:00:00Z', '别的群的雾灯',
                          scene=cases.OTHER_SCENE, peer=None)
    store.put('messages', other, stream='p1c')
    tid = make_task(store, [DIGEST_TOOL_NAME])['_id']
    task = service.claim(tid)
    broker.bind('s1', task, work)
    result = broker.call('s1', 'c1', DIGEST_TOOL_NAME, dict(FULL))
    assert result['degraded'] is False
    assert result['coverage']['read'] == 8                     # 别的群那条没混进来
    assert all(mid in result['source_ids'] for mid in ('i1', 'o2'))
    assert 'x1' not in result['source_ids']
    artifact = store.db.artifacts.find_one({'_id': result['artifact_ref']})
    assert artifact['state'] == 'DONE' and artifact['tool'] == DIGEST_TOOL_NAME
    assert broker.call('s1', 'c1', DIGEST_TOOL_NAME, dict(FULL)) == result   # 同 call_id 只回放
    with pytest.raises(ValueError, match='DIGEST_ARGUMENT_DENIED:scene_id'):
        broker.call('s1', 'c2', DIGEST_TOOL_NAME, dict(FULL, scene_id=cases.OTHER_SCENE))


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


def test_topic_filter_keeps_thread_continuation_on_real_mongo(store):
    """真实 Mongo 上复现并验住那个缺陷：不含主题词的 reply 更正必须进覆盖范围。"""
    seed(store, cases.thread_rows())
    task = make_task(store, [DIGEST_TOOL_NAME])
    value = DiscussionDigestService(store, None).digest_for_task(task, dict(FULL, topic="线缆"))
    assert value["source_ids"] == ["c1", "c2", "c3", "o1"], value["source_ids"]
    assert "cam1" not in value["source_ids"] and "cam2" not in value["source_ids"]
    correction = value["corrections"][0]
    assert correction["message_id"] == "c2" and "线缆" not in correction["text"]
    assert correction["basis"] == "reply_link" and correction["thread"] is True
    cov = value["coverage"]
    assert (cov["read"], cov["matched"], cov["thread_extra"]) == (4, 1, 3), cov
    assert cov["complete"] is True and cov["thread"]["extra"] == 3
    assert [item["message_id"] for item in value["resolved"]] == ["c3"]
    assert "相机" not in value["text"] and "线程内后续" in value["text"]
    args = value["readback"]["example_args"]
    assert value["readback"]["topic_omitted"] is True and "query" not in args, value["readback"]
    assert value["readback"]["thread_source_ids"] == ["c2", "c3"]
    # 回读参数真能回读：拿它去问 P1-b 那条查询，必须把这条不含主题词的更正还回来
    back = HistoryQueryService(store, None).query_for_task(
        make_task(store, [HISTORY_TOOL_NAME]), dict(args))
    assert "c2" in [hit["message_id"] for hit in back["hits"]], back["hits"]


def test_thread_rows_outside_the_window_are_counted_not_invented(store):
    seed(store, cases.thread_rows())
    task = make_task(store, [DIGEST_TOOL_NAME])
    value = DiscussionDigestService(store, None).digest_for_task(
        task, dict(FULL, topic="线缆", until="2026-09-22T12:03:00Z"))
    assert value["source_ids"] == ["c1", "c2"], value["source_ids"]
    assert value["coverage"]["thread"]["out_of_window"] == 2, value["coverage"]["thread"]
    assert any("窗口外" in note for note in value["notes"]), value["notes"]


def test_seed_and_continuation_are_not_delivered_twice_on_real_mongo(store):
    """真实 Mongo 上逐页走：既是命中项又是链上环节的行只送一遍。"""
    seed(store, cases.seed_and_continuation_rows())
    task = make_task(store, [DIGEST_TOOL_NAME])
    service = DiscussionDigestService(store, None)
    seen, cursor, value, pages = [], None, None, 0
    while True:
        value = service.digest_for_task(task, dict(FULL, topic="线缆", limit=1, cursor=cursor))
        seen += value["source_ids"]
        assert bool(value["next_cursor"]) == value["more"]
        pages += 1
        assert pages < 12, "pagination must terminate"
        if not value["more"]:
            break
        cursor = value["next_cursor"]
    assert sorted(seen) == ["s1", "s2", "x"], seen
    assert len(seen) == len(set(seen)), seen
    assert value["coverage"]["complete"] is True
    assert value["coverage"]["thread"]["skipped_carried"] == 1, value["coverage"]["thread"]


def test_long_thread_reports_partial_then_continues_on_real_mongo(store):
    """真实 Mongo：链比轮数上限还长时报部分完成，且带 cursor 能沿同一筛选读到 m10/m11。"""
    seed(store, cases.long_thread_rows())
    task = make_task(store, [DIGEST_TOOL_NAME])
    service = DiscussionDigestService(store, None)
    first = service.digest_for_task(task, dict(FULL, topic="线缆"))
    assert first["source_ids"] == ["m%d" % n for n in range(1, 10)], first["source_ids"]
    assert first["more"] is True and first["next_cursor"]
    assert first["coverage"]["complete"] is False
    assert first["coverage"]["thread"]["truncated"] is True
    assert first["coverage"]["thread"]["why"] == "thread_rounds_exhausted"
    assert first["coverage"]["thread"]["pending"] == ["m9"]
    assert "部分覆盖（讨论流没走完）" in first["text"]
    second = service.digest_for_task(task, dict(FULL, topic="线缆",
                                               cursor=first["next_cursor"]))
    assert second["source_ids"] == ["m10", "m11"], second["source_ids"]
    assert second["more"] is False and second["next_cursor"] is None
    assert second["coverage"]["complete"] is True, second["coverage"]
    assert second["coverage"]["thread"]["resumed"] is True
    assert second["coverage"]["window"] == first["coverage"]["window"]
    assert sorted(first["source_ids"] + second["source_ids"]) == sorted(
        ["m%d" % n for n in range(1, 12)])


def test_person_scope_labels_thread_context_on_real_mongo(store):
    """真实 Mongo：person 只限定主题命中项，链上带进来的别人标 thread_context。"""
    seed(store, cases.person_scope_rows())
    task = make_task(store, [DIGEST_TOOL_NAME])
    value = DiscussionDigestService(store, None).digest_for_task(task,
                                                                dict(FULL, topic="线缆",
                                                                     person=cases.A_CARD))
    assert value["source_ids"] == ["a1", "b1"], value["source_ids"]
    assert value["coverage"]["person_scope"] == "seed"
    assert value["coverage"]["person_context_rows"] == 1, value["coverage"]
    item = next(x for x in value["corrections"] if x["message_id"] == "b1")
    assert item["thread"] is True and item["person_match"] is False, item
    marks = dict((person["display"], person) for person in value["participants"])
    assert marks[cases.A_CARD]["outside_person"] == 0
    assert marks[cases.B_CARD]["outside_person"] == 1
    assert any("person 只限定主题命中项" in note for note in value["notes"]), value["notes"]
    assert "非 person 指定" in value["text"]


def test_p1b_history_path_is_untouched(store):
    """P1-c 只加不改：P1-b 那条查询在同一个宿主里行为不变。"""
    seed(store)
    task = make_task(store, [HISTORY_TOOL_NAME])
    value = HistoryQueryService(store, None).query_for_task(task, dict(FULL))
    assert [hit['message_id'] for hit in value['hits']] == ['o2', 'i6', 'o1', 'i5', 'i4',
                                                            'i3', 'i2', 'i1']
    assert value['more'] is False and value['degraded'] is False
