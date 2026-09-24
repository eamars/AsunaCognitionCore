"""ADR-005 P2 离线用例：摘要能不能写进关系、能不能读进下一轮，用假集合真算一遍。

本机 python3 tools/p2_offline_check.py 直接跑，不需要 Mongo、不需要 pytest。
假掉的只有 import 期的第三方（bson/pymongo/httpx/jsonschema/msvcrt）；
Store.put／audit／head／mutate、MemoryService.commit_understanding、ContextBuilder.prepare
都是仓库里那份真代码在跑——过滤、排序、CAS、来源根遍历都是算出来的，不是断言出来的。
真实 Mongo 下的同一批结论由 tests/test_p2_summary_loop.py 在隔离宿主复测，两者不互相代替。
"""
import importlib
import os
import sys
import types
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _stub_when_missing(name, factory):
    '''只在真库装不上时才假：操作员在隔离宿主跑时用的是真 pymongo／真 jsonschema。'''
    try:
        importlib.import_module(name)
        return False
    except Exception:
        factory()
        return True


def _install_stubs():
    def bson():
        _stub('bson', BSON=SimpleNamespace(encode=lambda doc: b'{}'))

    def pymongo():
        root = _stub('pymongo', ASCENDING=1, MongoClient=object,
                     ReturnDocument=SimpleNamespace(AFTER=1), WriteConcern=lambda **kw: None)
        root.errors = _stub('pymongo.errors',
                            DuplicateKeyError=type('DuplicateKeyError', (Exception,), {}))
        root.operations = _stub('pymongo.operations', SearchIndexModel=object)

    def httpx():
        _stub('httpx', Client=lambda *a, **k: SimpleNamespace(timeout=None, build_request=None,
                                                              send=None),
              Timeout=lambda *a, **k: None)

    def jsonschema():
        _stub('jsonschema', validate=lambda value, schema: None,
              ValidationError=type('ValidationError', (Exception,), {}))

    def msvcrt():
        # 假了 msvcrt 之后，标准库 subprocess 会跟着去找 _winapi；一并补上名字。
        _stub('msvcrt', setlocking=lambda handle, mode: None, locking=lambda handle: None)
        _stub('_winapi', __getattr__=lambda name: 0)   # subprocess 只要一堆常量名

    return [name for name, factory in (('bson', bson), ('pymongo', pymongo), ('httpx', httpx),
                                       ('jsonschema', jsonschema), ('msvcrt', msvcrt))
            if _stub_when_missing(name, factory)]


STUBBED = _install_stubs()

from asuna.context import ContextBuilder                       # noqa: E402
from asuna.ingress import episode_id                           # noqa: E402
from asuna.memory import MemoryService                         # noqa: E402
from asuna.state import COLLECTIONS, Denied, Store             # noqa: E402

PERSON = 'qq:A'
SCENE = 'dm-a'
SCOPE = 'scene:dm-a'
EPOCH = 7
INBOUND = 'in-ep1'
OUTBOUND = 'ep1:speak:0'
SUMMARY = 'summary-1'
MONO = 'mono-ep1:0'
PERSONA_BODY = ('沈小满，24 岁。说话清淡直接，有一点不刻薄的机灵。分得清什么是看到的事实、'
                '什么是自己猜的、什么只是想做的。愿意帮忙，也会说不想做什么；休息和聊天 '
                '不算浪费。会被经历影响，允许自己改看法，不拿工作量证明自己值得被喜欢。')


# ── 假集合：真算过滤／投影／排序，只按 pymongo 在本路径用到的那一小块 ──────
def _lookup(doc, key):
    value = doc
    for part in key.split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return False, None
    return True, value


