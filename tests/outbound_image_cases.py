"""出站图片附件（QQ 私聊 B 阶段第一步）的离线用例。

本机跑：``python3 tools/outbound_image_offline_check.py`` —— 不需要 Mongo、不需要 pytest、
不联网、不发 QQ。装真的跑的是仓库里那份代码：``outbound_media`` 的全部围栏、
``channels`` 的 claim / attachment / HTTP 层（真在 127.0.0.1 上起服务、真发请求）、
她的 ``attach_image`` 工具（``role_tools``，逐次判定、退回给她的话）、整回合（真 ``Coordinator``
跑 think → attach_image → 正文或 stay_silent → SPEAK 行）、``history_query`` 的命中投影与渲染、
``BlobStore`` 的 sha 复核与 GridFS 读。假掉的只有存储（内存集合 + 内存 GridFS，**无论环境装没装
pymongo／gridfs 都用替身**：真 GridFSBucket 不接受假 DB）与模型（``FakeLane`` 按剧本给工具调用，
不调真模型）。这套是独立跑的离线套件，不要在用真 Mongo 的 pytest 会话里 import 它——它会把自己的
存储替身装进 sys.modules。

覆盖：端点围栏（token / 只发这条声明的 artifact / attempt 必须属于这条且正在 SENDING /
scope / sha 复核 / 不是图就拒）、claim 元数据（声明 supports=image 才给，不带 base64）、
attach_image 校验（清单外、群方向、非 owner_private、非图片、超限、参数逐次退回、沉默的回合不发图）、
历史投影（我发过这张图 / 回执对不上 / 没带图的行逐字不变）。

假集合的匹配语义按 Mongo 的字面查询实现（等值、$in/$ne/$lt/$lte/$gt/$gte/$exists/$or、
点号路径、sort/limit/projection）；语义不一致会让用例假绿，改动这里要对着 Mongo 文档看。
"""
import copy
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import types
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'src')
# 锁文件写到临时目录：别让离线用例在候选里留下 .runtime/
os.environ.setdefault('ASUNA_DATA_ROOT', tempfile.mkdtemp(prefix='outbound-image-'))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


# 存储这一层无论环境装没装都用替身：这套用例假的就是存储本身，而真 GridFSBucket 拿到假 DB
# 会直接 TypeError: database must be an instance of Database。装了 pymongo 的完整环境里必须
# 和这里一样绿，否则同一套用例在两种环境下测的不是同一件事。
FORCED_STUBS = ('bson', 'pymongo', 'gridfs')


def _stub_when_missing(name, factory):
    '''只在真库装不上时才假：jsonschema 用真的才有意义（真校验），httpx／msvcrt 同理。'''
    try:
        __import__(name)
        return False
    except Exception:
        factory()
        return True


class ObjectId:                       # 只需要「能当键、能比」这一点点语义
    def __init__(self, value):
        self.value = str(value)

    def __eq__(self, other):
        return self.value == str(other)

    def __hash__(self):
        return hash(self.value)

    def __str__(self):
        return self.value


class FakeBucket:                     # 内存版 GridFS：只按 id 存字节
    def __init__(self, db, bucket_name=None):
        self.db = db

    def upload_from_stream(self, name, data, metadata=None):
        return self.db.put_blob(bytes(data), metadata or {})

    def open_download_stream(self, blob_id):
        return io.BytesIO(self.db.take_blob(blob_id))

    def delete(self, blob_id):
        self.db.drop_blob(blob_id)


def _install_stubs():
    def bson():
        _stub('bson', BSON=types.SimpleNamespace(encode=lambda doc: b'{}'), ObjectId=ObjectId)

    def pymongo():
        root = _stub('pymongo', ASCENDING=1, MongoClient=object,
                     ReturnDocument=types.SimpleNamespace(AFTER=1), WriteConcern=lambda **kw: None)
        root.errors = _stub('pymongo.errors',
                            DuplicateKeyError=type('DuplicateKeyError', (Exception,), {}))
        root.operations = _stub('pymongo.operations', SearchIndexModel=object)

    def httpx():
        _stub('httpx', Client=lambda *a, **k: None, Timeout=lambda *a, **k: None)

    def jsonschema_stub():
        _stub('jsonschema', validate=lambda value, schema: None,
              ValidationError=type('ValidationError', (Exception,), {}))

    def msvcrt():
        _stub('msvcrt', setlocking=lambda *a: None, locking=lambda *a: None,
              LK_NBLCK=1, LK_UNLCK=2)
        _stub('_winapi', __getattr__=lambda name: 0)

    def gridfs():
        _stub('gridfs', GridFSBucket=FakeBucket)

    installed = []
    for name, factory in (('bson', bson), ('pymongo', pymongo), ('httpx', httpx),
                          ('jsonschema', jsonschema_stub), ('msvcrt', msvcrt), ('gridfs', gridfs)):
        if name in FORCED_STUBS:            # 存储：无条件换成替身，装了真的也换
            factory()
            installed.append(name)
        elif _stub_when_missing(name, factory):
            installed.append(name)
    return installed


STUBBED = _install_stubs()
DUPLICATE_ID = sys.modules['pymongo'].errors.DuplicateKeyError

from asuna import history_query, integration_import, outbound_media, role_tools   # noqa: E402
from asuna.blobs import BlobStore                                     # noqa: E402
from asuna.channels import ChannelServer, Channels                    # noqa: E402
from asuna.coordinator import Coordinator                             # noqa: E402
from asuna.lanes import FakeLane, FakeTurn                            # noqa: E402
from asuna.state import Conflict, Denied                              # noqa: E402

# ── 假世界 ────────────────────────────────────────────────────────────────────
# 规则：代码／测试／文档里不写真实 QQ 号、群号、地址，全用这里的假占位值。
BOT = '900000000'
OWNER_ACCOUNT = '900000001'
GROUP_ACCOUNT = '900000002'
TOKEN = 'offline-channel-token'
DM_SCENE = 'sc-owner-dm'
GROUP_SCENE = 'sc-group'
DM_SCOPE = 'scene:' + DM_SCENE
GROUP_SCOPE = 'scene:' + GROUP_SCENE

PNG = b'\x89PNG\r\n\x1a\n' + b'xiaoman-selfie-payload' * 4
JPEG = b'\xff\xd8\xff\xe0' + b'jpeg-payload' * 4
WEBP = b'RIFF' + (20).to_bytes(4, 'little') + b'WEBPVP8 ' + b'x' * 8
NOT_IMAGE = b'\x00\x01\x02\x03 not an image'

CONFIG = {
    'character_id': 'xiaoman',
    'chat': {'scene_id': 'local', 'person_id': 'owner-p', 'persona': 'xiaoman', 'display_name': '小满'},
    'channels': {'qq': {
        'account_id': BOT, 'token': TOKEN,
        'routes': {
            'owner-dm': {'scene_id': DM_SCENE, 'target': {'type': 'dm', 'id': OWNER_ACCOUNT},
                         'sender_id': OWNER_ACCOUNT, 'person_id': 'owner-p',
                         'members': {OWNER_ACCOUNT: {'person_id': 'owner-p'}}},
            'group': {'scene_id': GROUP_SCENE, 'target': {'type': 'group', 'id': GROUP_ACCOUNT},
                      'members': {OWNER_ACCOUNT: {'person_id': 'owner-p'}}},
        },
    }},
}


def _get(doc, key):
    value = doc
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _ops(have, want):
    for op, expect in want.items():
        if op == '$in':
            if have not in expect:
                return False
        elif op == '$nin':
            if have in expect:
                return False
        elif op == '$ne':
            if have == expect:
                return False
        elif op == '$exists':
            if (have is not None) != bool(expect):
                return False
        elif op == '$lt':
            if not (have is not None and have < expect):
                return False
        elif op == '$lte':
            if not (have is not None and have <= expect):
                return False
        elif op == '$gt':
            if not (have is not None and have > expect):
                return False
        elif op == '$gte':
            if not (have is not None and have >= expect):
                return False
        else:
            raise AssertionError('假集合没实现的操作符：%s' % op)
    return True


def _match(doc, query):
    for key, want in (query or {}).items():
        if key == '$or':
            if not any(_match(doc, sub) for sub in want):
                return False
            continue
        if key == '$and':
            if not all(_match(doc, sub) for sub in want):
                return False
            continue
        have = _get(doc, key)
        operator_query = isinstance(want, dict) and any(str(k).startswith('$') for k in want)
        if not (_ops(have, want) if operator_query else have == want):
            return False
    return True


def _project(doc, projection):
    if not projection:
        return copy.deepcopy(doc)
    out = {'_id': doc.get('_id')}
    for key, keep in projection.items():
        if not keep:
            continue
        if '.' in key:
            if _get(doc, key) is not None:
                out[key] = _get(doc, key)
        elif key in doc:
            out[key] = doc[key]
    return out


