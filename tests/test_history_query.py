"""ADR-005 P1-b 宿主集成定向检查：history_query、ToolBroker 受信调用与真实 Mongo 分页。

配置路径：环境变量 ASUNA_P1B_CONFIG（默认 config/local.json，与 conftest 同一入口）；
文件缺失时 load 直接抛错，fail closed，不回退到猜的连接串。
只用固定授权测试库 asuna_v2_test_p1b_host_20260924（可用 ASUNA_P1B_DATABASE 指向另一个
同等受限的库）：操作员账号只有这一库的读写权，随机库名会在 listCollections 就 Unauthorized
（2026-09-24 操作员反馈 10 errors 全在 fixture 建库阶段）。库内隔离靠每个用例开头清空
本套件写的集合；task id 用用例内确定值，artifacts 键由 task_id 派生，中断重跑不撞 DUPLICATE_ID。
不依赖 ADR-001 seed 夹具，不碰生产数据，不要求生产全库权限。
只补本次集成未证明的部分：真实查询调用、授权绑定、真实 Mongo 三支分页；
离线 400 条截断与 32768 输出配置是既有证据，这里不重跑。
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from asuna.config import ROOT, load
from asuna.state import Store, Denied
from asuna.tasks import TaskService, ToolBroker, TOOLS, WORKSPACE_TOOLS
from asuna.history_query import (HISTORY_TOOL_NAME, HistoryQueryService, identity_status,
                                 query_history, TIME_SOURCE_INBOUND, TIME_SOURCE_RECEIPT_AT,
                                 TIME_SOURCE_SINK)

CONFIG_PATH = os.environ.get('ASUNA_P1B_CONFIG', 'config/local.json')

BOT = '3768713357'
GID = '905393941'
SCENE_ID = 'qq:' + BOT + ':group:' + GID
OTHER_SCENE = 'qq:' + BOT + ':group:54369546'
ACCOUNT = '458658853'
PERSON = 'qq:' + ACCOUNT
EPOCH = 7
FULL_WINDOW = {'since': '2000-01-01', 'until': '2999-12-31T23:59:59Z'}
VERBATIM = '第一行' + chr(10) + '   第二行  尾随空格 '

PEER = {'person_id': PERSON, 'account_id': ACCOUNT, 'scene': 'group:' + GID,
        'group_id': GID, 'display': '雾灯修理工', 'nickname': '落郇之源', 'card': '雾灯修理工',
        'role': 'admin', 'verified': True, 'aliases': ['旧名片']}
OTHER_PEER = dict(PEER, person_id='qq:7777777', account_id='7777777', display='路人甲',
                  card='路人甲', nickname='路人甲', aliases=[])


TEST_DATABASE = os.environ.get('ASUNA_P1B_DATABASE', 'asuna_v2_test_p1b_host_20260924')
CLEARED = ('scenes', 'messages', 'tasks', 'artifacts', 'sink_receipts', 'audit_events')


@pytest.fixture
def store():
    # 固定授权库：受限账号只被授权这一库，建库/改名都不在本测试的职责内。
    db = Store(load(CONFIG_PATH), TEST_DATABASE)
    db.migrate()
    # 单库顺序跑：用例开头清掉上一个用例的残留，等价于原来的每用例独立新库。
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        # 结束时再清一次：不给同库 Web 重启留 READY 合成任务（_recover_tasks 会踩空 raw_input_refs）。
        db.db[name].delete_many({})
    db.client.close()


def scene_row(scene_id):
    return {'_id': scene_id, 'scene_id': scene_id, 'kind': 'group',
            'members': [PERSON, 'xiaoman'], 'scope_key': 'scene:' + scene_id,
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
                            'channel': {'sender_id': author.split(':')[-1],
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


def sink_receipt(db, rid, at):
    db.put('sink_receipts', {'_id': rid, 'received_at': at, 'sink': 'web',
                             'scope_key': 'scene:' + SCENE_ID}, stream='p1b')


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
    return db.db.tasks.find_one({'_id': tid})


class FakeRetrieval:
    """宿主 Retrieval.search 的签名替身：只用于局部契约，真实向量路径由隔离宿主复测。"""

    def __init__(self, units=(), boom=False):
        self.units, self.boom = list(units), boom

    def search(self, scope_key, policy_epoch, query, exclude_sources=(), require_vector=False):
        if self.boom:
            raise RuntimeError('vector index down')
        return list(self.units), {'path': 'test-double'}


@pytest.fixture
def broker_env(store):
    work = ROOT / '.runtime/work' / ('p1b-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    store.config.update(task_mode='workspace',
                        chat={'scene_id': SCENE_ID, 'person_id': PERSON, 'workspace': str(work)})
    service = TaskService(store)
    broker = ToolBroker(service)
    broker.history = HistoryQueryService(store, None)
    yield store, service, broker, work
    broker.close()


# ── 模块与可发现性 ──────────────────────────────────────────────────

def test_p1a_identity_module_is_reused_not_replaced():
    status = identity_status()
    assert status['complete'] and status['source'] == 'peer_context', status


def test_tool_registered_for_action_brain_and_native_plugin(broker_env):
    store, service, broker, work = broker_env
    assert [t['name'] for t in TOOLS].count(HISTORY_TOOL_NAME) == 1
    assert [t['name'] for t in WORKSPACE_TOOLS].count(HISTORY_TOOL_NAME) == 1
    row = next(r for r in broker.rows if r['id'] == 'asuna-controlled-tools')
    assert HISTORY_TOOL_NAME in [t['name'] for t in row['config']['tools']]
    spec = next(t for t in WORKSPACE_TOOLS if t['name'] == HISTORY_TOOL_NAME)
    for word in ('原文', '来源', 'cursor'):
        assert word in spec['description']


# ── 查询主干：时间来源、作者、原文、范围 ────────────────────────

def seed_time_sources(db):
    seed_scenes(db, OTHER_SCENE)
    message(db, 'i1', 5, '2026-09-22T12:00:00Z', '雾灯坏了，明天去修')
    message(db, 'i2', 6, '2026-09-22T12:05:00Z', VERBATIM)
    message(db, 'o1', 7, '', '好的，我去看看', direction='outbound', author='xiaoman',
            peer=None, receipt_at='2026-09-22T12:06:05Z')
    message(db, 'o2', 8, '', '已经记下了', direction='outbound', author='xiaoman',
            peer=None, receipt='sr-2')
    sink_receipt(db, 'sr-2', '2026-09-22T12:07:30Z')
    message(db, 'o3', 9, '', '没送达的不算', direction='outbound', author='xiaoman', peer=None,
            delivery='READY')
    message(db, 'o4', 10, '', '不是 SPEAK 的出站', direction='outbound', author='xiaoman',
            peer=None, phase='REACT', receipt_at='2026-09-22T12:08:00Z')
    message(db, 'x1', 1, '2026-09-22T12:09:00Z', '别的群的雾灯', scene=OTHER_SCENE, peer=None)
    message(db, 'old', 2, '2026-08-01T12:00:00Z', '八百年前的雾灯')


def test_time_sources_authorship_and_verbatim(store):
    seed_time_sources(store)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    window = dict(since='2026-09-21T00:00:00Z', until='2026-09-23T23:59:59Z')
    value = service.query_for_task(task_doc(store, tid), dict(window))
    assert not value['degraded'] and value['why'] == ''
    assert [h['message_id'] for h in value['hits']] == ['o2', 'o1', 'i2', 'i1']
    by_id = dict((h['message_id'], h) for h in value['hits'])
    assert by_id['o2']['time_source'] == TIME_SOURCE_SINK and by_id['o2']['time_ref'] == 'sr-2'
    assert by_id['o1']['time_source'] == TIME_SOURCE_RECEIPT_AT
    assert by_id['i2']['time_source'] == TIME_SOURCE_INBOUND
    assert by_id['i2']['text'] == VERBATIM and by_id['i2']['verbatim']
    assert by_id['o1']['side'] == '我说' and by_id['i1']['side'] == '对方说'
    assert '雾灯修理工' in by_id['i1']['who'] and PERSON in by_id['i1']['who']
    assert 'xiaoman' in by_id['o1']['who']          # 无身份块就退回已认证作者，不冒充
    assert value['more'] is False and value['next_cursor'] is None
    assert value['scope']['scene_id'] == SCENE_ID
    assert '本机送达回执' in value['text']            # 行首就标明回执来源，不伪称发送时刻
    literal = service.query_for_task(task_doc(store, tid), dict(window, query='雾灯'))
    assert [h['message_id'] for h in literal['hits']] == ['i1']   # 字面过滤对三支同时生效，出站不例外


def test_person_filter_follows_verified_identity(store):
    seed_scenes(store)
    message(store, 'i1', 1, '2026-09-22T12:00:00Z', '一', peer=PEER)
    message(store, 'i2', 2, '2026-09-22T12:01:00Z', '二', peer=OTHER_PEER, author='qq:7777777')
    message(store, 'i3', 3, '2026-09-22T12:02:00Z', '三', peer=None)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)

    def ids(**args):
        return [h['message_id'] for h in service.query_for_task(task, dict(FULL_WINDOW, **args))['hits']]

    assert ids(person='雾灯修理工') == ['i1']            # 名片（身份块已校验）
    assert ids(person='旧名片') == ['i1']                # 曾用名也算同一个人
    # 倒序（最新在前）是查询契约：与 keyset 游标的降序、渲染行序同源；i3=12:02 比 i1=12:00 新。
    assert ids(person='qq:' + ACCOUNT) == ['i3', 'i1']   # 已认证作者
    stale = service.query_for_task(task, dict(FULL_WINDOW, person=ACCOUNT))
    # 裸账号（不带 qq: 前缀）会在查询侧被归一化匹上，但后过滤按 names 精确比对会滤掉：
    # 人物过滤要用名片/昵称或完整 person_id；这是草稿已验证的行为，照实断言，不悄悄改逻辑。
    assert [h['message_id'] for h in stale['hits']] == []
    assert stale['dropped']['wrong_person'] == 2


def test_default_window_uses_real_clock(store):
    seed_scenes(store)
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    ancient = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    message(store, 'near', 1, recent, '近的一条')
    message(store, 'far', 2, ancient, '十天前的那条')
    tid = make_task(store, [HISTORY_TOOL_NAME])
    value = HistoryQueryService(store, None).query_for_task(task_doc(store, tid), {'query': '的'})
    assert [h['message_id'] for h in value['hits']] == ['near']


# ── 真实 Mongo 分页：不重不漏；回退支翻到底才敢 more=false ──────────────

def test_pagination_no_loss_no_repeat_across_streams(store):
    seed_scenes(store)
    for i in range(1, 10):
        message(store, 'i' + str(i), i, '2026-09-22T10:%02d:00Z' % i, '第%d条原话' % i)
    for i in (1, 2):
        message(store, 'o' + str(i), 20 + i, '', '平台出站%d' % i, direction='outbound',
                author='xiaoman', peer=None, receipt_at='2026-09-22T11:0%d:00Z' % i)
    for i in (1, 2, 3):
        message(store, 's' + str(i), 30 + i, '', '本机出站%d' % i, direction='outbound',
                author='xiaoman', peer=None, receipt='sr-' + str(i))
        sink_receipt(store, 'sr-' + str(i), '2026-09-22T11:3%d:00Z' % i)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)
    seen, cursor, pages = [], None, 0
    while True:
        value = service.query_for_task(task, dict(FULL_WINDOW, limit=3, cursor=cursor))
        assert not value['degraded'], value['why']
        seen += [h['message_id'] for h in value['hits']]
        cursor = value['next_cursor']
        pages += 1
        assert pages < 30, 'pagination must terminate'
        assert bool(cursor) == value['more']
        if not value['more']:
            break
    expected = ['i' + str(i) for i in range(1, 10)] + ['o1', 'o2', 's1', 's2', 's3']
    assert sorted(seen) == sorted(expected) and len(seen) == len(set(seen))


def test_fallback_keeps_more_until_truly_exhausted(store):
    """单页预算只拦工作量：回执候选超过一轮批量时 more 必须仍为 true，直到游标真到底。"""
    seed_scenes(store)
    expected = []
    for i in range(205):
        base = 10 * 3600 + i
        at = '2026-09-22T%02d:%02d:%02dZ' % (base // 3600, base % 3600 // 60, base % 60)
        message(store, 'f%03d' % i, i, '', '本机出站%03d' % i, direction='outbound',
                author='xiaoman', peer=None, receipt='fr-%03d' % i)
        sink_receipt(store, 'fr-%03d' % i, at)
        expected.append('f%03d' % i)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)
    first = service.query_for_task(task, dict(FULL_WINDOW, limit=2))
    assert first['fallback']['attempted'] and first['fallback']['exhausted'] is False
    assert first['more'] and first['next_cursor']
    seen = [h['message_id'] for h in first['hits']]
    cursor, pages = first['next_cursor'], 1
    while True:
        value = service.query_for_task(task, dict(FULL_WINDOW, limit=2, cursor=cursor))
        seen += [h['message_id'] for h in value['hits']]
        cursor = value['next_cursor']
        pages += 1
        assert pages < 200, 'pagination must terminate'
        if not value['more']:
            break
    assert sorted(seen) == sorted(expected) and len(seen) == len(set(seen))


# ── 语义候选：附加、可区分、失败不拖垮字面 ──────────────────────

def test_semantic_candidates_are_labelled_and_fail_soft(store):
    seed_scenes(store)
    message(store, 'lit', 1, '2026-09-22T12:00:00Z', '雾灯坏了')
    message(store, 'sem', 2, '2026-09-22T12:01:00Z', '换个说法的那条')
    tid = make_task(store, [HISTORY_TOOL_NAME])
    task = task_doc(store, tid)
    service = HistoryQueryService(store, FakeRetrieval([{'source_event_ids': ['sem']}]))
    value = service.query_for_task(task, dict(FULL_WINDOW, query='雾灯'))
    via = dict((h['message_id'], h['via']) for h in value['hits'])
    assert via == {'lit': 'literal', 'sem': 'semantic'}
    assert value['semantic'] == {'ok': True, 'why': '', 'candidates': 1}
    broken = HistoryQueryService(store, FakeRetrieval(boom=True))
    value = broken.query_for_task(task, dict(FULL_WINDOW, query='雾灯'))
    assert [h['message_id'] for h in value['hits']] == ['lit']
    assert value['semantic']['ok'] is False and value['semantic']['why'].startswith('retrieval_failed')
    off = HistoryQueryService(store, FakeRetrieval(boom=True))
    value = off.query_for_task(task, dict(FULL_WINDOW, query='雾灯', include_semantic=False))
    assert value['semantic']['why'] == 'not_attempted'


# ── ToolBroker 受信调用：授权绑定、幂等、取消围栏 ────────────────────

def test_broker_call_is_task_bound_and_idempotent(broker_env):
    store, service, broker, work = broker_env
    seed_time_sources(store)
    message(store, 'x2', 4, '2026-09-22T11:00:00Z', '别的群另一条雾灯', scene=OTHER_SCENE, peer=None)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    task = service.claim(tid)
    broker.bind('s1', task, work)
    window = dict(since='2026-09-21T00:00:00Z', until='2026-09-23T23:59:59Z')
    result = broker.call('s1', 'c1', HISTORY_TOOL_NAME, dict(window))
    assert not result['degraded']
    assert [h['message_id'] for h in result['hits']] == ['o2', 'o1', 'i2', 'i1']
    assert all(h['scene_id'] == SCENE_ID for h in result['hits'])
    artifact = store.db.artifacts.find_one({'_id': result['artifact_ref']})
    assert artifact['state'] == 'DONE' and artifact['tool'] == HISTORY_TOOL_NAME
    again = broker.call('s1', 'c1', HISTORY_TOOL_NAME, dict(window))
    assert again == result                                   # 同 call_id 只回放，不重跑
    with pytest.raises(ValueError, match='HISTORY_ARGUMENT_DENIED:scene_id'):
        broker.call('s1', 'c2', HISTORY_TOOL_NAME, dict(FULL_WINDOW, query='雾灯', scene_id=OTHER_SCENE))
    other = query_history(store, {'scene_id': OTHER_SCENE, 'scope_key': 'scene:' + OTHER_SCENE,
                                  'policy_epoch': EPOCH}, '雾灯', limit=1,
                          since='2000-01-01', until='2999-12-31T23:59:59Z')
    # 无筛选指纹信封的裸位置游标、乱写的游标：都不收，宁可报错不给「看似连续」的错页。
    with pytest.raises(ValueError, match='HISTORY_CURSOR_INVALID'):
        broker.call('s1', 'c3', HISTORY_TOOL_NAME,
                    dict(FULL_WINDOW, query='雾灯', cursor=other['next_cursor'] or 'raw'))
    with pytest.raises(ValueError, match='HISTORY_CURSOR_INVALID'):
        broker.call('s1', 'c4', HISTORY_TOOL_NAME,
                    dict(FULL_WINDOW, query='雾灯', cursor='not-a-real-cursor'))
    page1 = broker.call('s1', 'c5', HISTORY_TOOL_NAME, dict(FULL_WINDOW, query='雾灯', limit=1))
    assert [h['message_id'] for h in page1['hits']] == ['i1'] and page1['next_cursor']
    assert page1['next_cursor'] in page1['text']                   # 非裁剪续页路径同样一致
    with pytest.raises(ValueError, match='HISTORY_CURSOR_FILTER_MISMATCH'):
        broker.call('s1', 'c6', HISTORY_TOOL_NAME, dict(FULL_WINDOW, query='雾灯', person='qq:7777777',
                                                       limit=1, cursor=page1['next_cursor']))
    rest = broker.call('s1', 'c7', HISTORY_TOOL_NAME,
                       dict(FULL_WINDOW, query='雾灯', limit=1, cursor=page1['next_cursor']))
    assert [h['message_id'] for h in rest['hits']] == ['old']
    assert all(h['scene_id'] == SCENE_ID for h in rest['hits'])   # 游标换不了授权范围


def test_broker_denies_without_capability_service_or_after_cancel(broker_env):
    store, service, broker, work = broker_env
    seed_time_sources(store)
    plain = make_task(store, ['read_file'])
    task = service.claim(plain)
    broker.bind('s-plain', task, work)
    with pytest.raises(Denied, match='CAPABILITY_DENIED'):
        broker.call('s-plain', 'c1', HISTORY_TOOL_NAME, {})
    granted = make_task(store, [HISTORY_TOOL_NAME])
    task = service.claim(granted)
    broker.bind('s-granted', task, work)
    broker.history = None
    with pytest.raises(Denied, match='HISTORY_QUERY_UNAVAILABLE'):
        broker.call('s-granted', 'c1', HISTORY_TOOL_NAME, {})
    broker.history = HistoryQueryService(store, None)
    service.cancel(granted, person_id=PERSON)
    with pytest.raises(Denied, match='STALE_TASK_FENCE'):
        broker.call('s-granted', 'c2', HISTORY_TOOL_NAME, {})


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

def test_long_text_page_overflow_continues_by_cursor(store):
    """探针复现：两条 30022 字消息同页命中，48KiB 预算裁掉一条——被裁的必须能续页取回完整原文。"""
    seed_scenes(store)
    long_a = 'P1B_LONG_TEXT_PROBE' + 'a' * 30000
    long_b = 'P1B_LONG_TEXT_PROBE' + 'b' * 30000
    message(store, 'long-1', 1, '2026-09-22T12:01:00Z', long_a)
    message(store, 'long-2', 2, '2026-09-22T12:02:00Z', long_b)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)
    args = dict(FULL_WINDOW, query='P1B_LONG_TEXT_PROBE', limit=2)
    first = service.query_for_task(task, args)
    assert [h['message_id'] for h in first['hits']] == ['long-2']
    assert first['hits_trimmed'] == 1 and first['more'] and first['next_cursor']
    assert first['next_cursor'] in first['text']                   # 渲染里的 cursor 就是可用游标
    assert first['hits'][0]['text'] == long_b                      # 交付的是完整原文，不是片段
    second = service.query_for_task(task, dict(args, cursor=first['next_cursor']))
    assert [h['message_id'] for h in second['hits']] == ['long-1']
    assert second['hits'][0]['text'] == long_a and not second['more']


def test_cursor_carries_the_filter_it_was_issued_with(store):
    """探针复现：person=qq:111 发放的 cursor 不能改拿 person=qq:222 复用。"""
    seed_scenes(store)
    message(store, 'A1', 1, '2026-09-22T12:01:00Z', 'P1B_CURSOR_FILTER 甲一', author='qq:111', peer=None)
    message(store, 'A2', 2, '2026-09-22T12:02:00Z', 'P1B_CURSOR_FILTER 甲二', author='qq:111', peer=None)
    message(store, 'B1', 3, '2026-09-22T12:00:00Z', 'P1B_CURSOR_FILTER 乙一', author='qq:222', peer=None)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)
    base = dict(FULL_WINDOW, query='P1B_CURSOR_FILTER', limit=1)
    page1 = service.query_for_task(task, dict(base, person='qq:111'))
    assert [h['message_id'] for h in page1['hits']] == ['A2'] and page1['next_cursor']
    assert page1['next_cursor'] in page1['text']                   # 渲染行与结构化字段同一个信封
    with pytest.raises(ValueError, match='HISTORY_CURSOR_FILTER_MISMATCH'):
        service.query_for_task(task, dict(base, person='qq:222', cursor=page1['next_cursor']))
    with pytest.raises(ValueError, match='HISTORY_CURSOR_INVALID'):
        service.query_for_task(task, dict(base, person='qq:111', cursor='not-a-real-cursor'))
    page2 = service.query_for_task(task, dict(base, person='qq:111', cursor=page1['next_cursor']))
    assert [h['message_id'] for h in page2['hits']] == ['A1'] and not page2['more']