def _match(doc, flt):
    for key, cond in flt.items():
        if key == '$or':
            if not any(_match(doc, sub) for sub in cond):
                return False
        elif key == '$and':
            if not all(_match(doc, sub) for sub in cond):
                return False
        elif isinstance(cond, dict):
            found, value = _lookup(doc, key)
            for op, arg in cond.items():
                if op == '$in' and value not in arg:
                    return False
                elif op == '$exists' and found is not bool(arg):
                    return False
                elif op == '$ne' and found and value == arg:
                    return False
                elif op == '$gt' and (value is None or value <= arg):
                    return False
                elif op == '$gte' and (value is None or value < arg):
                    return False
                elif op == '$lte' and (value is None or value > arg):
                    return False
                elif op == '$lt' and (value is None or value >= arg):
                    return False
        else:
            found, value = _lookup(doc, key)
            if not found or not (value == cond or (isinstance(value, list) and cond in value)):
                return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    if not any(value for key, value in projection.items() if key != '_id'):
        # 排除式投影（本路径只有 {'embedding':0}）：整条留下，只剔掉点名的键。
        out = dict(doc)
        for key, value in projection.items():
            if not value and key != '_id':
                out.pop(key, None)
        return out
    out = {'_id': doc.get('_id')}
    for key in projection:
        if key == '_id':
            continue
        found, value = _lookup(doc, key)
        if not found:
            continue
        cursor = out
        parts = key.split('.')
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, *args):
        keys = []
        for arg in args:
            if isinstance(arg, list):
                keys.extend(arg)
            elif isinstance(arg, str) and len(args) > 1:
                keys.append((arg, args[1]))
        for key, direction in reversed(keys):
            self.rows.sort(key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = {row['_id']: dict(row) for row in (rows or [])}

    def find(self, flt=None, projection=None):
        return FakeCursor([_project(doc, projection) for doc in self.rows.values()
                           if _match(doc, flt or {})])

    def find_one(self, flt=None, projection=None, sort=None):
        cursor = self.find(flt, projection)
        if sort:
            cursor.sort(sort)
        for row in cursor:
            return row
        return None

    def insert_one(self, doc):
        if doc['_id'] in self.rows:
            raise sys.modules['pymongo.errors'].DuplicateKeyError(str(doc['_id']))
        self.rows[doc['_id']] = dict(doc)
        return SimpleNamespace(inserted_id=doc['_id'])

    def replace_one(self, flt, doc):
        current = self.rows.get(flt.get('_id'))
        if current is None or ('revision' in flt and current.get('revision') != flt['revision']):
            return SimpleNamespace(modified_count=0)
        self.rows[flt['_id']] = dict(doc)
        return SimpleNamespace(modified_count=1)


class FakeDB:
    def __init__(self, rows_by_collection):
        for name in COLLECTIONS:
            setattr(self, name, FakeCollection(rows_by_collection.get(name, [])))

    def __getitem__(self, name):          # Store.mutate 会走 db[collection]
        return getattr(self, name)


def bind_store(rows_by_collection=None, workspace=True):
    '''真 Store 方法绑到假库：put／audit／head／mutate／authorize 全走仓库实现。'''
    store = Store.__new__(Store)
    store.config = {'mongo_uri': 'mongodb://stub', 'database': 'fake', 'legacy_database': 'legacy',
                    'allowed_databases': ['fake'],
                    'prompts_dir': os.path.join(ROOT, 'docs', 'development_plans',
                                                'ADR-001-asuna_v2_v1_handoff', 'prompts')}
    if workspace:
        store.config['task_mode'] = 'workspace'
        store.config['chat'] = {'scene_id': SCENE, 'person_id': PERSON, 'workspace': '/task'}
    store.name = 'fake'
    store.fail_audit = False
    store.db = FakeDB(rows_by_collection or {})
    return store


# ── 一份 P2 私聊现场：两条原文 + 一条后台摘要 + 本轮独白 ──────────────
def rows(**overrides):
    scene = {'_id': SCENE, 'kind': 'dm', 'members': [PERSON, 'xiaoman'], 'scope_key': SCOPE,
             'policy_epoch': EPOCH, 'sequence': 8, 'revision': 1}
    inbound = {'_id': INBOUND, 'scene_id': SCENE, 'scope_key': SCOPE, 'policy_epoch': EPOCH,
               'scene_seq': 7, 'direction': 'inbound', 'author': PERSON, 'text': '我周三去修雾灯',
               'platform_event_id': 'evt1', 'occurred_at': '2026-09-24T06:00:00+00:00', 'revision': 1}
    outbound = {'_id': OUTBOUND, 'scene_id': SCENE, 'scope_key': SCOPE, 'policy_epoch': EPOCH,
                'scene_seq': 8, 'direction': 'outbound', 'author': 'xiaoman', 'text': '工具我带',
                'delivery_state': 'DELIVERED', 'receipt_at': '2026-09-24T06:01:00+00:00', 'revision': 1}
    summary = {'_id': SUMMARY, 'kind': 'dialogue_summary', 'scope_key': SCOPE, 'policy_epoch': EPOCH,
               'character_id': 'xiaoman', 'epistemic_type': 'derived_summary', 'status': 'active',
               'body_markdown': '他说周三去修雾灯；我说工具我带。',
               'source_event_ids': [INBOUND, OUTBOUND], 'scene_id': SCENE, 'source_window': [7, 8],
               'generated_at': '2026-09-24T06:05:00+00:00', 'embedding_status': 'READY', 'revision': 1}
    monologue = {'_id': MONO, 'kind': 'monologue', 'episode_id': 'ep1', 'scope_key': SCOPE,
                 'policy_epoch': EPOCH, 'character_id': 'xiaoman', 'status': 'active',
                 'epistemic_type': 'character_interpretation', 'body_markdown': '他把日子说定了。',
                 'source_event_ids': ['evt1'], 'revision': 1}
    rel_head = {'_id': 'relationship:' + PERSON + '|' + SCOPE, 'scope_key': SCOPE,
                'revision_id': 'rev-rel-0', 'revision': 1}
    rel_rev = {'_id': 'rev-rel-0', 'entity_key': 'relationship:' + PERSON + '|' + SCOPE,
               'scope_key': SCOPE, 'mutation_id': 'seed', 'revision': 1,
               'content': {'body': '刚认识，还在试口径。', 'familiarity': 1},
               'source_ids': [], 'parent_revision_id': None}
    persona_head = {'_id': 'persona:P1|global-safe', 'scope_key': 'global-safe',
                    'revision_id': 'rev-persona-0', 'revision': 1}
    persona_rev = {'_id': 'rev-persona-0', 'entity_key': 'persona:P1|global-safe',
                   'scope_key': 'global-safe', 'mutation_id': 'seed', 'revision': 1,
                   'content': {'body': PERSONA_BODY}, 'source_ids': [], 'parent_revision_id': None}
    data = {'scenes': [scene], 'messages': [inbound, outbound], 'memory_units': [summary, monologue],
            'state_heads': [rel_head, persona_head], 'state_revisions': [rel_rev, persona_rev]}
    data.update(overrides)
    return data


def episode(selected=(SUMMARY,), monologue=(MONO,), base='rev-rel-0', ep_id='ep1'):
    return {'_id': ep_id, 'scene_id': SCENE, 'person_id': PERSON, 'scope_key': SCOPE,
            'policy_epoch': EPOCH, 'monologue_refs': list(monologue), 'revision': 1,
            'manifest': {'relationship_revision': base, 'selected': list(selected)}}


def head_pair(store):
    return store.head('relationship:' + PERSON, SCOPE)


def audit_of(store, kind):
    return [row for row in store.db.audit_events.rows.values() if row['type'] == kind]


def add_row(store, collection, row):
    '''走真 put：假库和真 Mongo（集合校验要 schema_version）都能收。'''
    store.put(collection, row, stream='p2')


def seed_real(store, data=None):
    '''把同一批夹具灌进真库（操作员那侧的定向检查用）。'''
    for name, docs in (data or rows()).items():
        for doc in docs:
            store.put(name, doc, stream='p2')


# ── 写入腿 ──────────────────────────────────────────────────────────
def w1_summary_becomes_relationship_source():
    store = bind_store(rows())
    result = MemoryService(store).commit_understanding(episode(), '他把日子说定了，工具我带，不用再催。')
    assert result['state'] == 'COMMITTED', result
    assert result['source_ids'] == [MONO, SUMMARY], result
    assert result['auto_source_ids'] == [SUMMARY], result
    head, revision = head_pair(store)
    assert head['revision_id'] == result['accepted_revision']
    assert revision['source_ids'] == [MONO, SUMMARY]
    assert set(revision['processed_source_ids']) >= {INBOUND, OUTBOUND}, revision
    logged = audit_of(store, 'understanding.result')
    assert logged and logged[-1]['payload']['auto_source_ids'] == [SUMMARY], logged
    return '摘要写进关系版本，来源链落到两条原文'


def w2_unshown_summary_is_not_cited():
    store = bind_store(rows())
    result = MemoryService(store).commit_understanding(episode(selected=[]), '先记着，不催。')
    assert result['state'] == 'COMMITTED', result
    assert result['source_ids'] == [MONO] and result['auto_source_ids'] == [], result
    return '本轮没展示过的摘要不得混进来源'


def w3_shown_but_unusable_is_not_cited():
    notes = []
    for label, patch in (('已失效', {'status': 'superseded'}),
                         ('换了纪元', {'policy_epoch': EPOCH + 1}),
                         ('不在 kind 白名单', {'kind': 'chat_chunk'})):
        store = bind_store(rows())
        store.db.memory_units.rows[SUMMARY].update(patch)
        result = MemoryService(store).commit_understanding(episode(), '口径先不动。')
        assert result['state'] == 'COMMITTED', (label, result)
        assert result['auto_source_ids'] == [], (label, result)
        assert result['source_ids'] == [MONO], (label, result)
        notes.append(label)
    return '展示过但 %s 的条目都不登记，提交本身照旧' % '／'.join(notes)


def w4_foreign_monologue_still_denied():
    store = bind_store(rows())
    store.db.memory_units.rows[MONO]['episode_id'] = 'ep-other'
    try:
        MemoryService(store).commit_understanding(episode(), '随便写点什么。')
    except Denied as exc:
        assert 'UNDERSTANDING_SOURCE_NOT_CURRENT' in str(exc), exc
        assert not audit_of(store, 'understanding.result'), '被拒的提交不该留下结果审计'
        return '独白不是本 episode 的仍然直接拒（原行为未松）'
    raise AssertionError('应当 Denied')


def w5_same_evidence_is_audited_not_fatal():
    store = bind_store(rows())
    MemoryService(store).commit_understanding(episode(), '他把日子说定了。')
    before = head_pair(store)[0]['revision_id']
    # 同一轮被 feedback／续跑重新处理：独白 root 还是那条入站，摘要盖的也是同一批。
    add_row(store, 'memory_units', {'_id': 'mono-ep2:0', 'kind': 'monologue', 'episode_id': 'ep2',
                                    'scope_key': SCOPE, 'policy_epoch': EPOCH, 'status': 'active',
                                    'epistemic_type': 'character_interpretation',
                                    'body_markdown': '同一件事，没新料。', 'source_event_ids': ['evt1'],
                                    'revision': 1})
    result = MemoryService(store).commit_understanding(
        episode(monologue=['mono-ep2:0'], base=before, ep_id='ep2'), '同一批原文，再写一版说法。')
    assert result['state'] == 'NOT_COMMITTED', result
    assert 'NO_NEW_SOURCE_EVENTS' in result['reason'], result
    assert head_pair(store)[0]['revision_id'] == before, '头版本不该被动'
    assert audit_of(store, 'understanding.result')[-1]['payload']['state'] == 'NOT_COMMITTED'
    return '同一批原文再来一次 → 审计过的 NOT_COMMITTED，不抛异常打断本轮'


def w6_stale_base_is_audited_not_fatal():
    store = bind_store(rows())
    MemoryService(store).commit_understanding(episode(), '第一版理解。')
    # 第二个 episode 还拿着旧 base_id（并发／重跑），必须降级而不是把整轮打成 FAILED_RUNTIME。
    add_row(store, 'memory_units', {'_id': 'mono-ep3:0', 'kind': 'monologue', 'episode_id': 'ep3',
                                    'scope_key': SCOPE, 'policy_epoch': EPOCH, 'status': 'active',
                                    'epistemic_type': 'character_interpretation', 'body_markdown': '新料。',
                                    'source_event_ids': ['evt9'], 'revision': 1})
    add_row(store, 'messages', {'_id': 'in-ep3', 'scene_id': SCENE, 'scope_key': SCOPE,
                                'policy_epoch': EPOCH, 'scene_seq': 9, 'direction': 'inbound',
                                'author': PERSON, 'text': '改主意了，周五去', 'platform_event_id': 'evt9',
                                'revision': 1})
    result = MemoryService(store).commit_understanding(
        episode(monologue=['mono-ep3:0'], base='rev-rel-0', ep_id='ep3'), '他改主意了。')
    assert result['state'] == 'NOT_COMMITTED', result
    assert 'BASE_REVISION_STALE' in result['reason'], result
    assert result['body'] == '他改主意了。', '未提交的正文要留在审计里，角色才知道自己说过什么'
    return '头版本被推前 → NOT_COMMITTED + 原因，正文进审计'


def w7_old_no_change_paths_unchanged():
    store = bind_store(rows())
    service = MemoryService(store)
    assert service.commit_understanding(episode(), '不更新')['state'] == 'NO_CHANGE'
    assert service.commit_understanding(episode(), '刚认识，还在试口径。')['state'] == 'NO_CHANGE'
    try:
        service.commit_understanding(episode(), '   ')
        raise AssertionError('应当 Denied')
    except Denied as exc:
        assert 'EMPTY_UNDERSTANDING' in str(exc), exc
    assert head_pair(store)[0]['revision_id'] == 'rev-rel-0', '三条路径都不该动头版本'
    return '不更新／同文／空正文三条原路径行为不变'


def w8_sources_bottom_out_at_real_messages():
    store = bind_store(rows())
    MemoryService(store).commit_understanding(episode(), '他说周三，我说工具我带。')
    revision = head_pair(store)[1]
    ids = set(revision['processed_source_ids'])
    assert ids, revision
    for source in sorted(ids):
        # 来源根可以是消息 _id，也可以是消息的 platform_event_id（Store.mutate 就是这么落根的）；
        # 两种都必须回读得到真实原文行，不接受凭空的编号。
        assert (store.db.messages.find_one({'_id': source})
                or store.db.messages.find_one({'platform_event_id': source})), \
            '来源根回读不到真实原文行：%s' % source
    assert {INBOUND, OUTBOUND} <= ids, '摘要盖的两条原文必须都在里面' % ()
    return '关系版本的每个来源根都能回读成真实 messages 行（不编造来源）'


# ── 读取腿：下一轮能不能认出这条摘要 ──────────────────────────────
def prepare(store):
    current = {'event_id': 'evt2', 'scene_id': SCENE, 'person_id': PERSON, 'text': '那工具谁带？'}
    # 本轮新输入也得先落一行，否则 prepare 认不出 source。
    add_row(store, 'messages', {'_id': 'in-' + episode_id(current), 'scene_id': SCENE,
                                'scope_key': SCOPE, 'policy_epoch': EPOCH, 'scene_seq': 9,
                                'direction': 'inbound', 'author': PERSON, 'text': current['text'],
                                'platform_event_id': 'evt2', 'revision': 1})
    return ContextBuilder(store, retrieval=None).prepare(current)


def r1_summary_reaches_next_turn():
    store = bind_store(rows())
    _system, context, manifest = prepare(store)
    entry = next((m for m in context['memories'] if m['_id'] == SUMMARY), None)
    assert entry, context['memories']
    assert entry['kind'] == 'dialogue_summary', entry
    assert entry['epistemic_type'] == 'derived_summary', entry
    assert entry['source_window'] == [7, 8], entry
    assert entry['generated_at'] == '2026-09-24T06:05:00+00:00', entry
    assert entry['source_event_ids'] == [INBOUND, OUTBOUND], entry
    assert SUMMARY in manifest['selected'], manifest
    return '下一轮能看到这条摘要是什么、盖了哪一段、什么时候生成、原文是谁'


def r2_rules_explain_how_to_read_it():
    store = bind_store(rows())
    _system, context, _manifest = prepare(store)
    rules = context['memory_source_rules']
    assert 'derived_summary' in rules and 'source_window' in rules, rules
    assert 'source_event_ids' in rules, rules
    route = context['understanding_update_from_program']['route']
    assert 'derived_summary' in route and '未提交' in route, route
    return '读法说明与提交口径都写清了：转述不是新经历，来源可回读'


def r3_epistemic_order_is_kept():
    store = bind_store(rows())
    add_row(store, 'memory_units', {'_id': 'a-chunk', 'kind': 'chat_chunk', 'scope_key': SCOPE,
                                    'policy_epoch': EPOCH, 'status': 'active',
                                    'epistemic_type': 'reported_speech', 'speaker': PERSON,
                                    'body_markdown': '我周三去修雾灯', 'scene_seq': 7,
                                    'segment_index': 0, 'segment_count': 1,
                                    'source_event_ids': [INBOUND], 'revision': 1})
    _system, context, _manifest = prepare(store)
    order = [m['_id'] for m in context['memories']]
    assert order == [MONO, SUMMARY, 'a-chunk'], order
    return '排序：角色看法 → 程序转述 → 人物原话，摘要不靠 recency 抢位'


def r4_relationship_read_path_untouched():
    store = bind_store(rows())
    _system, context, manifest = prepare(store)
    assert context['relationship']['body'] == '刚认识，还在试口径。', context['relationship']
    assert manifest['relationship_revision'] == 'rev-rel-0', manifest
    return '读取腿没动关系口径：下一轮仍按 head 版本读'




# ── P2 第二片：自适应触发、群内归属与更正 ────────────────────────────────
import threading
from datetime import datetime, timezone

from asuna import summary_attribution, summary_trigger                  # noqa: E402
from asuna.dialogue_summary import DialogueSummarizer                   # noqa: E402
from asuna.memory_indexer import MemoryIndexer                          # noqa: E402

GROUP = 'grp-1'
GROUP_SCOPE = 'scene:grp-1'
PERSON_B = 'qq:B'
SLOW = 'dm-slow'
SLOW_SCOPE = 'scene:dm-slow'
BUSY = 'grp-busy'
BUSY_SCOPE = 'scene:grp-busy'
COLD = 'grp-cold'
COLD_SCOPE = 'scene:grp-cold'
T0 = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc).timestamp()