class Cursor:
    '''链式 sort/limit 与 Mongo 同形；实例属性用下划线前缀，别把方法盖掉。'''

    def __init__(self, rows, projection=None, sorted_by=None, capped=None):
        self.rows, self.projection, self._sorted_by, self._capped = rows, projection, sorted_by, capped

    def sort(self, *spec):
        pairs = list(spec[0]) if spec and isinstance(spec[0], (list, tuple)) and \
            spec[0] and isinstance(spec[0][0], (list, tuple)) else [list(spec)]
        rows = list(self.rows)
        for field, direction in reversed(pairs):
            rows.sort(key=lambda row, f=field: (_get(row, f) is None, _get(row, f)),
                      reverse=int(direction) < 0)
        return Cursor(rows, self.projection, spec, self._capped)

    def limit(self, count):
        return Cursor(list(self.rows)[:int(count)], self.projection, self._sorted_by, count)

    def __iter__(self):
        return iter(_project(row, self.projection) for row in self.rows)

    def __len__(self):
        return len(self.rows)


class Collection:
    def __init__(self, name):
        self.name, self.docs = name, {}

    def insert_one(self, doc):
        if doc['_id'] in self.docs:
            raise DUPLICATE_ID(doc['_id'])
        self.docs[doc['_id']] = copy.deepcopy(doc)
        return types.SimpleNamespace(inserted_id=doc['_id'])

    def replace_one(self, query, doc):
        hit = [row for row in self.docs.values() if _match(row, query)]
        if not hit:
            return types.SimpleNamespace(modified_count=0)
        self.docs[doc['_id']] = copy.deepcopy(doc)
        return types.SimpleNamespace(modified_count=1)

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [row for row in self.docs.values() if _match(row, query or {})]
        cursor = Cursor(rows, projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return cursor

    def find_one(self, query=None, projection=None, sort=None, limit=None):
        for row in self.find(query, projection, sort, limit or 1):
            return row
        return None

    def count_documents(self, query=None):
        return len([row for row in self.docs.values() if _match(row, query or {})])

    def find_one_and_update(self, query, update, return_document=None):
        '''只实现 coordinator 写 SPEAK 行取场景序号用到的 $inc／$set，返回改后的那份（AFTER）。'''
        for row in self.docs.values():
            if _match(row, query):
                for field, step in (update.get('$inc') or {}).items():
                    row[field] = (row.get(field) or 0) + step
                for field, value in (update.get('$set') or {}).items():
                    row[field] = value
                unknown = set(update) - {'$inc', '$set'}
                if unknown:
                    raise AssertionError('假集合没实现的更新操作符：%s' % sorted(unknown))
                return copy.deepcopy(row)
        return None

    def distinct(self, field, query=None):
        return sorted({row.get(field) for row in self.docs.values()
                       if _match(row, query or {}) and row.get(field) is not None})


class DB:
    def __init__(self):
        self._collections, self._blobs, self._next = {}, {}, 1

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        return self._collections.setdefault(name, Collection(name))

    def put_blob(self, data, metadata):
        blob_id = str(self._next).zfill(24)
        self._next += 1
        self._blobs[blob_id] = (data, metadata)
        return ObjectId(blob_id)

    def take_blob(self, blob_id):
        found = self._blobs.get(str(blob_id))
        if found is None:
            raise FileNotFoundError(blob_id)
        return found[0]

    def drop_blob(self, blob_id):
        self._blobs.pop(str(blob_id), None)

    def tamper(self, blob_id, data):
        '''把存进去的字节换掉：BlobStore 读时应按行内 sha 发现不一致。'''
        blob_id = str(blob_id)
        self._blobs[blob_id] = (data, self._blobs[blob_id][1])


class FakeStore:
    name = 'offline-outbound-image'

    def __init__(self, config=None):
        self.config = config if config is not None else CONFIG
        self.db = DB()
        self.audited = []

    def audit(self, stream, kind, payload, scope='operator'):
        event = {'_id': 'aud-%d' % len(self.audited), 'stream_id': stream, 'type': kind,
                 'payload': payload, 'scope_key': scope}
        self.audited.append(event)
        return event

    def put(self, collection, document, *, expected=None, stream='state'):
        doc = copy.deepcopy(document)
        doc['schema_version'] = 1
        doc['revision'] = 1 if expected is None else expected + 1
        column = self.db[collection]
        if expected is None:
            column.insert_one(doc)
        elif column.replace_one({'_id': doc['_id'], 'revision': expected}, doc).modified_count != 1:
            raise Conflict('STALE_REVISION')
        self.audit(stream, 'state.commit', {'collection': collection, 'id': doc['_id']},
                   doc.get('scope_key', 'operator'))
        return doc

    def authorize(self, scene_id, person_id):
        scene = self.db.scenes.find_one({'_id': scene_id})
        if not scene or person_id not in scene['members']:
            raise Denied('SCENE_MEMBERSHIP_DENIED')
        return scene

    def head(self, entity, scope):
        return None

    def next_scene_seq(self, scene_id):
        return len(list(self.db.messages.find({'scene_id': scene_id}))) + 1


class FakeEvidence:
    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append((kind, payload))
        return {'_id': 'ev-%d' % len(self.records)}


class FakeApp:
    def __init__(self, store):
        self.store = store
        self.evidence = FakeEvidence()


class FakeController:
    def __init__(self, store):
        self.app = FakeApp(store)
        self.stopping = threading.Event()
        self.reconfiguring = False
        self.ingress_lock = threading.RLock()


def scene_row(kind='dm'):
    if kind == 'dm':
        return {'_id': DM_SCENE, 'kind': 'dm', 'channel_id': 'qq', 'scope_key': DM_SCOPE,
                'policy_epoch': 1, 'members': ['owner-p'], 'sequence': 0}
    return {'_id': GROUP_SCENE, 'kind': 'group', 'channel_id': 'qq', 'scope_key': GROUP_SCOPE,
            'policy_epoch': 1, 'members': ['owner-p'], 'sequence': 0}


def episode_row(state='COMMITTED'):
    return {'_id': 'ep-1', 'scene_id': DM_SCENE, 'person_id': 'owner-p', 'state': state,
             'scope_key': DM_SCOPE, 'policy_epoch': 1}


def publication_row(**over):
    row = {'_id': 'out-1', 'publication_key': 'out-1', 'episode_id': 'ep-1', 'scene_id': DM_SCENE,
           'scene_seq': 5, 'scope_key': DM_SCOPE, 'policy_epoch': 1, 'text': '画好了，给你看',
           'direction': 'outbound', 'author': 'xiaoman', 'phase': 'SPEAK', 'revision': 1,
           'channel_id': 'qq', 'channel_account_id': BOT, 'target': {'type': 'dm', 'id': OWNER_ACCOUNT},
           'platform_reply_to': None, 'delivery_state': 'QUEUED_EXTERNAL'}
    row.update(over)
    return row


def world(kind='dm', image=PNG, store=None):
    '''一个场景 + 一条已提交的 SPEAK + BlobStore 里的一张图。'''
    store = store or FakeStore()
    store.db.scenes.insert_one(scene_row(kind))
    store.db.episodes.insert_one(episode_row())
    stored = BlobStore(store).put(image, DM_SCOPE if kind == 'dm' else GROUP_SCOPE, 'image',
                                  media_type=outbound_media.sniff_media_type(image))
    return store, stored


def sending_row(store, stored, **over):
    '''一条正在 SENDING、行上挂着附件元数据的 publication（claim 之后的形状）。'''
    attachment = {'artifact_id': stored['artifact_id'],
                  'media_type': outbound_media.sniff_media_type(_blob_bytes(store, stored)),
                  'sha256': stored['sha256'], 'size': stored['size']}
    row = publication_row(delivery_state='SENDING', attempt_id='attempt-1', attachment=attachment)
    row.update(over)
    store.db.messages.insert_one(row)
    return row


def _blob_bytes(store, stored):
    return store.db.take_blob(_gridfs_id(store, stored['artifact_id']))


def _gridfs_id(store, artifact_id):
    return store.db.artifacts.find_one({'_id': artifact_id})['gridfs_id']


def http(port, path, token=TOKEN):
    request = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path))
    if token:
        request.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get('Content-Type'), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get('Content-Type'), exc.read()


def with_server(store):
    server = ChannelServer(Channels(FakeController(store)), 0)
    return server, server.server.server_address[1]


def error_code(body):
    try:
        return json.loads(body.decode('utf-8', 'replace')).get('error')
    except Exception:
        return ''


# ── 用例 ─────────────────────────────────────────────────────────────────────
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# 1) 端点围栏
@case
def endpoint_serves_declared_bytes():
    store, stored = world()
    sending_row(store, stored)
    server, port = with_server(store)
    try:
        code, ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment'
                                        '?attempt_id=attempt-1&artifact_id=%s' % stored['artifact_id'])
    finally:
        server.close()
    assert code == 200, (code, body[:200])
    assert ctype == 'image/png', ctype
    assert body == PNG, '端点吐的字节不是存进去的那份'
    return True, '200 + image/png + %d 字节逐字相同' % len(body)


