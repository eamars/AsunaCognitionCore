#!/usr/bin/env python3
"""A2 跨场景只读联动的离线自检：不需要 Mongo、不需要 pytest、不碰网络。

跑法：python3 tools/linked_scenes_offline_check.py

被测的都是**真文件**：scene_links / history_query / discussion_digest 平铺装载，
context.py 与 memory.py 各装进一个临时包（外面垫几个小替身，跟 P3 自检同一套路）。
假集合只实现这批用例真会用到的那一小块查询语言；真 Mongo 那一层由操作员跑 tests/。

每条用例钉的是「放宽了什么、没放宽什么」：
读得到跨场景的原话，同时写权限、场景围栏、历史行上的 author 都不许跟着漂。
"""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get('ASUNA_LINKED_SRC') or os.path.join(ROOT, 'src', 'asuna')
BUNDLE = os.path.join(ROOT, 'docs', 'development_plans', 'ADR-001-asuna_v2_v1_handoff')
os.environ.setdefault('ASUNA_BUNDLE', BUNDLE)
sys.path.insert(0, SRC)

import scene_links as sl                                              # noqa: E402
import history_query as hq                                            # noqa: E402
import discussion_digest as dd                                        # noqa: E402

LOCAL = 'local-dm'
QQ = 'qq:3768713357:dm:673225019'
ME = 'local-user'
ALIAS = 'qq:673225019'
ASUNA = 'asuna'
SINCE = '2026-09-01T00:00:00Z'


# ── 假集合：够跑这批查询就行 ───────────────────────────────────────
def _lookup(doc, key):
    node = doc
    for part in key.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _match(doc, flt):
    for key, want in (flt or {}).items():
        if key == '$or':
            if not any(_match(doc, branch) for branch in want):
                return False
        elif key == '$and':
            if not all(_match(doc, branch) for branch in want):
                return False
        else:
            have = _lookup(doc, key)
            if isinstance(want, dict) and '$regex' in want:
                flags = re.I if 'i' in str(want.get('$options', '')) else 0
                if not (isinstance(have, str) and re.search(want['$regex'], have, flags)):
                    return False
                continue
            if isinstance(want, dict):
                for op, arg in want.items():
                    if op == '$in' and have not in arg:
                        return False
                    if op == '$ne' and have == arg:
                        return False
                    if op == '$lt' and not (have is not None and have < arg):
                        return False
                    if op == '$lte' and not (have is not None and have <= arg):
                        return False
                    if op == '$gte' and not (have is not None and have >= arg):
                        return False
                    if op == '$exists' and (have is not None) != bool(arg):
                        return False
            elif have != want:
                return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    out = {'_id': doc['_id']}
    for key in projection:
        value = _lookup(doc, key)
        if value is None:
            continue
        node = out
        parts = key.split('.')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


class Cursor(list):
    def sort(self, key, direction=-1):
        ordered = sorted(self, key=lambda row: (row.get(key) is None, row.get(key)),
                         reverse=direction < 0)
        del self[:]
        self.extend(ordered)
        return self

    def limit(self, count):
        del self[count:]
        return self


class Collection:
    def __init__(self, rows=()):
        self.rows = {row['_id']: dict(row) for row in rows}

    def find(self, flt=None, projection=None, sort=None, limit=0):
        out = [_project(row, projection) for row in self.rows.values() if _match(row, flt)]
        for key, direction in reversed(list(sort or [])):
            out.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=direction < 0)
        return Cursor(out[:limit] if limit else out)

    def find_one(self, flt=None, projection=None):
        rows = list(self.find(flt, projection))
        return rows[0] if rows else None

    def count_documents(self, flt):
        return len([row for row in self.rows.values() if _match(row, flt)])


class Conflict(RuntimeError):
    pass


class DB(dict):
    """既能 db.messages 也能 db['messages']：真 state.mutate 里两种写法都有。"""

    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