def _iso(moment):
    return datetime.fromtimestamp(moment, timezone.utc).isoformat()


def _scene(scene_id, kind, members, start_seq, sequence):
    return {'_id': scene_id, 'kind': kind, 'members': members, 'scope_key': 'scene:' + scene_id,
            'policy_epoch': EPOCH, 'sequence': sequence, 'summary_start_seq': start_seq,
            'revision': 1}


def _in(scene, seq, author, text, at, event=None, **extra):
    row = {'_id': 'in-%s-%d' % (scene, seq), 'scene_id': scene, 'scope_key': 'scene:' + scene,
           'policy_epoch': EPOCH, 'scene_seq': seq, 'direction': 'inbound', 'author': author,
           'text': text, 'platform_event_id': 'evt-%s-%d' % (scene, seq),
           'occurred_at': _iso(at), 'received_at': _iso(at), 'revision': 1}
    if event:
        row['event'] = event
    row.update(extra)
    return row


def _out(scene, seq, text, at, **extra):
    row = {'_id': '%s:speak:%d' % (scene, seq), 'scene_id': scene, 'scope_key': 'scene:' + scene,
           'policy_epoch': EPOCH, 'scene_seq': seq, 'direction': 'outbound', 'author': 'xiaoman',
           'text': text, 'delivery_state': 'DELIVERED', 'phase': 'SPEAK',
           'receipt_at': _iso(at), 'revision': 1}
    row.update(extra)
    return row