@case
def endpoint_needs_the_same_bearer_token():
    store, stored = world()
    sending_row(store, stored)
    server, port = with_server(store)
    try:
        missing = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1', token=None)
        wrong = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1',
                     token='not-the-channel-token')
    finally:
        server.close()
    assert missing[0] == 403 and wrong[0] == 403, (missing[0], wrong[0])
    assert error_code(missing[2]) == 'CHANNEL_AUTH_REQUIRED', missing[2][:200]
    return True, '没带 token 与带错 token 都是 403 CHANNEL_AUTH_REQUIRED'


@case
def endpoint_only_serves_the_artifact_this_publication_declared():
    store, stored = world()
    other = BlobStore(store).put(JPEG, DM_SCOPE, 'image', media_type='image/jpeg')
    sending_row(store, stored)
    server, port = with_server(store)
    try:
        foreign = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1'
                             '&artifact_id=%s' % other['artifact_id'])
        omitted = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert foreign[0] == 403 and error_code(foreign[2]) == 'ATTACHMENT_ARTIFACT_DENIED', foreign[:2]
    assert omitted[0] == 200 and omitted[2] == PNG, '不写 artifact_id 时应发这条自己声明的那张'
    return True, '同 scope 里别的 artifact 被拒（403），不写则发自己声明的那张'


@case
def endpoint_fences_attempt_and_sending():
    store, stored = world()
    sending_row(store, stored)
    store.db.messages.insert_one(publication_row(_id='out-queued', delivery_state='QUEUED_EXTERNAL'))
    store.db.messages.insert_one(publication_row(_id='out-delivered', delivery_state='DELIVERED',
                                                 attempt_id='attempt-1'))
    server, port = with_server(store)
    try:
        wrong_attempt = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=nope')
        no_attempt = http(port, '/v1/channels/qq/outbox/out-1/attachment')
        queued = http(port, '/v1/channels/qq/outbox/out-queued/attachment?attempt_id=attempt-1')
        delivered = http(port, '/v1/channels/qq/outbox/out-delivered/attachment?attempt_id=attempt-1')
        other_channel = http(port, '/v1/channels/other/out-1/attachment?attempt_id=attempt-1')
        missing_pub = http(port, '/v1/channels/qq/outbox/out-none/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert wrong_attempt[0] == 403 and error_code(wrong_attempt[2]) == 'PUBLICATION_ATTEMPT_MISMATCH'
    assert no_attempt[0] == 403 and error_code(no_attempt[2]) == 'PUBLICATION_ATTEMPT_MISMATCH'
    assert queued[0] == 403 and error_code(queued[2]) == 'PUBLICATION_ATTEMPT_MISMATCH', queued[:2]
    assert delivered[0] == 403 and error_code(delivered[2]) == 'PUBLICATION_ATTEMPT_MISMATCH'
    assert other_channel[0] == 403 and error_code(other_channel[2]) == 'CHANNEL_AUTH_REQUIRED', other_channel[:2]
    assert missing_pub[0] == 403 and error_code(missing_pub[2]) == 'PUBLICATION_NOT_FOUND'
    return True, '错 attempt／缺 attempt／没领取／已送达／别的通道／别的 publication 全部 403'


@case
def endpoint_refuses_when_nothing_declared():
    store, _stored = world()
    store.db.messages.insert_one(publication_row(delivery_state='SENDING', attempt_id='attempt-1'))
    server, port = with_server(store)
    try:
        code, _ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert code == 403 and error_code(body) == 'ATTACHMENT_NOT_DECLARED', (code, body[:200])
    return True, '没声明附件的 publication 拿不到任何字节'


@case
def endpoint_refuses_bytes_when_the_picture_never_went_out():
    """没声明 image 能力的那条：行上元数据还在，图没跟着出去 → 字节也不给。

    假存储没有放过这个形状，漏的是用例矩阵：真 claim 的 CAS 只往行上加 ``attachment_skipped``，
    故意不把 ``attachment`` 元数据抹掉（历史要靠它知道这条本来带图），所以「两个字段都在」正是
    真实行的样子；以前只在 claim 那一层断过 skipped，没拿同一条行再去取一次字节，而
    ``descriptor(row)`` 只看元数据在不在 —— 于是真库里这条端点是开着的。
    """
    store, stored = world()
    sending_row(store, stored, attachment_skipped=outbound_media.NO_CAPABILITY)
    server, port = with_server(store)
    try:
        code, ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert code == 403 and error_code(body) == 'ATTACHMENT_NOT_DECLARED', (code, ctype, body[:200])

    row = store.db.messages.find_one({'_id': 'out-1'})
    assert row['attachment'] and row['attachment_skipped'] == outbound_media.NO_CAPABILITY, row
    try:                                                    # 不靠 HTTP 层、也不靠 claim 阶段
        outbound_media.serve(store, BlobStore(store), row, outbound_media.descriptor(row))
    except Denied as exc:
        assert 'ATTACHMENT_NOT_DECLARED' in str(exc), exc
    else:
        raise AssertionError('serve() 在记了 skipped 的行上还是把图发出去了')

    store.db.messages.replace_one({'_id': 'out-1'}, {key: value for key, value in row.items()
                                                     if key != outbound_media.SKIPPED_KEY})
    server, port = with_server(store)
    try:                                                    # 对照：声明了能力的正常路径不变
        code, ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert (code, body) == (200, PNG), (code, body[:200])
    return True, '行上有 attachment_skipped → 403 ATTACHMENT_NOT_DECLARED；抹掉后同一行仍 200'


@case
def endpoint_checks_scope_and_sha():
    store, stored = world()
    row = sending_row(store, stored)
    # 别的 scope 里的 artifact：行上声明了，但这条消息的 scope 读不到
    store.db.scenes.insert_one({'_id': 'sc-other', 'kind': 'dm', 'scope_key': 'scene:other',
                                'policy_epoch': 1, 'members': ['owner-p']})
    foreign = BlobStore(store).put(JPEG, 'scene:other', 'image', media_type='image/jpeg')
    store.db.messages.replace_one({'_id': 'out-1'}, dict(row, attachment={
        'artifact_id': foreign['artifact_id'], 'media_type': 'image/jpeg',
        'sha256': foreign['sha256'], 'size': foreign['size']}))
    server, port = with_server(store)
    try:
        scoped = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert scoped[0] == 403 and error_code(scoped[2]) == 'ATTACHMENT_SCOPE_DENIED', scoped[:2]

    # 行内 sha 与声明不一致（写行的人与存字节的人对不上）
    store2, stored2 = world()
    row2 = sending_row(store2, stored2)
    store2.db.messages.replace_one({'_id': 'out-1'}, dict(row2, attachment=dict(
        row2['attachment'], sha256='0' * 64)))
    try:
        outbound_media.serve(store2, BlobStore(store2), store2.db.messages.find_one({'_id': 'out-1'}),
                             outbound_media.descriptor(store2.db.messages.find_one({'_id': 'out-1'})))
        raise AssertionError('sha 不一致却还是发了字节')
    except Denied as exc:
        assert 'ATTACHMENT_SHA_MISMATCH' in str(exc), exc

    # 存进去的字节被换掉：BlobStore 读时按行内 sha 复核必须发现
    store3, stored3 = world()
    row3 = sending_row(store3, stored3)
    store3.db.tamper(_gridfs_id(store3, stored3['artifact_id']), b'tampered-bytes')
    try:
        outbound_media.serve(store3, BlobStore(store3), store3.db.messages.find_one({'_id': 'out-1'}),
                             outbound_media.descriptor(store3.db.messages.find_one({'_id': 'out-1'})))
        raise AssertionError('字节被换过却还是发了')
    except Denied as exc:
        assert 'ATTACHMENT_HASH_MISMATCH' in str(exc), exc
    return True, '别的 scope 403；行内 sha 不符与字节被换过都拒发'


@case
def endpoint_refuses_bytes_that_are_not_the_declared_image():
    # 字节本来就存了非图片（kind 写着 image）：sha 对得上，也要在魔数这一关被拒
    store, stored = world(image=NOT_IMAGE)
    row = publication_row(delivery_state='SENDING', attempt_id='attempt-1', attachment={
        'artifact_id': stored['artifact_id'], 'media_type': 'image/png',
        'sha256': stored['sha256'], 'size': stored['size']})
    store.db.messages.insert_one(row)
    try:
        outbound_media.serve(store, BlobStore(store), row, outbound_media.descriptor(row))
        raise AssertionError('不是图却还是发了')
    except Denied as exc:
        assert 'ATTACHMENT_NOT_AN_IMAGE' in str(exc), exc
    # 魔数与行上声明的 media_type 不一致（存的是 jpeg，行上写 png）：适配器会按声明去比对，先拒
    store2, stored2 = world(image=JPEG)
    row2 = publication_row(delivery_state='SENDING', attempt_id='attempt-1', attachment={
        'artifact_id': stored2['artifact_id'], 'media_type': 'image/png',
        'sha256': stored2['sha256'], 'size': stored2['size']})
    store2.db.messages.insert_one(row2)
    try:
        outbound_media.serve(store2, BlobStore(store2), row2, outbound_media.descriptor(row2))
        raise AssertionError('格式与声明不一致却还是发了')
    except Denied as exc:
        assert 'ATTACHMENT_MEDIA_TYPE_MISMATCH' in str(exc), exc
    return True, '不是图 / 与声明格式不一致都拒发，不吐半截字节'


# 2) claim 元数据
@case
def claim_returns_metadata_only_when_image_declared():
    store, stored = world()
    sending_row(store, stored)
    store.db.messages.replace_one({'_id': 'out-1'}, dict(store.db.messages.find_one({'_id': 'out-1'}),
                                                         delivery_state='QUEUED_EXTERNAL'))
    server, port = with_server(store)
    try:
        code, _ctype, body = http(port, '/v1/channels/qq/outbox?wait_seconds=0&supports=image')
    finally:
        server.close()
    assert code == 200, (code, body[:200])
    item = json.loads(body)['items'][0]
    assert set(item) == {'publication_id', 'attempt_id', 'target', 'text', 'reply_to', 'attachment'}, sorted(item)
    assert item['attachment'] == {'artifact_id': stored['artifact_id'], 'media_type': 'image/png',
                                  'sha256': stored['sha256'], 'size': stored['size']}, item['attachment']
    flat = json.dumps(item)
    assert 'base64' not in flat and len(flat) < 2000, 'claim 里混进了字节或变大了'
    return True, 'supports=image 时给 %s' % sorted(item['attachment'])


@case
def claim_without_capability_sends_text_and_marks_the_picture_skipped():
    store, stored = world()
    sending_row(store, stored)
    store.db.messages.replace_one({'_id': 'out-1'}, dict(store.db.messages.find_one({'_id': 'out-1'}),
                                                         delivery_state='QUEUED_EXTERNAL'))
    server, port = with_server(store)
    try:
        code, _ctype, body = http(port, '/v1/channels/qq/outbox?wait_seconds=0')
    finally:
        server.close()
    item = json.loads(body)['items'][0]
    assert 'attachment' not in item, '老适配器没声明能力却拿到了附件元数据'
    row = store.db.messages.find_one({'_id': 'out-1'})
    assert row['delivery_state'] == 'SENDING'
    assert row['attachment_skipped'] == outbound_media.NO_CAPABILITY, row.get('attachment_skipped')
    assert row['attachment'], '元数据要留在行上，历史才知道这条本来带图'
    return True, '不声明就只给文字，行上记 attachment_skipped=%s' % outbound_media.NO_CAPABILITY


@case
def claim_that_carries_the_image_clears_a_stale_skipped_marker():
    """重投的行会带着上一次的 attachment_skipped 回来：这次声明了能力并真带图，标记必须清掉。

    不清的话，字节端点会拒掉这条自己声明的图（403），而 delivered 历史也会说「图没出去」——
    标记描述的是当前这一次领取，不是这条消息历史上的一次失败。
    """
    store, stored = world()
    stale = publication_row(attachment={'artifact_id': stored['artifact_id'], 'media_type': 'image/png',
                                        'sha256': stored['sha256'], 'size': stored['size']},
                            attachment_skipped=outbound_media.NO_CAPABILITY, attempt_id='attempt-old')
    store.db.messages.insert_one(stale)                     # publish 重投后的形状：QUEUED_EXTERNAL + 旧标记
    server, port = with_server(store)
    try:
        code, _ctype, body = http(port, '/v1/channels/qq/outbox?wait_seconds=0&supports=image')
        item = json.loads(body)['items'][0]
        assert 'attachment' in item, (code, body[:200])
        row = store.db.messages.find_one({'_id': 'out-1'})
        assert outbound_media.SKIPPED_KEY not in row, '旧标记没清，端点会拒掉这条自己声明的图'
        assert row['attempt_id'] == item['attempt_id'] and row['attempt_id'] != 'attempt-old', row
        code, _ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=%s'
                                  % item['attempt_id'])
    finally:
        server.close()
    assert (code, body) == (200, PNG), (code, body[:200])
    return True, '带图的领取会清掉旧的 attachment_skipped，字节照旧 200'