class Store:
    def __init__(self, config, rows):
        self.config, self.audits = config, []
        self.db = DB(
            messages=Collection(rows.get('messages', ())), scenes=Collection(rows.get('scenes', ())),
            sink_receipts=Collection(rows.get('sinks', ())),
            identities=Collection(rows.get('identities', ())),
            memory_units=Collection(rows.get('memory_units', ())),
            state_heads=Collection(rows.get('heads', ())),
            state_revisions=Collection(rows.get('revisions', ())),
            tasks=Collection(), plans=Collection(), artifacts=Collection(), episodes=Collection())

    def put(self, collection, document, *, expected=None, stream='state'):
        coll = getattr(self.db, collection)
        doc = dict(document)
        doc['schema_version'] = 1
        current = coll.rows.get(doc['_id'])
        if expected is None:
            if current:
                raise Conflict('DUPLICATE_ID')
            doc['revision'] = 1
        else:
            if not current or current['revision'] != expected:
                raise Conflict('STALE_REVISION')
            doc['revision'] = expected + 1
        coll.rows[doc['_id']] = dict(doc)
        return dict(doc)

    def audit(self, stream, kind, payload, scope='operator'):
        self.audits.append({'stream': stream, 'type': kind, 'payload': payload, 'scope': scope})
        return {}

    def authorize(self, scene_id, person_id):
        scene = self.db.scenes.find_one({'_id': scene_id})
        if not scene or person_id not in scene['members']:
            raise hq.Denied('SCENE_MEMBERSHIP_DENIED')
        return scene

    def head(self, entity, scope):
        row = self.db.state_heads.find_one({'_id': entity + '|' + scope})
        if not row:
            return None
        return row, self.db.state_revisions.find_one({'_id': row['revision_id']})

    def init_head(self, entity, scope, content, sources):
        key = entity + '|' + scope
        if self.db.state_heads.find_one({'_id': key}):
            return None
        revision = self.put('state_revisions', {'_id': 'rev-' + key, 'entity_key': key,
                                               'scope_key': scope, 'content': dict(content),
                                               'source_ids': list(sources),
                                               'processed_source_ids': [],
                                               'parent_revision_id': None}, stream='setup')
        return self.put('state_heads', {'_id': key, 'scope_key': scope,
                                        'revision_id': revision['_id'], 'revision': 1},
                        stream='setup')

    def kinds(self, stream=None):
        return [row['type'] for row in self.audits
                if stream is None or row['stream'] == stream]


PERSONA = '沈小满，24 岁。' + '说话清淡直接，有一点不刻薄的机灵。' * 6