def _heads(scope, persons):
    heads, revisions = [], []
    for person in persons:
        key = 'relationship:' + person + '|' + scope
        heads.append({'_id': key, 'scope_key': scope, 'revision_id': 'rev-rel-' + person,
                      'revision': 1})
        revisions.append({'_id': 'rev-rel-' + person, 'entity_key': key, 'scope_key': scope,
                          'mutation_id': 'seed', 'revision': 1,
                          'content': {'body': '当前授权场景里的参与者，口径还在试。',
                                      'familiarity': 1},
                          'source_ids': [], 'parent_revision_id': None})
    return heads, revisions


def _persona():
    return ([{'_id': 'persona:P1|global-safe', 'scope_key': 'global-safe',
              'revision_id': 'rev-persona-0', 'revision': 1}],
            [{'_id': 'rev-persona-0', 'entity_key': 'persona:P1|global-safe',
              'scope_key': 'global-safe', 'mutation_id': 'seed', 'revision': 1,
              'content': {'body': PERSONA_BODY}, 'source_ids': [], 'parent_revision_id': None}])


def _scaffold(scene_id, kind, persons, messages, start_seq, sequence):
    heads, revisions = _heads('scene:' + scene_id, persons)
    persona_heads, persona_revs = _persona()
    return {'scenes': [_scene(scene_id, kind, list(persons) + ['xiaoman'], start_seq, sequence)],
            'messages': messages, 'memory_units': [],
            'state_heads': heads + persona_heads, 'state_revisions': revisions + persona_revs,
            'identities': [{'_id': PERSON, 'person_id': PERSON, 'platform': 'qq',
                            'account_id': '10001', 'display_name': '老陈', 'revision': 1},
                           {'_id': PERSON_B, 'person_id': PERSON_B, 'platform': 'qq',
                            'account_id': '10002', 'display_name': '小舟', 'revision': 1}]}