@case
def claim_of_text_only_publication_is_unchanged():
    store, _stored = world()
    store.db.messages.insert_one(publication_row())
    server, port = with_server(store)
    try:
        code, _ctype, body = http(port, '/v1/channels/qq/outbox?wait_seconds=0&supports=image')
    finally:
        server.close()
    item = json.loads(body)['items'][0]
    assert set(item) == {'publication_id', 'attempt_id', 'target', 'text', 'reply_to'}, sorted(item)
    assert item['text'] == '画好了，给你看' and item['target'] == {'type': 'dm', 'id': OWNER_ACCOUNT}
    row = store.db.messages.find_one({'_id': 'out-1'})
    assert 'attachment' not in row and 'attachment_skipped' not in row
    return True, '没带图的消息：item 与行都和改动前逐字一致'


# 3) 她的 attach_image 工具（ADR-011：原来 DECIDE 的 attach）
# 单次调用走 RoleTools.call（原生回合里每次工具调用都走它）；整回合走真 Coordinator + FakeLane/FakeTurn。
THINK = ('think', {'thought': '他想看那张图，我配上发给他。'})


class FakeCoordinator:
    '''RoleTools 只用到协调器的 store 与 _update：_update 与真 Coordinator 一样按 revision 写回。'''

    def __init__(self, store):
        self.store, self.scheduler = store, None

    def _update(self, ep, **changes):
        return self.store.put('episodes', {**ep, **changes}, expected=ep['revision'], stream=ep['_id'])


class FakePublisher:
    '''发布那一层只记下发了哪几行：通道与字节端点在上面两组用例里真跑。'''

    def __init__(self, store):
        self.store, self.published = store, []

    def publish(self, key):
        self.published.append(key)
        return dict(self.store.db.messages.find_one({'_id': key}), delivery_state='QUEUED_EXTERNAL')

    def cancel_after(self, row):
        raise AssertionError('离线回合不该走到撤销')


def turn_ep(store, kind='dm', session='owner_private', context=None, ep_id='ep-turn'):
    '''一个准备好、还没开始的回合（PREPARED）：上下文与图片清单都是程序给的。'''
    scene = scene_row(kind)
    return store.put('episodes', {
        '_id': ep_id, 'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': 1,
        'persona': 'xiaoman', 'person_id': 'owner-p', 'episode_kind': 'external', 'state': 'PREPARED',
        'source_event_id': 'evt-' + ep_id, 'monologue_refs': [], 'context': context or {},
        'manifest': {'session_class': session},
        'system_ref': {'render_sha256': 'offline', 'common_sha256': 'offline', 'session_class': session}},
        stream=ep_id)


def offered_ep(store, kind='dm', session='owner_private'):
    return turn_ep(store, kind, session, {'image_artifacts_from_program': outbound_media.offer(
        store, store.config, scene_row(kind), session, 'owner-p')})


def call_tool(store, ep, args, tools=None, name='attach_image'):
    '''这一回合（已 think）里调用一次工具：成功 ('ok', 结果, 回合)，退回 ('refused', 给她看的话, 回合)。'''
    current = store.db.episodes.find_one({'_id': ep['_id']})
    names = tools if tools is not None else role_tools.exposed(store, current)
    current = store.put('episodes', dict(current, state='TURN', turn_tools=names, turn_thought=True,
                                         tool_calls=current.get('tool_calls') or {}),
                        expected=current['revision'], stream=ep['_id'])
    call_id = '%s:TURN#%d' % (ep['_id'], len(current['tool_calls']))
    try:
        result, _conclude = role_tools.RoleTools(FakeCoordinator(store)).call(ep['_id'], call_id, name, args)
        outcome = ('ok', result)
    except role_tools.Refused as exc:
        outcome = ('refused', str(exc))
    return outcome + (store.db.episodes.find_one({'_id': ep['_id']}),)


def attach(store, ep, artifact_id, tools=None):
    return call_tool(store, ep, {'artifact_id': artifact_id, 'why': '给他看这张'}, tools)


def run_turn(store, ep, *turns):
    '''真 Coordinator 跑完这一回合（think → 工具 → 正文或 stay_silent → SPEAK 行）。'''
    lane, publisher = FakeLane(store, list(turns)), FakePublisher(store)
    coordinator = Coordinator(store, lane, context=object(), publisher=publisher, task_service=object())
    return coordinator.advance(ep['_id']), lane, publisher


def speak_rows(store, ep):
    return list(store.db.messages.find({'episode_id': ep['_id'], 'direction': 'outbound'}).sort('scene_seq', 1))


