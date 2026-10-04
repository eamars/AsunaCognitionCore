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
import json
import os
import uuid

import pytest

from asuna.config import ROOT, load
from asuna.state import Store, Denied
from asuna.tasks import TaskService, ToolBroker
from asuna.history_query import HISTORY_TOOL_NAME, HistoryQueryService, query_history

CONFIG_PATH = os.environ.get('ASUNA_P1B_CONFIG', 'config/local.json')

BOT = '100357'
GID = '300941'
SCENE_ID = 'qq:' + BOT + ':group:' + GID
OTHER_SCENE = 'qq:' + BOT + ':group:300546'
ACCOUNT = '100853'
PERSON = 'qq:' + ACCOUNT
EPOCH = 7
FULL_WINDOW = {'since': '2000-01-01', 'until': '2999-12-31T23:59:59Z'}
VERBATIM = '第一行' + chr(10) + '   第二行  尾随空格 '

PEER = {'person_id': PERSON, 'account_id': ACCOUNT, 'scene': 'group:' + GID,
        'group_id': GID, 'display': '雾灯修理工', 'nickname': '示例昵称', 'card': '雾灯修理工',
        'role': 'admin', 'verified': True, 'aliases': ['旧名片']}
OTHER_PEER = dict(PEER, person_id='qq:100777', account_id='100777', display='路人甲',
                  card='路人甲', nickname='路人甲', aliases=[])


TEST_DATABASE = os.environ.get('ASUNA_P1B_DATABASE', 'asuna_v2_test_p1b_host_20260924')
CLEARED = ('scenes', 'messages', 'tasks', 'artifacts', 'sink_receipts', 'audit_events')


@pytest.fixture(scope='module')
def module_database():
    # One isolated database for this module (migrated once), dropped when the module finishes.
    from conftest import isolated_database, drop_database
    db = Store(load(CONFIG_PATH), isolated_database(TEST_DATABASE))
    db.migrate()
    yield db
    db.client.close()
    drop_database(db.config, db.name)


@pytest.fixture
def store(module_database):
    db = module_database
    # 单库顺序跑：用例开头清掉上一个用例的残留，等价于原来的每用例独立新库。
    for name in CLEARED:
        db.db[name].delete_many({})
    yield db
    for name in CLEARED:
        db.db[name].delete_many({})


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


# ── 查询主干：时间来源、作者、原文、范围 ────────────────────────

def seed_time_sources(db):
    seed_scenes(db, OTHER_SCENE)
    message(db, 'i1', 5, '2026-09-22T12:00:00Z', '雾灯坏了，明天去修')
    message(db, 'i2', 6, '2026-09-22T12:05:00Z', VERBATIM)
    message(db, 'o1', 7, '', '好的，我去看看', direction='outbound', author='demo',
            peer=None, receipt_at='2026-09-22T12:06:05Z')
    message(db, 'o2', 8, '', '已经记下了', direction='outbound', author='demo',
            peer=None, receipt='sr-2')
    sink_receipt(db, 'sr-2', '2026-09-22T12:07:30Z')
    message(db, 'o3', 9, '', '没送达的不算', direction='outbound', author='demo', peer=None,
            delivery='READY')
    message(db, 'o4', 10, '', '不是 SPEAK 的出站', direction='outbound', author='demo',
            peer=None, phase='REACT', receipt_at='2026-09-22T12:08:00Z')
    message(db, 'x1', 1, '2026-09-22T12:09:00Z', '别的群的雾灯', scene=OTHER_SCENE, peer=None)
    message(db, 'old', 2, '2026-08-01T12:00:00Z', '八百年前的雾灯')


def test_person_filter_follows_verified_identity(store):
    seed_scenes(store)
    message(store, 'i1', 1, '2026-09-22T12:00:00Z', '一', peer=PEER)
    message(store, 'i2', 2, '2026-09-22T12:01:00Z', '二', peer=OTHER_PEER, author='qq:100777')
    message(store, 'i3', 3, '2026-09-22T12:02:00Z', '三', peer=None)
    tid = make_task(store, [HISTORY_TOOL_NAME])
    service = HistoryQueryService(store, None)
    task = task_doc(store, tid)

    def ids(**args):
        return [h['message_id'] for h in service.query_for_task(task, dict(FULL_WINDOW, **args))['hits']]

    # A name resolves to one account (people.py), and the filter is that account's messages:
    # i3 carries no profile but is the same author. 倒序（最新在前）是查询契约。
    assert ids(person='雾灯修理工') == ['i3', 'i1']      # 名片
    assert ids(person='旧名片') == ['i3', 'i1']          # 曾用名也算同一个人
    assert ids(person='qq:' + ACCOUNT) == ['i3', 'i1']   # 已认证作者
    assert ids(person=ACCOUNT) == ['i3', 'i1']           # 裸账号
    label = service.query_for_task(task, dict(FULL_WINDOW, person='雾灯修理工'))['hits'][0]['who']
    number = label.split('#')[1].split(']')[0]
    assert ids(person='#' + number) == ['i3', 'i1']      # 标签编号
    hit = service.query_for_task(task, dict(FULL_WINDOW, person='#' + number))['hits'][0]
    assert not {'author', 'person_id', 'names'} & set(hit) and ACCOUNT not in json.dumps(hit, ensure_ascii=False)
    # Someone copies the name: the lookup names both people and asks for the number, it never picks one.
    message(store, 'i4', 4, '2026-09-22T12:03:00Z', '四', author='qq:100778',
            peer=dict(PEER, person_id='qq:100778', account_id='100778', aliases=[]))
    copied = service.query_for_task(task, dict(FULL_WINDOW, person='雾灯修理工'))
    assert copied['hits'] == [] and copied['why'] == 'person_unclear' and copied['text'].count('[雾灯修理工 #') == 2
    assert ids(person='#' + number) == ['i3', 'i1']      # the label still names exactly one of them


# ── 真实 Mongo 分页：不重不漏；回退支翻到底才敢 more=false ──────────────

def test_pagination_no_loss_no_repeat_across_streams(store):
    seed_scenes(store)
    for i in range(1, 10):
        message(store, 'i' + str(i), i, '2026-09-22T10:%02d:00Z' % i, '第%d条原话' % i)
    for i in (1, 2):
        message(store, 'o' + str(i), 20 + i, '', '平台出站%d' % i, direction='outbound',
                author='demo', peer=None, receipt_at='2026-09-22T11:0%d:00Z' % i)
    for i in (1, 2, 3):
        message(store, 's' + str(i), 30 + i, '', '本机出站%d' % i, direction='outbound',
                author='demo', peer=None, receipt='sr-' + str(i))
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


# ── 语义候选：附加、可区分、失败不拖垮字面 ──────────────────────


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
        broker.call('s1', 'c6', HISTORY_TOOL_NAME, dict(FULL_WINDOW, query='雾灯', person='qq:100777',
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