def group_rows(**overrides):
    """群现场：A 起话、B 应答、角色送达；A 的更正另给（correction_row）。"""
    data = _scaffold(GROUP, 'group', [PERSON, PERSON_B],
                     [_in(GROUP, 11, PERSON, '雾灯我周三去修，谁有空搭把手？', T0),
                      _in(GROUP, 12, PERSON_B, '我去，工具我带', T0 + 25),
                      _out(GROUP, 13, '那我记周三', T0 + 40, reply_to='in-%s-11' % GROUP)],
                     10, 13)
    data.update(overrides)
    return data


def correction_row(at=None):
    """A 用真实 reply 链更正自己那句：对象取得到，所以按 reply_link 认定，不是猜。"""
    return _in(GROUP, 14, PERSON, '更正一下：周三不行，改周五',
               T0 + 55 if at is None else at,
               {'group_context': {'reply_to': 'evt-%s-11' % GROUP,
                                  'reply_message_id': 'in-%s-11' % GROUP,
                                  'topic_id': 'evt-%s-11' % GROUP, 'mentioned_account_ids': []}})


def slow_rows():
    """慢私聊：半小时一条，两条刚攒起来——旧口径那 120 秒在这儿是抢话。"""
    return _scaffold(SLOW, 'dm', [PERSON],
                     [_in(SLOW, 5, PERSON, '早，今天先不动雾灯', T0 - 3600,
                          summary_batch_id='summary-old'),
                      _in(SLOW, 6, PERSON, '我下班去趟修理厂', T0 - 130),
                      _out(SLOW, 7, '行，我知道了', T0 - 120)], 0, 7)


def busy_rows():
    """快群：5 秒一条已经攒满窗口，安静线还没到，但批不可能比窗口更大。"""
    messages = [_in(BUSY, 21 + index, PERSON if index % 2 == 0 else PERSON_B,
                    '第 %d 条：雾灯这事就这么办' % index, T0 + index * 5)
                for index in range(8)]
    return _scaffold(BUSY, 'group', [PERSON, PERSON_B], messages, 20, 28)


def cold_rows():
    """全新场景：一个真实间隔都没有，先验值不该为一句「在吗」就动手。"""
    return _scaffold(COLD, 'group', [PERSON], [_in(COLD, 3, PERSON, '在吗', T0 - 300)], 0, 3)


class FakeEvidence:
    def __init__(self):
        self.rows = []

    def record(self, kind, payload):
        self.rows.append({'type': kind, 'payload': payload})
        return kind

    def kinds(self):
        return [row['type'] for row in self.rows]

    def last(self, kind):
        return next((row['payload'] for row in reversed(self.rows) if row['type'] == kind), None)


class FakeLane:
    """摘要那条低优先级 lane 的最小替身：只要锁、模型名与一次有界生成。"""

    def __init__(self, content='老陈说周三去修雾灯，小舟说他去并带工具；老陈随后更正成周五。'):
        self.lock = threading.Lock()
        self.model = {'model': 'fake-summary-model'}
        self.content = content
        self.calls = []

    def generate(self, session, operation, phase, text, system, *, scope_key=None, policy_epoch=None):
        self.calls.append({'session': session, 'operation': operation, 'phase': phase,
                           'text': text, 'system': system, 'scope_key': scope_key,
                           'policy_epoch': policy_epoch})
        return SimpleNamespace(content=self.content, finish_reason='stop', request_refs=['fake-ref'])


def summarizer(store, evidence, lane, scenes=(GROUP,), moment=None):
    return DialogueSummarizer(store, evidence, lane, list(scenes), clock=lambda: moment)


def pending_rows(store, scene_id):
    return list(store.db.messages.find({'scene_id': scene_id, 'summary_batch_id': {'$exists': False}})
                .sort('scene_seq', 1))


def decide_for(store, scene_id, pending, moment, pooled=None, window_rows=8):
    scene = store.db.scenes.find_one({'_id': scene_id})
    profile = summary_trigger.observe(store, scene, now_ts=moment)
    return profile, summary_trigger.decide(profile, pending, pooled_prior=pooled, now_ts=moment,
                                           window_rows=window_rows)


def legacy_rule(pending, moment, oldest_at):
    """上一版写死的口径，原样搬来当反证：≥4 条，或 ≥2 条且最早一条安静 ≥120 秒。"""
    return len(pending) >= 4 or (len(pending) >= 2 and moment - oldest_at >= 120)


def monologue_unit(person, ep_id, scope=GROUP_SCOPE, body='他把日子说定了。'):
    return {'_id': 'mono-%s:0' % ep_id, 'kind': 'monologue', 'episode_id': ep_id,
            'scope_key': scope, 'policy_epoch': EPOCH, 'character_id': 'xiaoman',
            'status': 'active', 'epistemic_type': 'character_interpretation',
            'body_markdown': body, 'source_event_ids': ['in-%s-14' % GROUP], 'revision': 1}