def meta_of(stored, media_type='image/png'):
    return {'artifact_id': stored['artifact_id'], 'media_type': media_type,
            'sha256': stored['sha256'], 'size': stored['size']}


@case
def attach_image_accepts_a_listed_artifact_and_yields_metadata():
    store, stored = world()
    ep = offered_ep(store)
    assert 'attach_image' in role_tools.exposed(store, ep), role_tools.exposed(store, ep)
    outcome, result, after = attach(store, ep, stored['artifact_id'])
    assert outcome == 'ok' and result['attached'] == stored['artifact_id'], result
    assert after['attachment']['size'] == len(PNG), after['attachment']
    meta = outbound_media.attachment_for_speak(after)
    assert meta == meta_of(stored), meta
    assert json.dumps(meta).count('base64') == 0
    recorded = list(after['tool_calls'].values())
    assert [row['tool'] for row in recorded] == ['attach_image'] and 'result' in recorded[0], recorded
    return True, '接受清单里的图 → 回合上记下元数据 %s（无 base64）' % sorted(meta)


@case
def attach_image_refuses_artifact_not_offered_this_turn():
    store, _stored = world()
    elsewhere = BlobStore(store).put(JPEG, DM_SCOPE, 'image', media_type='image/jpeg')
    offered = outbound_media.offer(store, CONFIG, scene_row(), 'owner_private')
    offered['items'] = [item for item in offered['items'] if item['artifact_id'] != elsewhere['artifact_id']]
    ep = turn_ep(store, context={'image_artifacts_from_program': offered})
    outcome, said, after = attach(store, ep, elsewhere['artifact_id'])
    assert outcome == 'refused' and 'ATTACH_ARTIFACT_NOT_IN_CONTEXT' in said, said
    assert 'image_artifacts_from_program' in said, '退回的话没告诉她该从哪里抄 artifact_id'
    assert 'attachment' not in after and outbound_media.attachment_for_speak(after) is None
    assert [row.get('refused') for row in after['tool_calls'].values()] == [said]
    return True, '清单外的 artifact 退回给她：%s' % said


@case
def attach_image_refuses_group_and_non_owner_private_deterministically():
    store, stored = world(kind='group')
    # 群场景里 offer 本身就不出现：她没有可引用的清单，这回合也就没有 attach_image
    assert outbound_media.offer(store, CONFIG, scene_row('group'), 'owner_private') is None
    group_ep = turn_ep(store, kind='group')
    assert 'attach_image' not in role_tools.exposed(store, group_ep)
    outcome, said, _after = attach(store, group_ep, stored['artifact_id'])
    assert outcome == 'refused' and '没有 attach_image' in said, said
    # 就算这回合带着工具、上下文里冒出一份清单，程序照样按方向拒
    forged = {'image_artifacts_from_program': {'items': [{'artifact_id': stored['artifact_id']}], 'note': ''}}
    group_ep2 = turn_ep(store, kind='group', context=forged, ep_id='ep-turn-2')
    outcome, said, after = attach(store, group_ep2, stored['artifact_id'], tools=['think', 'attach_image'])
    assert outcome == 'refused' and 'ATTACH_TARGET_NOT_ALLOWED' in said and 'target_not_dm' in said, said
    assert 'attachment' not in after

    store2, stored2 = world()
    assert outbound_media.offer(store2, CONFIG, scene_row(), 'public') is None
    public_ep = turn_ep(store2, session='public')
    assert 'attach_image' not in role_tools.exposed(store2, public_ep)
    public_ep2 = turn_ep(store2, session='public', ep_id='ep-turn-2', context={
        'image_artifacts_from_program': {'items': [{'artifact_id': stored2['artifact_id']}], 'note': ''}})
    outcome2, said2, after2 = attach(store2, public_ep2, stored2['artifact_id'], tools=['think', 'attach_image'])
    assert outcome2 == 'refused' and 'ATTACH_TARGET_NOT_ALLOWED' in said2, said2
    assert 'session_class_not_owner_private' in said2 and 'attachment' not in after2, said2
    return True, '群／非 owner_private：这回合没有 attach_image；硬调也按 target_not_dm／session_class_not_owner_private 退回'


@case
def attach_image_refuses_non_image_and_oversize_bytes():
    store, _stored = world()
    texty = BlobStore(store).put(NOT_IMAGE, DM_SCOPE, 'image')
    ep = offered_ep(store)
    assert texty['artifact_id'] in [item['artifact_id'] for item in
                                    ep['context']['image_artifacts_from_program']['items']], ep['context']
    outcome, said, after = attach(store, ep, texty['artifact_id'])
    assert outcome == 'refused' and 'ATTACHMENT_NOT_AN_IMAGE' in said and 'attachment' not in after, said

    big = {'_id': 'blob-big', 'scope_key': DM_SCOPE, 'state': 'DONE', 'kind': 'image',
           'storage': 'gridfs', 'gridfs_id': '0' * 24, 'sha256': '1' * 64,
           'size': outbound_media.MAX_ATTACHMENT_BYTES + 1, 'source_ids': [], 'created_at': 'x'}
    store.db.artifacts.insert_one(big)
    try:
        outbound_media.accept_artifact(store, BlobStore(store), 'blob-big', DM_SCOPE)
        raise AssertionError('超过上限的图被接受了')
    except Denied as exc:
        assert 'ATTACHMENT_OVER_LIMIT' in str(exc), exc
    return True, '魔数不是图 → ATTACHMENT_NOT_AN_IMAGE 退回给她；超过 8 MiB → ATTACHMENT_OVER_LIMIT'


@case
def attach_image_arguments_are_checked_one_call_at_a_time():
    store, stored = world()
    other = BlobStore(store).put(JPEG, DM_SCOPE, 'image', media_type='image/jpeg')
    ep = offered_ep(store)
    missing = call_tool(store, ep, {'why': '没给 artifact_id'})
    empty = call_tool(store, ep, {'artifact_id': '', 'why': '空的'})
    no_why = call_tool(store, ep, {'artifact_id': stored['artifact_id']})
    for outcome, said, _after in (missing, empty, no_why):
        assert outcome == 'refused' and '要写内容' in said, said
    # 自己加一个文件路径也带不进去：行上只认清单里那张的四项元数据
    pathy = call_tool(store, ep, {'artifact_id': stored['artifact_id'], 'why': '给他看', 'file': '/tmp/a.png'})
    assert pathy[0] == 'ok' and pathy[2]['attachment'] == meta_of(stored), pathy
    assert '/tmp/a.png' not in json.dumps(pathy[2]['attachment'])
    # 一回合至多一张：再调用就换成新的那张
    swapped = call_tool(store, ep, {'artifact_id': other['artifact_id'], 'why': '换这张'})
    assert swapped[0] == 'ok' and outbound_media.attachment_for_speak(swapped[2]) == \
        meta_of(other, 'image/jpeg'), swapped[2].get('attachment')
    recorded = sorted(swapped[2]['tool_calls'].values(), key=lambda row: row['seq'])
    assert [('refused' in row) for row in recorded] == [True, True, True, False, False], recorded
    return True, '缺 artifact_id／空值／缺 why 逐次退回（不整轮失败）；路径进不了元数据；第二张换掉第一张'


@case
def a_speaking_turn_carries_the_picture_on_its_speak_row():
    store, stored = world()
    ep = offered_ep(store)
    done, lane, publisher = run_turn(store, ep, FakeTurn(
        [THINK, ('attach_image', {'artifact_id': stored['artifact_id'], 'why': '他想看'})], '画好了，给你看'))
    assert done['state'] == 'COMMITTED', (done['state'], done.get('failure'))
    assert [call['phase'] for call in lane.calls] == ['TURN'] and 'attach_image' in lane.calls[0]['tools']
    rows = speak_rows(store, ep)
    assert [row['text'] for row in rows] == ['画好了，给你看'] and publisher.published == [rows[0]['_id']]
    assert rows[0]['phase'] == 'SPEAK' and rows[0]['attachment'] == meta_of(stored), rows[0].get('attachment')
    assert 'base64' not in json.dumps(rows[0], default=str)

    # 退回的那一次不带图，话照样说出去
    store2, _stored2 = world()
    ep2 = offered_ep(store2)
    done2, lane2, _p2 = run_turn(store2, ep2, FakeTurn(
        [THINK, ('attach_image', {'artifact_id': 'blob-not-offered', 'why': '他想看'})], '这张我找不到了'))
    rows2 = speak_rows(store2, ep2)
    assert done2['state'] == 'COMMITTED' and [row['text'] for row in rows2] == ['这张我找不到了'], done2['state']
    assert 'attachment' not in rows2[0], rows2[0]
    assert lane2.tool_results[1][5] is False and 'ATTACH_ARTIFACT_NOT_IN_CONTEXT' in lane2.tool_results[1][4]
    return True, 'think → attach_image → 正文：SPEAK 行带元数据；被退回时只发文字，行上没有 attachment'