def rows_base():
    return {
        'scenes': [
            {'_id': LOCAL, 'scene_id': LOCAL, 'kind': 'dm', 'members': [ME],
             'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1, 'sequence': 40, 'revision': 1},
            {'_id': QQ, 'scene_id': QQ, 'kind': 'dm', 'members': [ALIAS], 'channel_id': 'qq',
             'scope_key': 'scene:' + QQ, 'policy_epoch': 1, 'sequence': 21, 'revision': 2,
             'channel_account_id': '3768713357'}],
        'identities': [
            {'_id': ME, 'person_id': ME, 'platform': 'local', 'account_id': ME,
             'display_name': '本机用户', 'revision': 1},
            {'_id': ALIAS, 'person_id': ALIAS, 'platform': 'qq', 'account_id': '673225019',
             'revision': 3}],
        'sinks': [{'_id': 'r-l1', 'received_at': '2026-09-25T03:00:05Z', 'kind': 'outbound'}],
        'messages': [
            {'_id': 'in-l1', 'scene_id': LOCAL, 'policy_epoch': 1, 'scene_seq': 10,
             'direction': 'inbound', 'author': ME, 'occurred_at': '2026-09-25T03:00:00Z',
             'text': '本机说的第一句', 'scope_key': 'scene:' + LOCAL},
            {'_id': 'out-l1', 'scene_id': LOCAL, 'policy_epoch': 1, 'scene_seq': 11,
             'direction': 'outbound', 'phase': 'SPEAK', 'author': ASUNA, 'text': '我回的那句',
             'delivery_state': 'DELIVERED', 'receipt': 'r-l1', 'scope_key': 'scene:' + LOCAL},
            # 同一秒、同一个 scene_seq、不同场景：跨场景之后 (时间, scene_seq) 不再是全序
            {'_id': 'in-l2', 'scene_id': LOCAL, 'policy_epoch': 1, 'scene_seq': 20,
             'direction': 'inbound', 'author': ME, 'occurred_at': '2026-09-25T04:07:32Z',
             'text': '关于联动的那句', 'scope_key': 'scene:' + LOCAL,
             'event': {'group_context': {'reply_message_id': 'in-q1'}}},
            {'_id': 'in-q1', 'scene_id': QQ, 'policy_epoch': 1, 'scene_seq': 20,
             'direction': 'inbound', 'author': ALIAS, 'occurred_at': '2026-09-25T04:07:32Z',
             'text': 'QQ 上说的那句', 'scope_key': 'scene:' + QQ},
            {'_id': 'in-q2', 'scene_id': QQ, 'policy_epoch': 1, 'scene_seq': 21,
             'direction': 'inbound', 'author': ALIAS, 'occurred_at': '2026-09-25T04:07:33Z',
             'text': 'QQ 上的第二句', 'scope_key': 'scene:' + QQ},
            {'_id': 'in-q3', 'scene_id': QQ, 'policy_epoch': 1, 'scene_seq': 19,
             'direction': 'inbound', 'author': ALIAS, 'occurred_at': '2026-09-24T02:00:00Z',
             'text': '更早的一句', 'scope_key': 'scene:' + QQ},
            {'_id': 'in-ep-evt-1', 'scene_id': LOCAL, 'policy_epoch': 1, 'scene_seq': 30,
             'direction': 'inbound', 'author': ME, 'occurred_at': '2026-09-25T05:00:00Z',
             'text': '我说过什么', 'scope_key': 'scene:' + LOCAL}],
        'revisions': [{'_id': 'rev-persona', 'entity_key': 'persona:P1|global-safe',
                       'scope_key': 'global-safe', 'revision': 1,
                       'content': {'body': PERSONA}, 'source_ids': [],
                       'parent_revision_id': None},
                      {'_id': 'rev-rel', 'entity_key': 'relationship:local-user|scene:local-dm',
                       'scope_key': 'scene:' + LOCAL, 'revision': 1,
                       'content': {'body': '这是通过本机界面交流的用户。'}, 'source_ids': [],
                       'processed_source_ids': [], 'parent_revision_id': None}],
        'heads': [{'_id': 'persona:P1|global-safe', 'scope_key': 'global-safe',
                   'revision_id': 'rev-persona', 'revision': 1},
                  {'_id': 'relationship:local-user|scene:local-dm', 'scope_key': 'scene:' + LOCAL,
                   'revision_id': 'rev-rel', 'revision': 1}],
    }


def config_base(top=None):
    config = {'timezone': 'Asia/Shanghai',
              'chat': {'scene_id': LOCAL, 'person_id': ME, 'persona': 'P1'},
              'context_links': {LOCAL: [QQ]},
              'canonical_persons': {ALIAS: ME},
              'channels': {'qq': {'account_id': '3768713357',
                                  'routes': {'owner-dm': {'scene_id': QQ, 'person_id': ALIAS,
                                                          'target': {'type': 'dm',
                                                                     'id': '673225019'}}}}}}
    config.update(top or {})
    return config


def store_with(config=None, rows=None):
    store = Store(config if config is not None else config_base(),
                  rows if rows is not None else rows_base())
    return store


TASK_LOCAL = {'scene_id': LOCAL, 'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1}
TASK_QQ = {'scene_id': QQ, 'scope_key': 'scene:' + QQ, 'policy_epoch': 1}


# ── 临时包：真 context.py / 真 memory.py 外面垫替身 ────────────────
STUBS = {
    'config.py': 'from pathlib import Path\nimport os\nBUNDLE=Path(os.environ["ASUNA_BUNDLE"])\n'
                 'ROOT=BUNDLE\n'
                 'def prompt_path(config, name):\n    return BUNDLE/"prompts"/name\n'
                 'def redact_text(text, config):\n    return text\n'
                 'def validate_database(config, database):\n    return "asuna-test"\n',
    'evidence.py': 'import json, hashlib\ndef canonical(value):\n    return json.dumps(value, '
                   'sort_keys=True).encode()\ndef sha(raw):\n    return hashlib.sha256(raw).hexdigest()\n',
    'state.py': 'class Conflict(RuntimeError):\n    pass\nclass Denied(PermissionError):\n    pass\n'
                'class Store:\n    pass\ndef now():\n    return ""\n',
    'peer_context.py': 'def apply_peer_context(context, source):\n    return context\n',
    'ingress.py': 'def episode_id(event):\n    return "ep-" + str(event["event_id"])\n',
    'queue.py': 'import contextlib\n@contextlib.contextmanager\ndef database_effects_lock(name):'
                '\n    yield\n',
}


def load_package(name, real):
    root = tempfile.mkdtemp(prefix=name + '-')
    package = os.path.join(root, name)
    os.makedirs(package)
    open(os.path.join(package, '__init__.py'), 'w').close()
    for module in real:
        shutil.copyfile(os.path.join(SRC, module), os.path.join(package, module))
    for module, body in STUBS.items():
        if module in real:
            continue
        open(os.path.join(package, module), 'w', encoding='utf-8').write(body)
        # 真文件里那些「同包加载失败就退回平铺 import」的口子也要落到替身上：
        # 不然退回平铺时会从 src/asuna 里捞到真 state.py，红在 bson 上而不是红在用例上。
        open(os.path.join(root, module), 'w', encoding='utf-8').write(body)
    sys.path.insert(0, root)
    return __import__('%s.%s' % (name, real[0][:-3]), fromlist=['__init__'])


# 真 state.py 的 mutate 是这道围栏本体，得真跑：给它的两个第三方 import 垫最小替身。
sys.modules.setdefault('bson', types.SimpleNamespace(BSON=object))
_pymongo = types.ModuleType('pymongo')
_pymongo.ASCENDING, _pymongo.MongoClient, _pymongo.ReturnDocument = 1, object, object
_pymongo.WriteConcern = object
_errors = types.ModuleType('pymongo.errors')
_errors.DuplicateKeyError = type('DuplicateKeyError', (RuntimeError,), {})
_pymongo.errors = _errors
sys.modules.setdefault('pymongo', _pymongo)
sys.modules.setdefault('pymongo.errors', _errors)
_state = load_package('a2state', ('state.py',))
Store.mutate = _state.Store.mutate
Denied, Conflict = _state.Denied, _state.Conflict


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ── 1. 配置口径 ─────────────────────────────────────────────────
@case
def c1_links_are_directed_literal_and_bounded():
    links = sl.context_links(config_base())
    one_way = links.get(LOCAL) == [QQ] and QQ not in links
    junk = sl.context_links({'context_links': {'a': ['*', 'a', '', 7, 'b', 'b']}})
    route = sl.context_links({'channels': {'qq': {'routes': {'r': {'scene_id': 's1',
                                                                   'read_scenes': ['s2']}}}}})
    capped = sl.context_links({'context_links': {'a': ['s%d' % i for i in range(30)]}})
    none = sl.readable_scenes({'chat': {}}, LOCAL)
    return (one_way and junk == {'a': ['b']} and route == {'s1': ['s2']}
            and len(capped['a']) == sl.MAX_LINKS and none == []), \
        {'links': links, 'junk': junk, 'route': route, 'capped': len(capped['a']), 'none': none}


@case
def c2_history_reads_the_linked_scene_only_one_way():
    store = store_with()
    service = hq.HistoryQueryService(store)
    here = service.query_for_task(TASK_LOCAL, {'query': '那句', 'since': SINCE})
    there = service.query_for_task(TASK_QQ, {'query': '那句', 'since': SINCE})
    ids = {hit['message_id']: hit['scene_id'] for hit in here['hits']}
    back = {hit['message_id']: hit['scene_id'] for hit in there['hits']}
    return ('in-q1' in ids and ids.get('in-q1') == QQ and 'in-l1' not in back
            and here['scope']['linked_scenes'] == [QQ] and there['scope']['linked_scenes'] == []
            and '联动' in here['text']), {'local_sees': ids, 'qq_sees': back}


@case
def c3_same_second_across_scenes_paginates_without_gaps():
    store = store_with()
    service = hq.HistoryQueryService(store)
    seen, cursor, pages = [], None, 0
    while pages < 15:
        pages += 1
        page = service.query_for_task(TASK_LOCAL, {'query': '', 'since': SINCE, 'limit': 1,
                                                   'include_semantic': False,
                                                   **({'cursor': cursor} if cursor else {})})
        seen += [hit['message_id'] for hit in page['hits']]
        if not page['more']:
            break
        cursor = page['next_cursor']
    wanted = {'in-l1', 'out-l1', 'in-l2', 'in-q1', 'in-q2', 'in-q3', 'in-ep-evt-1'}
    return (sorted(seen) == sorted(wanted) and len(seen) == len(set(seen))), \
        {'seen': seen, 'pages': pages}


@case
def c4_person_filter_follows_the_canonical_person_without_rewriting_rows():
    store = store_with()
    service = hq.HistoryQueryService(store)
    result = service.query_for_task(TASK_LOCAL, {'person': ME, 'since': SINCE, 'limit': 20,
                                                 'include_semantic': False})
    ids = {hit['message_id']: hit for hit in result['hits']}
    authors = {mid: hit['author'] for mid, hit in ids.items()}
    raw = {row['_id']: row['author'] for row in store.db.messages.rows.values()}
    return ('in-q1' in ids and authors.get('in-q1') == ALIAS == raw['in-q1']
            and result['dropped']['wrong_person'] == 0
            and sorted(result['scope']['same_person_ids']) == sorted([ME, ALIAS])), \
        {'authors': authors, 'rows_untouched': raw['in-q1'] == ALIAS}


@case
def c5_cursor_is_bound_to_the_link_set_it_was_issued_under():
    store = store_with()
    page = hq.HistoryQueryService(store).query_for_task(
        TASK_LOCAL, {'query': '那句', 'since': SINCE, 'limit': 2})
    cursor = page['next_cursor'] or hq.HistoryQueryService(store).query_for_task(
        TASK_LOCAL, {'query': '那句', 'since': SINCE, 'limit': 1})['next_cursor']
    unlinked = store_with(config_base(top={'context_links': {}}))
    refused = None
    try:
        hq.HistoryQueryService(unlinked).query_for_task(
            TASK_LOCAL, {'query': '那句', 'since': SINCE, 'limit': 2, 'cursor': cursor})
    except ValueError as exc:
        refused = str(exc)
    return (cursor is not None and refused == 'HISTORY_CURSOR_FILTER_MISMATCH'), {'refused': refused}


@case
def c6_digest_merges_one_person_across_two_scenes_and_keeps_sources():
    store = store_with()
    digest = dd.DiscussionDigestService(store).digest_for_task(
        TASK_LOCAL, {'person': ME, 'since': SINCE, 'limit': 20, 'include_semantic': False})
    cov = digest['coverage']
    people = {person['key']: person for person in digest['participants']}
    replies = {item['message_id']: item for item in digest['replies']}
    one_person = len(digest['participants']) == 1 and ME in people
    return (one_person and people[ME]['messages'] >= 4 and people[ME]['aliases'] == [ALIAS]
            and cov['cross_scene_rows'] >= 3 and sorted(cov['scenes_read']) == sorted([LOCAL, QQ])
            and replies.get('in-l2', {}).get('target_in_scope') is True
            and '联动' in digest['text']), \
        {'people': list(people), 'coverage': {k: cov.get(k) for k in
                                             ('scenes_read', 'cross_scene_rows', 'linked_scenes')},
         'reply': replies.get('in-l2')}


@case
def c7_topic_digest_continues_a_thread_that_crosses_the_edge():
    store = store_with()
    digest = dd.DiscussionDigestService(store).digest_for_task(
        TASK_LOCAL, {'topic': '联动', 'since': SINCE, 'limit': 20, 'include_semantic': False})
    ids = {row: True for row in digest['source_ids']}
    replies = {item['message_id']: item for item in digest['replies']}
    return ('in-l2' in ids and 'in-q1' in ids
            and replies.get('in-l2', {}).get('target_in_scope') is True
            and digest['coverage']['thread_extra'] >= 1), \
        {'source_ids': digest['source_ids'], 'reply': replies.get('in-l2')}


@case
def c8_context_merges_linked_history_by_effective_time():
    module = load_package('a2ctx', ('context.py', 'scene_links.py', 'schedule_rules.py',
                                    'self_state.py', 'vision.py'))
    store = store_with()
    _system, context, manifest = module.ContextBuilder(store, retrieval=None).prepare(
        {'event_id': 'evt-1', 'scene_id': LOCAL, 'person_id': ME, 'text': '我说过什么'})
    history = context['delivered_history']
    ids = [row['_id'] for row in history]
    scene_of = {row['_id']: row.get('scene_id') for row in history}
    note = context.get('linked_scenes_from_program') or {}
    # 出站那条行内没有 receipt_at：只有按 sink 回执（03:00:05）算时间才会排在那句本机话之后
    ordered = ids.index('out-l1') > ids.index('in-l1')
    return ('in-q1' in ids and scene_of.get('in-q1') == QQ and 'in-ep-evt-1' not in ids
            and ordered and ids[-1] in ('in-q2', 'in-l2') and len(history) <= 12
            and note.get('readable') == [QQ] and '不是这个场景里的新输入' in note.get('note', '')
            and manifest['linked_scenes'] == [QQ]), \
        {'ids': ids, 'scenes': scene_of, 'note': bool(note)}


@case
def c9_without_the_config_key_everything_stays_exactly_as_before():
    module = load_package('a2ctx', ('context.py', 'scene_links.py', 'schedule_rules.py',
                                    'self_state.py', 'vision.py'))
    store = store_with(config_base(top={'context_links': {}, 'canonical_persons': {}}))
    _system, context, manifest = module.ContextBuilder(store, retrieval=None).prepare(
        {'event_id': 'evt-1', 'scene_id': LOCAL, 'person_id': ME, 'text': '我说过什么'})
    ids = [row['_id'] for row in context['delivered_history']]
    service = hq.HistoryQueryService(store)
    result = service.query_for_task(TASK_LOCAL, {'query': '那句', 'since': SINCE})
    flt = hq.message_filters(hq._scene_parts({'scene_id': LOCAL, 'scope_key': 'scene:' + LOCAL,
                                              'policy_epoch': 1}), '')[0][2]
    return ('in-q1' not in ids and 'linked_scenes_from_program' not in context
            and manifest['linked_scenes'] == [] and result['scope']['linked_scenes'] == []
            and flt['scene_id'] == LOCAL and 'in-q1' not in {h['message_id'] for h in result['hits']}), \
        {'ids': ids, 'filter_scene_id': flt.get('scene_id')}


@case
def c10_relationship_state_lives_in_one_place_and_sources_stay_fenced():
    store = store_with()
    qq_scene = store.db.scenes.find_one({'_id': QQ})
    target = sl.relationship_target(store.config, store.db, qq_scene, ALIAS)
    # 写：别名场景这一轮把理解写进 canonical 那一份，来源是本轮场景（QQ）里的证据
    store.db.memory_units.rows['mu-q1'] = {
        '_id': 'mu-q1', 'episode_id': 'ep-9', 'scope_key': 'scene:' + QQ, 'policy_epoch': 1,
        'status': 'active', 'kind': 'monologue', 'body_markdown': '他在 QQ 上更正过一次',
        'source_event_ids': ['in-q1'], 'epistemic_type': 'character_interpretation'}
    store.init_head('relationship:local-user', 'scene:' + LOCAL, {'body': '这是通过本机界面交流的用户。'}, [])
    memory = load_package('a2mem', ('memory.py', 'scene_links.py', 'summary_attribution.py'))
    service = memory.MemoryService(store)
    episode = {'_id': 'ep-9', 'scene_id': QQ, 'person_id': ALIAS, 'scope_key': 'scene:' + QQ,
               'policy_epoch': 1, 'monologue_refs': ['mu-q1'],
               'manifest': {'relationship_revision': store.head('relationship:local-user',
                                                                'scene:' + LOCAL)[0]['revision_id'],
                            'relationship_entity_key': 'relationship:local-user|scene:' + LOCAL,
                            'selected': []}}
    result = service.commit_understanding(episode, '他习惯在两个入口说同一件事。')
    head = store.head('relationship:local-user', 'scene:' + LOCAL)
    # 反证：同一轮如果没带上授权联动的 scope（配置删了那条边），mutate 必须拒掉这次跨 scope 的写
    try:
        store.mutate('relationship:local-user', 'scene:' + LOCAL, head[0]['revision_id'],
                     {'body': '不该写进去'}, ['mu-q1'], 'scene:' + QQ, 'op-no-link')
        refused = ''
    except Exception as exc:
        refused = type(exc).__name__
    # 来源越界（既不在目标 scope 也不在授权联动 scope）也要拒
    store.db.memory_units.rows['mu-x'] = dict(store.db.memory_units.rows['mu-q1'],
                                              _id='mu-x', scope_key='scene:other')
    try:
        store.mutate('relationship:local-user', 'scene:' + LOCAL, head[0]['revision_id'],
                     {'body': '不该写进去'}, ['mu-x'], 'scene:' + QQ, 'op-bad-source',
                     linked_scopes=['scene:' + QQ])
        source_refused = ''
    except Exception as exc:
        source_refused = type(exc).__name__
    return (target['entity'] == 'relationship:local-user' and target['scope'] == 'scene:' + LOCAL
            and target['shared'] is True and result['state'] == 'COMMITTED'
            and result['target_scope'] == 'scene:' + LOCAL
            and head[1]['content']['body'] == '他习惯在两个入口说同一件事。'
            and refused == 'Denied' and source_refused == 'Denied'), \
        {'target': target, 'result': {k: result.get(k) for k in ('state', 'target_scope')},
         'refused': refused, 'source_refused': source_refused}


@case
def c11_startup_projections_are_observability_only_and_removal_reverts():
    store = store_with()
    # 启动投影本身（chat.prepare_local_scene / host.prepare_channels）要拉起整个应用装配，
    # 离线这层只钉两件事：投影函数写的是什么，以及启动路径真的调了它们。
    sl.sync_identity_docs(store, store.config)
    sl.sync_scene_docs(store, store.config, [LOCAL, QQ])
    scene = store.db.scenes.find_one({'_id': LOCAL})
    alias = store.db.identities.find_one({'_id': ALIAS})
    chat = io.open(os.path.join(SRC, 'chat.py'), encoding='utf-8').read()
    host = io.open(os.path.join(SRC, 'host.py'), encoding='utf-8').read()
    wired = [('chat 同步身份投影', 'scene_links.sync_identity_docs(store, store.config)' in chat),
             ('chat 同步场景投影', 'scene_links.sync_scene_docs(store, store.config, [scene])' in chat),
             ('chat 的关系 head 落在算出来的那一份', "store.init_head(target['entity'], target['scope']" in chat),
             ('host 同步两份投影', 'scene_links.sync_identity_docs(store, store.config)' in host
              and 'scene_links.sync_scene_docs(store, store.config' in host),
             ('host 的关系 head 落在算出来的那一份', "store.init_head(target['entity'], target['scope']" in host)]
    # 回滚 = 删配置键：投影留在库里，但读路径立刻不联动
    quiet = store_with(config_base(top={'context_links': {}, 'canonical_persons': {}}))
    quiet.db.scenes.rows[LOCAL] = dict(scene)
    after = sl.read_scope(quiet.config, {'_id': LOCAL})
    target = sl.relationship_target(quiet.config, store.db, {'_id': QQ, 'scope_key': 'scene:' + QQ},
                                    ALIAS)
    return (scene.get('readable_scenes') == [QQ] and alias.get('canonical_person_id') == ME
            and alias.get('alias_of') == ME and store.db.messages.rows['in-q1']['author'] == ALIAS
            and after['linked_scenes'] == [] and target['scope'] == 'scene:' + QQ
            and all(flag for _, flag in wired)), \
        {'scene': scene.get('readable_scenes'),
         'identity': {k: alias.get(k) for k in ('canonical_person_id', 'alias_of')},
         'after_removal': after['linked_scenes'], 'fallback_target': target['scope'],
         'missing': [name for name, flag in wired if not flag]}


def main():
    failures = 0
    for fn in CASES:
        try:
            ok, detail = fn()
        except Exception as exc:                       # 用例炸了也算没通过，不静默跳过
            ok, detail = False, '%s: %s' % (type(exc).__name__, exc)
        print('%s %s — %s' % ('PASS' if ok else 'FAIL', fn.__name__,
                              '' if ok else detail))
        failures += 0 if ok else 1
    print('跨场景只读联动自检：%d/%d 通过' % (len(CASES) - failures, len(CASES)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