def group_episode(person, selected=(), ep_id='ep-g1', base=None):
    return {'_id': ep_id, 'scene_id': GROUP, 'person_id': person, 'scope_key': GROUP_SCOPE,
            'policy_epoch': EPOCH, 'monologue_refs': ['mono-%s:0' % ep_id], 'revision': 1,
            'manifest': {'relationship_revision': base or ('rev-rel-' + person),
                         'selected': list(selected)}}


def prepare_group(store, person, text, event_id='evt-next'):
    from asuna.ingress import episode_id as _episode_id
    current = {'event_id': event_id, 'scene_id': GROUP, 'person_id': person, 'text': text,
               'group_context': {'reply_message_id': None, 'topic_id': None,
                                 'mentioned_account_ids': []}}
    add_row(store, 'messages', {'_id': 'in-' + _episode_id(current), 'scene_id': GROUP,
                                'scope_key': GROUP_SCOPE, 'policy_epoch': EPOCH, 'scene_seq': 20,
                                'direction': 'inbound', 'author': person, 'text': text,
                                'platform_event_id': event_id, 'occurred_at': _iso(T0 + 400),
                                'received_at': _iso(T0 + 400), 'revision': 1})
    return ContextBuilder(store, retrieval=None).prepare(current)


def _saved_group_summary(store, moment=T0 + 95):
    evidence, lane = FakeEvidence(), FakeLane()
    saved = summarizer(store, evidence, lane, moment=moment).tick(GROUP)
    return saved, evidence, lane


# ── 触发：阈值来自这个场景自己的节奏 ────────────────────────
def t1_fast_group_uses_its_own_pause():
    store = bind_store(group_rows())
    pending = pending_rows(store, GROUP)
    assert len(pending) == 3, pending
    profile, decision = decide_for(store, GROUP, pending, T0 + 95)
    assert decision['fire'] and 'pause_anomalous' in decision['signals'], decision
    assert decision['quiet_source'] == 'observed', decision
    assert 20 <= decision['quiet_after'] <= 60, decision
    assert profile['burst_rows'] == 3 and decision['cluster_closed'], (profile, decision)
    assert not legacy_rule(pending, T0 + 95, T0), '反证：旧口径在这一批上根本不动手'
    return '快群里 3 条＋安静 55 秒：按这个群自己的停顿线（%.0fs）动手，旧口径还在等第 4 条' % decision['quiet_after']


def t2_slow_dialogue_does_not_get_interrupted():
    store = bind_store(slow_rows())
    pending = pending_rows(store, SLOW)
    assert len(pending) == 2, pending
    _profile, decision = decide_for(store, SLOW, pending, T0)
    assert not decision['fire'] and decision['hold'] == 'scene_still_talking', decision
    assert decision['quiet_after'] > 1000, decision
    assert legacy_rule(pending, T0, T0 - 130), '反证：旧口径的 120 秒在这儿会抢话'
    return '慢私聊里两条＋安静 120 秒：按它自己半小时的节奏还得等，旧口径已经动手了'


def t6_mid_burst_never_summarizes_except_window_cap():
    store = bind_store(group_rows())
    pending = pending_rows(store, GROUP)
    _profile, decision = decide_for(store, GROUP, pending, T0 + 50)   # 最新一条才 10 秒前
    assert not decision['fire'] and decision['hold'] == 'scene_still_talking', decision
    assert decision['settled'] is False and 'pending_stale' not in decision['signals'], decision
    busy = bind_store(busy_rows())
    four = [row for row in pending_rows(busy, BUSY) if row['scene_seq'] <= 24]
    _profile, mid = decide_for(busy, BUSY, four, T0 + 15)             # 第四条刚落库
    assert not mid['fire'] and mid['settled'] is False, mid
    assert legacy_rule(four, T0 + 15, T0), '反证：旧口径凑够四条就动手，人还在连着发也照整理'
    _profile, capped = decide_for(busy, BUSY, pending_rows(busy, BUSY), T0 + 40)
    assert capped['settled'] is False and 'window_full' in capped['signals'], capped
    return '话说完之前不整理（旧口径凑够四条就动手）；只有窗口顶满这一条结构上限会打断'


def t3_full_window_is_structural_not_tuned():
    store = bind_store(busy_rows())
    pending = pending_rows(store, BUSY)
    assert len(pending) == DialogueSummarizer.WINDOW_ROWS, pending
    _profile, decision = decide_for(store, BUSY, pending, T0 + 40)
    assert decision['fire'] and 'window_full' in decision['signals'], decision
    assert 'pause_anomalous' not in decision['signals'], decision
    assert decision['quiet_after'] == summary_trigger.QUIET_FLOOR_SECONDS, decision
    return '攒满窗口就动手：这条是结构上限（%d 行），跟任何调出来的停顿线无关' % DialogueSummarizer.WINDOW_ROWS


def t4_cold_start_waits_then_borrows_a_prior():
    store = bind_store(cold_rows())
    pending = pending_rows(store, COLD)
    _profile, decision = decide_for(store, COLD, pending, T0)
    assert not decision['fire'], decision
    assert decision['hold'] == 'cold_start_needs_more_than_a_fragment', decision
    assert decision['quiet_source'] == 'seed', decision
    group_store = bind_store(group_rows())
    group_profile, _ = decide_for(group_store, GROUP, pending_rows(group_store, GROUP), T0 + 95)
    prior = summary_trigger.pooled({GROUP: group_profile}, exclude=COLD)
    assert prior['source'] == 'pooled_prior' and prior['samples'] >= 1, prior
    _profile2, decision2 = decide_for(store, COLD, pending, T0, pooled=prior)
    assert decision2['fire'] and decision2['quiet_source'] == 'pooled_prior', decision2
    return '新场景先不为一句「在吗」动手；同部署别的场景实测到节奏后，触发点换成实测值'