@case
def a_silent_turn_sends_no_picture():
    store, stored = world()
    ep = offered_ep(store)
    done, lane, publisher = run_turn(store, ep, FakeTurn(
        [THINK, ('attach_image', {'artifact_id': stored['artifact_id'], 'why': '想给他看'}),
         ('stay_silent', {'reason': '他在忙，先不打扰'})], '不该发出去'))
    assert done['state'] == 'COMMITTED' and done['silent_reason'] == '他在忙，先不打扰', done['state']
    assert speak_rows(store, ep) == [] and publisher.published == [], '沉默的回合还是发出了东西'
    assert [result[2] for result in lane.tool_results] == ['think', 'attach_image', 'stay_silent']
    return True, 'stay_silent 结束的回合不写 SPEAK 行：接受过的图也不会跟着出去'


@case
def speak_row_writes_metadata_on_the_first_segment_only():
    '''coordinator 写 SPEAK 行那一段的守卫：只挂第一段，行上只有元数据。'''
    source = io.open(os.path.join(SRC, 'asuna', 'coordinator.py'), encoding='utf-8').read()
    assert "attach_meta=outbound_media.attachment_for_speak(ep)" in source, 'SPEAK 那一步没接上 attach_image 结果'
    assert "if index==0 and attach_meta:" in source and "row['attachment']=dict(attach_meta)" in source, \
        '附件元数据不是只挂第一段'
    assert source.index("attach_meta=outbound_media.attachment_for_speak(ep)") < \
        source.index("if index==0 and attach_meta:"), '元数据要在写行之前算好'
    ep = {'attachment': {'artifact_id': 'blob-x', 'media_type': 'image/png', 'sha256': '1' * 64, 'size': 10}}
    assert outbound_media.attachment_for_speak(ep) == {'artifact_id': 'blob-x', 'media_type': 'image/png',
                                                       'sha256': '1' * 64, 'size': 10}
    assert outbound_media.attachment_for_speak({}) is None
    assert outbound_media.attachment_for_speak({'attachment': 'blob-x'}) is None     # 形状不对就当没有
    return True, '第一段挂元数据；没有被接受的图时行上没有 attachment'


# 4) 历史投影
def delivered_row(**over):
    row = publication_row(delivery_state='DELIVERED', attempt_id='attempt-1', receipt_at='2026-10-04T15:00:00+00:00',
                          platform_message_id='700001', platform_receipt={'status': 'platform_accepted',
                                                                           'response': {}})
    row.update(over)
    return row


def attested_receipt(artifact_id, sha256, size, verified=True):
    return {'status': 'platform_accepted', 'response': {
        'attachment': {'artifact_id': artifact_id, 'media_type': 'image/png', 'sha256': sha256,
                       'declared_size': size, 'bytes': size, 'sha256_verified': verified,
                       'sniffed_media_type': 'image/png', 'content_type': 'image/png',
                       'base64_chars': size * 2}}}


def hit_of(row):
    return history_query._hit(row, {'labeler': lambda doc: '小满'}, 'text', 'receipt_at')


@case
def history_projection_shows_the_picture_i_sent():
    store, stored = world()
    row = delivered_row(attachment={'artifact_id': stored['artifact_id'], 'media_type': 'image/png',
                                    'sha256': stored['sha256'], 'size': stored['size']},
                        platform_receipt=attested_receipt(stored['artifact_id'], stored['sha256'],
                                                          stored['size']))
    hit = hit_of(row)
    slot = hit['attachment']
    assert slot['sent'] is True and slot['attested'] is True and slot['media_type'] == 'image/png'
    assert slot['bytes'] == stored['size'] and slot['sha256'] == stored['sha256']
    assert '我发过这张图' in slot['note'], slot
    line = history_query.render({'hits': [hit], 'window': ['2026-10-01', '2026-10-08'],
                                 'fallback': {}, 'next_cursor': None})
    assert '我发过这张图' in line and 'image/png' in line, line
    # 行里没带 platform_receipt 时按 _id 窄取一次（context 的投影就是这种情况）
    store.db.messages.insert_one(row)
    lean = {key: value for key, value in row.items() if key != 'platform_receipt'}
    slot2 = outbound_media.history_slot(lean, store)
    assert slot2 and slot2['sent'] is True and slot2['attested'] is True, slot2
    return True, '已送达且回执对得上 →「我发过这张图（image/png，%d 字节）」并出现在渲染里' % stored['size']


@case
def history_projection_says_when_the_picture_did_not_go():
    store, stored = world()
    attachment = {'artifact_id': stored['artifact_id'], 'media_type': 'image/png',
                  'sha256': stored['sha256'], 'size': stored['size']}
    skipped = delivered_row(attachment=dict(attachment), attachment_skipped=outbound_media.NO_CAPABILITY,
                            platform_receipt={'status': 'platform_accepted', 'response': {}})
    slot = hit_of(skipped)['attachment']
    assert slot['sent'] is False and '只有文字发出去了' in slot['note'], slot

    mismatch = delivered_row(attachment=dict(attachment),
                             platform_receipt=attested_receipt(stored['artifact_id'], 'f' * 64,
                                                               stored['size']))
    slot2 = hit_of(mismatch)['attachment']
    assert slot2['sent'] is False and slot2['reason'] == 'attachment_evidence_mismatch', slot2

    unattested = delivered_row(attachment=dict(attachment),
                               platform_receipt={'status': 'platform_accepted', 'response': {}})
    slot3 = hit_of(unattested)['attachment']
    assert slot3['sent'] is True and slot3['attested'] is False, slot3
    assert '平台回执没带附件证据' in slot3['note'], slot3

    queued = publication_row(delivery_state='QUEUED_EXTERNAL', attachment=dict(attachment))
    assert hit_of(queued).get('attachment') is None, '还没送达就别说成发过这张图'
    inbound = {'_id': 'in-1', 'scene_id': DM_SCENE, 'direction': 'inbound', 'author': 'owner-p',
               'text': '画好了吗', 'occurred_at': '2026-10-04T14:00:00+00:00', 'attachment': dict(attachment)}
    assert hit_of(inbound).get('attachment') is None, '入站行不该被写成我发过的图'
    return True, '没声明能力／回执对不上／没送达／入站行：都不算「我发过这张图」，措辞各说各的'


@case
def history_projection_of_text_only_rows_is_unchanged():
    row = delivered_row()
    hit = hit_of(row)
    assert 'attachment' not in hit, sorted(hit)
    line = history_query.render({'hits': [hit], 'window': ['2026-10-01', '2026-10-08'],
                                 'fallback': {}, 'next_cursor': None})
    assert '图' not in line, line
    assert hit['side'] == '我说' and hit['text'] == '画好了，给你看'
    return True, '没带图的命中没有 attachment 位，渲染里也不提图'


@case
def context_projection_offers_only_program_listed_images():
    store, stored = world()
    BlobStore(store).put(JPEG, DM_SCOPE, 'image', media_type='image/jpeg')
    store.db.artifacts.insert_one({'_id': 'blob-other-scope', 'scope_key': 'scene:elsewhere',
                                   'state': 'DONE', 'kind': 'image', 'storage': 'gridfs',
                                   'gridfs_id': '0' * 24, 'sha256': '2' * 64, 'size': 10,
                                   'source_ids': [], 'created_at': '2026-10-04T15:00:00+00:00'})
    store.db.artifacts.insert_one({'_id': 'blob-not-image', 'scope_key': DM_SCOPE, 'state': 'DONE',
                                   'kind': 'persona_job_report', 'storage': 'gridfs',
                                   'gridfs_id': '0' * 24, 'sha256': '3' * 64, 'size': 10,
                                   'source_ids': [], 'created_at': '2026-10-04T15:00:00+00:00'})
    offer = outbound_media.offer(store, CONFIG, scene_row(), 'owner_private')
    ids = [item['artifact_id'] for item in offer['items']]
    assert len(ids) == 2 and all(id.startswith('blob-') for id in ids), ids
    assert '文件路径' in offer['note'] and 'artifact_id' in offer['note']
    assert outbound_media.offer(store, CONFIG, scene_row('group'), 'owner_private') is None
    assert outbound_media.offer(store, CONFIG, scene_row(), 'public') is None
    # 上限：一轮最多给她看 MAX_ITEMS_OFFERED 张
    for index in range(10):
        store.db.artifacts.insert_one({'_id': 'blob-many-%d' % index, 'scope_key': DM_SCOPE,
                                       'state': 'DONE', 'kind': 'image', 'storage': 'gridfs',
                                       'gridfs_id': '0' * 24, 'sha256': '%064x' % index, 'size': 10,
                                       'source_ids': [], 'created_at': '2026-10-0%dT00:00:00+00:00'
                                       % (index % 9 + 1)})
    assert len(outbound_media.image_artifacts(store, DM_SCOPE)) == outbound_media.MAX_ITEMS_OFFERED
    return True, '只列本 scope 的 image artifact、新的在前、最多 %d 张；群／public 不给' % \
        outbound_media.MAX_ITEMS_OFFERED