def t5_group_tick_saves_attribution_and_marks_sources():
    data = group_rows()
    data['messages'] = data['messages'] + [correction_row()]
    store = bind_store(data)
    saved, evidence, lane = _saved_group_summary(store)
    assert saved and saved['kind'] == 'dialogue_summary', saved
    assert saved['participants'] == sorted([PERSON, PERSON_B, 'xiaoman']), saved
    assert saved['source_by_speaker'][PERSON] == ['in-%s-11' % GROUP, 'in-%s-14' % GROUP], saved
    assert saved['source_window'] == [11, 14], saved
    assert saved['attribution']['multi_speaker'] is True, saved
    fix = saved['attribution']['corrections'][0]
    assert fix['corrects'] == 'in-%s-11' % GROUP and fix['self_correction'], fix
    assert fix['target_resolution'] == 'reply_link' and fix['actor'] == PERSON, fix
    assert saved['trigger']['signals'], saved
    for row in data['messages']:
        marked = store.db.messages.find_one({'_id': row['_id']})['summary_batch_id']
        assert marked == saved['_id'], row['_id']
    assert 'summary.saved' in evidence.kinds(), evidence.kinds()
    assert '老陈' in lane.calls[0]['text'] and '小舟' in lane.calls[0]['text'], lane.calls[0]['text']
    assert 'in-%s-11' % GROUP in lane.calls[0]['text'], '程序算出的归属要一起给模型，不让它自己认领'
    return '群场景一轮 tick：摘要落库带上归属与更正，四条原文都标了批次'


# ── 归属与更正：谁的话算谁，被更正的要看得见 ────────────────
def _summary_unit(unit_id, body, sources, participants, window):
    return {'_id': unit_id, 'kind': 'dialogue_summary', 'scope_key': GROUP_SCOPE,
            'policy_epoch': EPOCH, 'character_id': 'xiaoman', 'epistemic_type': 'derived_summary',
            'status': 'active', 'body_markdown': body, 'source_event_ids': sources,
            'scene_id': GROUP, 'source_window': window, 'participants': participants,
            'generated_at': _iso(T0 + 60), 'embedding_status': 'READY', 'revision': 1}


def a1_summary_about_someone_else_is_not_my_source():
    data = group_rows()
    data['messages'] = data['messages'] + [correction_row()]
    store = bind_store(data)
    saved = _summary_unit('summary-ab', '老陈说周三去修雾灯，小舟说他去并带工具。',
                          ['in-%s-11' % GROUP, 'in-%s-12' % GROUP],
                          [PERSON, PERSON_B, 'xiaoman'], [11, 12])
    add_row(store, 'memory_units', saved)
    add_row(store, 'memory_units', monologue_unit(PERSON, 'ep-g1'))
    both = MemoryService(store).commit_understanding(
        group_episode(PERSON, selected=[saved['_id']]), '他改口周五了。')
    assert both['state'] == 'COMMITTED' and both['auto_source_ids'] == [saved['_id']], both
    assert both['auto_source_skipped'] == [], both
    only_b = _summary_unit('summary-b-only', '小舟说他去，工具他带。', ['in-%s-12' % GROUP],
                           [PERSON_B, 'xiaoman'], [12, 12])
    add_row(store, 'memory_units', only_b)
    add_row(store, 'memory_units', monologue_unit(PERSON, 'ep-g2', body='小舟热心，但这事老陈没定。'))
    moved = store.head('relationship:' + PERSON, GROUP_SCOPE)[0]['revision_id']
    result = MemoryService(store).commit_understanding(
        group_episode(PERSON, selected=['summary-b-only'], ep_id='ep-g2', base=moved),
        '小舟愿意去。')
    # 盖不到 A 的摘要不算 A 的证据，这一轮就没有新来源：审计过的未提交，不是异常
    assert result['state'] == 'NOT_COMMITTED' and 'NO_NEW_SOURCE_EVENTS' in result['reason'], result
    assert result['auto_source_ids'] == [], result
    assert result['auto_source_skipped'] == [{'id': 'summary-b-only',
                                              'reason': 'person_not_in_participants'}], result
    assert store.head('relationship:' + PERSON, GROUP_SCOPE)[0]['revision_id'] == moved, \
        '没登记成来源就不该动 A 这条关系的头版本'
    add_row(store, 'memory_units', monologue_unit(PERSON_B, 'ep-g3', body='我去，工具我带。'))
    covered = MemoryService(store).commit_understanding(
        group_episode(PERSON_B, selected=['summary-b-only'], ep_id='ep-g3'), '工具归我。')
    assert covered['auto_source_ids'] == ['summary-b-only'], covered
    return '只盖了别人的摘要照样给 A 看，但不算 A 的证据（未提交带原因）；盖到 B 的那条对 B 就算'


def stale_summary_rows():
    '''早一批已经被 summary-old 盖住，后一批里 A 更正了那句。'''
    data = group_rows()
    data['memory_units'] = [_summary_unit('summary-old', '老陈说他周三去修雾灯。',
                                          ['in-%s-11' % GROUP], [PERSON, 'xiaoman'], [11, 11])]
    data['messages'] = [dict(data['messages'][0], summary_batch_id='summary-old')] \
        + data['messages'][1:] + [correction_row()]
    return data


def a3_same_display_name_stays_two_people():
    rows = [_in('grp-names', 1, PERSON, '雾灯我周三去修', T0),
            _in('grp-names', 2, 'qq:B1', '我去', T0 + 25),
            _in('grp-names', 3, 'qq:C1', '我也去', T0 + 40)]
    data = _scaffold('grp-names', 'group', [PERSON, 'qq:B1', 'qq:C1'], rows, 0, 3)
    for person, display in ((PERSON, '老陈'), ('qq:B1', '小舟'), ('qq:C1', '小舟')):
        data['identities'] = [row for row in data['identities'] if row['_id'] != person] + [
            {'_id': person, 'person_id': person, 'platform': 'qq', 'account_id': 'a' + person[-1],
             'display_name': display, 'revision': 1}]
    store = bind_store(data)
    lane = FakeLane()
    saved = summarizer(store, FakeEvidence(), lane, scenes=('grp-names',),
                       moment=T0 + 95).tick('grp-names')
    assert saved and saved['participants'] == sorted([PERSON, 'qq:B1', 'qq:C1']), saved
    assert saved['source_by_speaker']['qq:B1'] == ['in-grp-names-2'], saved
    assert saved['source_by_speaker']['qq:C1'] == ['in-grp-names-3'], saved
    assert '小舟（qq:B1）' in lane.calls[0]['text'], '同名要带 person_id，否则模型会把两个人顺成一个'
    assert '小舟（qq:C1）' in lane.calls[0]['text'], lane.calls[0]['text']
    return '两个同名的人不会被顺成一个：归属按 person_id，给模型的标签也各自带 ID'


def a2_correction_marks_the_earlier_summary_as_stale():
    store = bind_store(stale_summary_rows())
    saved, evidence, _lane = _saved_group_summary(store)
    assert saved and saved['source_window'] == [12, 14], saved
    old = store.db.memory_units.find_one({'_id': 'summary-old'})
    assert old['corrected_by'] == ['in-%s-14' % GROUP], old
    assert old['body_markdown'] == '老陈说他周三去修雾灯。', '只追加标注，不改写旧转述'
    assert 'summary.corrected' in evidence.kinds(), evidence.kinds()
    add_row(store, 'memory_units', monologue_unit(PERSON, 'ep-g1'))
    result = MemoryService(store).commit_understanding(
        group_episode(PERSON, selected=['summary-old']), '他改周五了，旧那句只当历史。')
    assert result['auto_source_ids'] == ['summary-old'], result
    assert result['auto_stale_source_ids'] == ['summary-old'], result
    return '更正指向已被旧摘要盖住的原文：那条摘要追加 corrected_by，仍算来源但记为 stale'


def r5_group_next_turn_shows_attribution_and_correction():
    data = group_rows()
    data['messages'] = data['messages'] + [correction_row()]
    store = bind_store(data)
    saved, _evidence, _lane = _saved_group_summary(store)
    _system, context, manifest = prepare_group(store, PERSON, '那到底周几去？')
    entry = next((m for m in context['memories'] if m['_id'] == saved['_id']), None)
    assert entry, context['memories']
    assert entry['participants'] == sorted([PERSON, PERSON_B, 'xiaoman']), entry
    assert entry['attribution']['corrections'][0]['corrects'] == 'in-%s-11' % GROUP, entry
    assert saved['_id'] in manifest['selected'], manifest
    rules = context['memory_source_rules']
    assert 'participants' in rules and '更正' in rules, rules
    assert 'participants' in context['understanding_update_from_program']['route']
    return '下一轮在群里也认得出这条摘要盖了谁、里面哪句被更正过'


def e1_the_loop_actually_closes_in_a_group():
    data = group_rows()
    data['messages'] = data['messages'] + [correction_row()]
    store = bind_store(data)
    saved, _evidence, _lane = _saved_group_summary(store)
    _system, context, manifest = prepare_group(store, PERSON, '那到底周几去？')
    assert saved['_id'] in manifest['selected'], '下一轮真给角色看过了，才有资格当来源'
    add_row(store, 'memory_units', monologue_unit(PERSON, 'ep-g1', body='他自己把日子改成周五了。'))
    result = MemoryService(store).commit_understanding(
        group_episode(PERSON, selected=manifest['selected']), '他自己把日子改成周五了。')
    assert result['state'] == 'COMMITTED', result
    assert result['auto_source_ids'] == [saved['_id']], result
    revision = store.head('relationship:' + PERSON, GROUP_SCOPE)[1]
    assert revision['source_ids'] == ['mono-ep-g1:0', saved['_id']], revision
    roots = set(revision['processed_source_ids'])
    assert {row['_id'] for row in data['messages']} <= roots, roots
    for root in sorted(roots):
        assert (store.db.messages.find_one({'_id': root})
                or store.db.messages.find_one({'platform_event_id': root})), root
    assert audit_of(store, 'understanding.result')[-1]['payload']['auto_source_ids'] == [saved['_id']]
    return '群场景闭环跑通：触发→整理→保存→下一轮使用→登记成来源，每个来源根都回读得到原文'


def g1_indexer_hands_every_scene_to_the_summarizer():
    store = bind_store(group_rows())
    store.config['embedding'] = {'base_url': 'http://stub/v1', 'model': 'stub', 'dimensions': 768}
    lane = FakeLane()
    indexer = MemoryIndexer(store, FakeEvidence(), [SCENE, GROUP], summary_lane=lane,
                            summary_scenes=[SCENE, GROUP])
    assert indexer.summarizer.scene_ids == [SCENE, GROUP], indexer.summarizer.scene_ids
    legacy = MemoryIndexer(store, FakeEvidence(), SCENE, summary_lane=lane, summary_scene=SCENE)
    assert legacy.summarizer.scene_ids == [SCENE], '旧接线参数还得能用'
    assert summarizer(store, FakeEvidence(), lane, moment=T0).tick('other-scene') is None
    return '索引线程把本机场景与每个授权群都交给摘要器；不是自己那份场景直接不判断'


EXTRA_CASES = [t1_fast_group_uses_its_own_pause, t2_slow_dialogue_does_not_get_interrupted,
               t6_mid_burst_never_summarizes_except_window_cap,
               t3_full_window_is_structural_not_tuned, t4_cold_start_waits_then_borrows_a_prior,
               t5_group_tick_saves_attribution_and_marks_sources,
               a1_summary_about_someone_else_is_not_my_source,
               a3_same_display_name_stays_two_people,
               a2_correction_marks_the_earlier_summary_as_stale,
               r5_group_next_turn_shows_attribution_and_correction,
               e1_the_loop_actually_closes_in_a_group,
               g1_indexer_hands_every_scene_to_the_summarizer]


CASES = [w1_summary_becomes_relationship_source, w2_unshown_summary_is_not_cited,
         w3_shown_but_unusable_is_not_cited, w4_foreign_monologue_still_denied,
         w5_same_evidence_is_audited_not_fatal, w6_stale_base_is_audited_not_fatal,
         w7_old_no_change_paths_unchanged, w8_sources_bottom_out_at_real_messages,
         r1_summary_reaches_next_turn, r2_rules_explain_how_to_read_it,
         r3_epistemic_order_is_kept, r4_relationship_read_path_untouched] + EXTRA_CASES


def run_all():
    results = []
    for case in CASES:
        try:
            results.append((case.__name__, True, case()))
        except AssertionError as exc:
            results.append((case.__name__, False, str(exc) or '断言失败'))
        except Exception as exc:            # 假库没接住也要报成失败，不冒充通过
            results.append((case.__name__, False, '%s: %s' % (type(exc).__name__, exc)))
    return results


if __name__ == '__main__':
    for name, ok, note in run_all():
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ' — ' + note if note else ''))