@case
def sniff_table_matches_vision_and_media_types():
    samples = [PNG, JPEG, WEBP, b'GIF89a....', b'GIF87a....', NOT_IMAGE, b'', b'RIFFxxxxWEBP']
    from asuna import vision
    for sample in samples:
        assert outbound_media.sniff_media_type(sample) == vision.sniff_media_type(sample), sample[:8]
    assert outbound_media.sniff_media_type(b'RIFFxxxxWEBP') == 'image/webp'
    assert outbound_media.MEDIA_TYPES == vision.IMAGE_MEDIA_TYPES, (outbound_media.MEDIA_TYPES,
                                                                    vision.IMAGE_MEDIA_TYPES)
    assert outbound_media.MAX_ATTACHMENT_BYTES == 8 * 1024 * 1024
    assert outbound_media.supports_image(outbound_media.parse_supports({'supports': ['Image,voice']}))
    assert not outbound_media.supports_image(outbound_media.parse_supports({}))
    return True, '魔数表与 vision 逐条一致；能力解析认 supports=image（大小写不敏感）'


@case
def blobstore_get_predicate_not_loosened():
    '''字节端点用 operator 身份读，但 scope 判定仍在 BlobStore 里，非 operator 仍然一律拒。'''
    store, stored = world()
    blobs = BlobStore(store)
    try:
        blobs.get(stored['artifact_id'], DM_SCOPE)
        raise AssertionError('BlobStore.get 的 operator 谓词被放宽了')
    except Denied as exc:
        assert 'ARTIFACT_OPERATOR_VIEW_REQUIRED' in str(exc), exc
    assert blobs.get(stored['artifact_id'], DM_SCOPE, operator=True) == PNG
    try:
        blobs.get(stored['artifact_id'], 'scene:elsewhere', operator=True)
        raise AssertionError('scope 判定没生效')
    except Denied as exc:
        assert 'ARTIFACT_SCOPE_DENIED' in str(exc), exc
    return True, '非 operator 仍 ARTIFACT_OPERATOR_VIEW_REQUIRED；跨 scope 仍 ARTIFACT_SCOPE_DENIED'


@case
def prompts_say_no_file_paths_and_only_listed_artifacts():
    turn = io.open(os.path.join(SRC, 'asuna', 'resources', 'prompts', 'turn.md'), encoding='utf-8').read()
    tool = role_tools.TOOLS['attach_image']['description']
    assert 'artifact_id' in tool and 'image_artifacts_from_program' in tool, tool
    assert '文件名' in tool and '路径' in tool and '见图' in tool, tool
    assert '不是文件路径' in outbound_media.OFFER_NOTE and 'attach_image' in outbound_media.OFFER_NOTE
    assert '私聊' in role_tools.WORDS['ATTACH_TARGET_NOT_ALLOWED'], role_tools.WORDS['ATTACH_TARGET_NOT_ALLOWED']
    assert '文件路径' in turn and '见图' in turn
    return True, 'attach_image 说明只能引用程序给出的 artifact、正文不写路径／见图；群里退回时说明只有私聊能带'


# ── B7：导入时顺手登记 + 同一主人的两个 owner_private 入口 ─────────────────
# 本机私聊（config.chat.scene_id 就是它）里生图与导入，说图的那一轮在 QQ 私聊。
LOCAL_SCENE = 'local'
LOCAL_SCOPE = 'scene:' + LOCAL_SCENE
GUEST_DM = 'sc-guest-dm'
ALIAS_DM = 'sc-alias-dm'
GEN_ENDPOINTS = [{'name': 'gen', 'host': '127.0.0.1', 'port': 1}]


def two_scene_world(links=None, canonical=None, extra=()):
    """本机私聊 + QQ 私聊（都是主人自己的），按配置联动；extra 里放别人的／群的场景。"""
    config = copy.deepcopy(CONFIG)
    config['chat'] = dict(config['chat'], scene_id=LOCAL_SCENE)
    if canonical:
        config['canonical_persons'] = canonical
    if links:
        config['context_links'] = {reader: list(targets) for reader, targets in links.items()}
    store = FakeStore(config)
    store.db.scenes.insert_one({'_id': LOCAL_SCENE, 'kind': 'dm', 'scope_key': LOCAL_SCOPE,
                                'policy_epoch': 1, 'members': ['owner-p'], 'sequence': 0})
    store.db.scenes.insert_one(scene_row('dm'))
    store.db.scenes.insert_one(scene_row('group'))
    for row in extra:
        store.db.scenes.insert_one(row)
    return store


def import_bytes(store, scope_key, body, *, target='artifacts/pic.png', register='auto',
                 content_type='image/png'):
    """真走 import_integration_artifact 那份判定与写盘，只假「谁给字节」。"""
    workspace = pathlib.Path(tempfile.mkdtemp(prefix='b7-import-'))

    def fetch(endpoint, path, limit):
        return {'status': 200, 'declared': len(body), 'body': body,
                'content_type': content_type, 'transport_error': None}

    hook = (outbound_media.import_register(store, {'scope_key': scope_key})
            if register == 'auto' else register)
    result = integration_import.import_artifact(
        {'endpoint': 'gen', 'artifact_path': '/view/pic.png', 'target_relative_path': target},
        endpoints=GEN_ENDPOINTS, workspace=workspace, fetch=fetch, register=hook)
    return result, workspace


def qq_offer(store):
    return outbound_media.offer(store, store.config, scene_row('dm'), 'owner_private', 'owner-p')


@case
def imported_image_registers_as_an_image_artifact_in_its_own_scene():
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    result, workspace = import_bytes(store, LOCAL_SCOPE, PNG)
    assert result.get('imported') is True, result
    art = result['artifact']
    assert art['registered'] is True and art['artifact_id'].startswith('blob-'), art
    assert art['sha256'] == hashlib.sha256(PNG).hexdigest(), '哈希不是宿主从字节重算的那份'
    assert art['media_type'] == 'image/png' and art['bytes'] == len(PNG), art
    assert 'image_artifacts_from_program' in art['note'], art['note']
    row = store.db.artifacts.find_one({'_id': art['artifact_id']})
    assert row['scope_key'] == LOCAL_SCOPE and row['kind'] == 'image', row
    assert row['state'] == 'DONE' and row['storage'] == 'gridfs', row
    assert row['media_type'] == 'image/png' and row['created_at'], row
    assert row['source_ids'] and row['source_ids'][0].startswith('integration:gen:'), row['source_ids']
    assert (workspace / 'artifacts/pic.png').read_bytes() == PNG, '文件没写或写错了'
    # 名字与 Content-Type 都不算：字节是 jpeg 就登记成 jpeg
    store2 = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    result2, _ws = import_bytes(store2, LOCAL_SCOPE, JPEG, target='artifacts/named.png',
                                content_type='image/png')
    assert result2['artifact']['media_type'] == 'image/jpeg', result2['artifact']
    return True, '导入 %d 字节的图 → 登记进 %s（kind=image/gridfs/DONE，sha 与格式都按字节）' % (
        len(PNG), LOCAL_SCOPE)


@case
def local_image_is_offered_and_attachable_in_the_qq_dm_turn():
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    art = import_bytes(store, LOCAL_SCOPE, PNG)[0]['artifact']
    offer = qq_offer(store)
    assert offer, 'QQ 私聊那一轮没看到本机登记的图'
    listed = {item['artifact_id']: item for item in offer['items']}
    assert art['artifact_id'] in listed, sorted(listed)
    item = listed[art['artifact_id']]
    assert item['from_linked_scene'] is True and item['scene_id'] == LOCAL_SCENE, item
    assert '另一个' in offer['note'], offer['note']
    # attach_image 接受它：可引用 scope 由程序算，回合上只记元数据
    ep = turn_ep(store, context={'image_artifacts_from_program': offer})
    outcome, result, after = attach(store, ep, art['artifact_id'])
    assert outcome == 'ok', result
    meta = outbound_media.attachment_for_speak(after)
    assert meta == {'artifact_id': art['artifact_id'], 'media_type': 'image/png',
                    'sha256': art['sha256'], 'size': len(PNG)}, meta
    # 字节端点：QQ 那条 publication 能取到本机 scope 里的那份字节
    row = publication_row(delivery_state='SENDING', attempt_id='attempt-1', attachment=meta)
    store.db.messages.insert_one(row)
    server, port = with_server(store)
    try:
        code, ctype, body = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert code == 200 and ctype == 'image/png' and body == PNG, (code, ctype, body[:80])
    return True, '本机导入 → QQ 私聊清单里标着 from_linked_scene → attach_image 接受 → 字节端点 200'


@case
def only_the_same_persons_other_owner_private_scene_is_readable():
    def scopes(store, scene=None, cls='owner_private', person='owner-p'):
        return outbound_media.image_scopes(store, store.config, scene or scene_row('dm'), cls, person)

    linked = {'sc-owner-dm': [LOCAL_SCENE]}
    assert scopes(two_scene_world(links=linked)) == [DM_SCOPE, LOCAL_SCOPE], '本场景要排第一'
    # 两个都是主人自己的私人空间：联动边写哪个方向都算
    assert scopes(two_scene_world(links={LOCAL_SCENE: ['sc-owner-dm']})) == [DM_SCOPE, LOCAL_SCOPE]
    # 没联动就回到只认本场景
    assert scopes(two_scene_world()) == [DM_SCOPE]
    # 群的场景不在这个列表里
    group_only = two_scene_world(links={'sc-owner-dm': [GROUP_SCENE]})
    assert scopes(group_only) == [DM_SCOPE], '群场景被当成可引用的私人入口了'
    # 别人的私聊场景（不是同一个人）不算
    guest = {'_id': GUEST_DM, 'kind': 'dm', 'scope_key': 'scene:' + GUEST_DM, 'policy_epoch': 1,
             'members': ['guest-p']}
    other = two_scene_world(links={'sc-owner-dm': [GUEST_DM]}, extra=[guest])
    assert scopes(other) == [DM_SCOPE], '别人的私聊场景被当成主人自己的入口了'
    # 同一个人的另一个入口（配置里挂了 canonical 别名）才算
    alias = {'_id': ALIAS_DM, 'kind': 'dm', 'scope_key': 'scene:' + ALIAS_DM, 'policy_epoch': 1,
             'members': ['qq:900000003']}
    same = two_scene_world(links={'sc-owner-dm': [ALIAS_DM]},
                           canonical={'qq:900000003': 'owner-p'}, extra=[alias])
    assert scopes(same) == [DM_SCOPE, 'scene:' + ALIAS_DM], scopes(same)
    # public 会话与群方向：连本场景之外都不多开
    assert scopes(two_scene_world(links=linked), cls='public') == [DM_SCOPE]
    assert scopes(two_scene_world(links=linked), scene=scene_row('group')) == [GROUP_SCOPE]
    # 没联动时 QQ 清单里没有那张图；就算清单里冒出它，attach_image 也按 scope 退回
    store = two_scene_world()
    art = import_bytes(store, LOCAL_SCOPE, PNG)[0]['artifact']
    assert qq_offer(store) is None, '没联动的场景之间也列出图了'
    ep = turn_ep(store, context={'image_artifacts_from_program': {
        'items': [{'artifact_id': art['artifact_id']}], 'note': ''}})
    outcome, said, after = attach(store, ep, art['artifact_id'])
    assert outcome == 'refused' and 'ATTACHMENT_SCOPE_DENIED' in said and 'attachment' not in after, said
    return True, '只有同一 canonical person 的另一个 owner_private dm 场景可引用；群／别人／没联动都拒绝'


@case
def byte_endpoint_fence_follows_the_configuration_at_read_time():
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    art = import_bytes(store, LOCAL_SCOPE, PNG)[0]['artifact']
    meta = {'artifact_id': art['artifact_id'], 'media_type': 'image/png', 'sha256': art['sha256'],
            'size': len(PNG)}
    store.db.messages.insert_one(publication_row(delivery_state='SENDING', attempt_id='attempt-1',
                                                 attachment=meta))
    server, port = with_server(store)
    try:
        before = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
        store.config.pop('context_links', None)          # 删掉那条边就等于回滚
        after = http(port, '/v1/channels/qq/outbox/out-1/attachment?attempt_id=attempt-1')
    finally:
        server.close()
    assert before[0] == 200 and before[2] == PNG, before[:2]
    assert after[0] == 403 and error_code(after[2]) == 'ATTACHMENT_SCOPE_DENIED', (after[0], after[2][:200])
    return True, '同一份字节：有那条边 200，删掉边后 403 ATTACHMENT_SCOPE_DENIED（现算自配置）'


@case
def non_image_import_result_is_unchanged_and_registers_nothing():
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    body = b'{"workflow":"selfie","ready":true}'
    result, workspace = import_bytes(store, LOCAL_SCOPE, body, target='artifacts/job.json')
    assert result.get('imported') is True and 'artifact' not in result, result
    assert set(result) == {'imported', 'endpoint', 'artifact_path', 'target_relative_path', 'target_path',
                           'bytes', 'sha256', 'http_status', 'content_type', 'max_bytes',
                           'overwritten'}, sorted(result)
    assert store.db.artifacts.count_documents({}) == 0, '非图片也登记了 artifact'
    assert (workspace / 'artifacts/job.json').read_bytes() == body
    # 名字叫 .png 但字节不是图：仍然不登记（魔数说了算，不是文件名）
    fake, _ws = import_bytes(store, LOCAL_SCOPE, b'not a png at all', target='artifacts/fake.png')
    assert 'artifact' not in fake, fake['artifact']
    assert store.db.artifacts.count_documents({}) == 0
    assert outbound_media.register_imported_image(store, LOCAL_SCOPE, body) is None
    return True, '非图片导入：结果字段与改动前逐字一致，一个 artifact 都不写'


@case
def registration_failures_are_reported_without_failing_the_import():
    # 任务绑的 scope 在库里不存在 → BlobStore 认不出来，不登记
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCENE]})
    result, workspace = import_bytes(store, 'scene:nowhere', PNG)
    assert result.get('imported') is True, result
    assert result['artifact']['registered'] is False, result['artifact']
    assert 'ARTIFACT_SCOPE_UNKNOWN' in result['artifact']['reason'], result['artifact']
    assert (workspace / 'artifacts/pic.png').read_bytes() == PNG, '登记失败却把文件弄丢了'
    # 登记回调自己炸了：导入仍然成功，原因如实带回来
    def boom(data, meta=None):
        raise RuntimeError('gridfs down')

    broken = import_bytes(store, LOCAL_SCOPE, PNG, target='artifacts/boom.png', register=boom)
    assert broken[0].get('imported') is True and broken[0]['artifact']['registered'] is False, broken[0]
    assert 'gridfs down' in broken[0]['artifact']['reason'], broken[0]['artifact']
    # 超过出站上限：不登记，原因与上限都写清楚
    big = PNG + b'x' * outbound_media.MAX_ATTACHMENT_BYTES
    over = outbound_media.register_imported_image(store, LOCAL_SCOPE, big)
    assert over['registered'] is False and over['reason'] == 'ATTACHMENT_OVER_LIMIT', over
    assert over['max_bytes'] == outbound_media.MAX_ATTACHMENT_BYTES
    # 今天导入工具自己的上限就在出站上限之内，这条围栏不会被静默绕过
    assert integration_import.MAX_ARTIFACT_BYTES <= outbound_media.MAX_ATTACHMENT_BYTES
    assert store.db.artifacts.count_documents({'kind': 'image'}) == 0, '不该登记的也登记了'
    return True, 'scope 不认识／回调炸／超上限：导入都成功，artifact 里如实写未登记与原因'


@case
def the_local_scene_keeps_its_own_images_readable():
    store = two_scene_world(links={'sc-owner-dm': [LOCAL_SCOPE]})
    art = import_bytes(store, LOCAL_SCOPE, PNG)[0]['artifact']
    listed = outbound_media.image_artifacts(store, LOCAL_SCOPE)
    assert art['artifact_id'] in [item['artifact_id'] for item in listed], listed
    assert not any(item.get('from_linked_scene') for item in listed), '本场景的图不该标成别人的入口'
    # 本机这一轮的回复不走通道，所以没有「可发图」清单——图仍然登记着、读得到
    local = store.db.scenes.find_one({'_id': LOCAL_SCENE})
    assert outbound_media.offer(store, store.config, local, 'owner_private', 'owner-p') is None
    assert outbound_media.target_allowed(store.config, local, 'owner_private')[1] == \
        'scene_has_no_channel_route'
    # 同一份字节再导一次是两份 artifact（不去重），清单里新的在前
    again = import_bytes(store, LOCAL_SCOPE, PNG)[0]['artifact']
    assert again['artifact_id'] != art['artifact_id']
    order = [item['artifact_id'] for item in outbound_media.image_artifacts(store, LOCAL_SCOPE)]
    assert order[0] == again['artifact_id'], order
    return True, '本机场景里图仍登记可读；本机这一轮没有可发图清单（那条路没有通道）'


def run_all():
    results = []
    for fn in CASES:
        try:
            ok, note = fn()
        except Exception as exc:
            import traceback
            ok, note = False, '%s: %s | %s' % (type(exc).__name__, exc,
                                               traceback.format_exc().splitlines()[-3])
        results.append((fn.__name__, ok, note))
    return results


if __name__ == '__main__':
    results = run_all()
    for name, ok, note in results:
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ' — ' + note if note else ''))
    failed = [name for name, ok, _note in results if not ok]
    print('出站图片附件离线自检：%d/%d 通过' % (len(results) - len(failed), len(results)))
    if failed:
        print('失败：' + ', '.join(failed))
    sys.exit(1 if failed else 0)
