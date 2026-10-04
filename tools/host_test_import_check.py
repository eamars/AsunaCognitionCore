"""宿主测试文件的导入自检：没装 pytest／pymongo 也能先保证「收集阶段不会红」。

用法：``python3 tools/host_test_import_check.py``（在候选根目录跑）。

它造一套「装了库」的环境（gridfs 故意像真库那样对非 Database 的假 DB 抛 TypeError，
bson／pymongo／httpx／msvcrt／_winapi 都可导入）再假一个 pytest，把改过的宿主测试文件真导进来
一遍：import 名、模块级代码、被引用的产品符号都要成立。断言跑不了——那要真 Mongo 与真夹具世界，
由操作员在宿主上跑 pytest。核心候选里没有 packages/napcat-qq，所以 conftest 用替身挂上
测试模块要用的那几个名字。
"""
import pathlib
import sys
import tempfile
import types

env = pathlib.Path(tempfile.mkdtemp(prefix='b7-fakeenv-'))
(env/'gridfs.py').write_text('\n'.join([
    'class GridFSBucket:',
    '    def __init__(self, db, bucket_name=None):',
    '        raise TypeError("database must be an instance of Database")', '']) , encoding='utf-8')
(env/'bson.py').write_text('\n'.join([
    'class BSON:',
    '    def __init__(self, doc): self.doc = doc',
    '    def encode(self): return b"x"',
    'class ObjectId:',
    '    def __init__(self, v=None): self.v = v', '']), encoding='utf-8')
(env/'httpx.py').write_text('\n'.join([
    'class Client:',
    '    def __init__(self, *a, **k): pass',
    '    def __enter__(self): return self',
    '    def __exit__(self, *a): return False',
    '    def get(self, *a, **k): raise RuntimeError("offline")',
    'class Timeout:',
    '    def __init__(self, *a, **k): pass', '']), encoding='utf-8')
(env/'msvcrt.py').write_text('\n'.join([
    'LK_NBLCK = 1', 'LK_UNLCK = 2', 'def locking(*a): pass', 'def setlocking(*a): pass', '']),
    encoding='utf-8')
(env/'_winapi.py').write_text('def __getattr__(name):\n    return 0\n', encoding='utf-8')
pkg = env/'pymongo'
pkg.mkdir()
(pkg/'__init__.py').write_text('\n'.join([
    'ASCENDING = 1',
    'class MongoClient:',
    '    def __init__(self, *a, **k): pass',
    'class ReturnDocument:',
    '    AFTER = 1',
    'class WriteConcern:',
    '    def __init__(self, **k): pass', '']), encoding='utf-8')
(pkg/'errors.py').write_text('\n'.join([
    'class DuplicateKeyError(Exception): pass',
    'class ConfigurationError(Exception): pass', '']), encoding='utf-8')
(pkg/'operations.py').write_text('\n'.join([
    'class SearchIndexModel:',
    '    def __init__(self, *a, **k): pass',
    'class UpdateOne:',
    '    def __init__(self, *a, **k): pass',
    'class IndexModel:',
    '    def __init__(self, *a, **k): pass', '']), encoding='utf-8')

pytest = types.ModuleType('pytest')


class _Raises:
    def __enter__(self):
        return types.SimpleNamespace(value=None)

    def __exit__(self, exc_type, exc, tb):
        return False


pytest.raises = lambda *a, **k: _Raises()
pytest.fixture = lambda *a, **k: (lambda fn: fn)
pytest.mark = types.SimpleNamespace(skip=lambda *a, **k: (lambda fn: fn),
                                    parametrize=lambda *a, **k: (lambda fn: fn))
sys.modules['pytest'] = pytest
sys.path[:0] = [str(env), 'tests', 'src']

import bson, gridfs, httpx, pymongo                              # noqa: E402  「装了库」的环境成立
print('FAKE_ENV_OK bson/gridfs/httpx/pymongo 都可导入（gridfs 会像真库一样拒假 DB）')

# conftest 在核心候选里装不起来：它要 packages/napcat-qq 那个插件包（不在本候选里）与真 Mongo
# 夹具世界。这里只把测试模块从它取的名字挂上——本检查保证的是「收集阶段成立」，不是断言通过。
sys.modules['conftest'] = types.SimpleNamespace(
    FIXTURES=pathlib.Path('tests/fixtures'), WORLD=pathlib.Path('tests/fixtures/world.json'))

import test_outbound_image as host                               # noqa: E402
names = sorted(name for name in dir(host) if name.startswith('test_'))
print('IMPORT_OK tests/test_outbound_image.py:', len(names), '个 test')
for name in names:
    print('  -', name)

# 模块级引用的产品符号都要存在：少一个名字就是宿主收集阶段就红
for attribute in ('offer', 'image_scopes', 'row_image_scopes', 'register_imported_image',
                  'import_register', 'history_slot', 'NO_CAPABILITY', 'MAX_ATTACHMENT_BYTES'):
    assert hasattr(host.outbound_media, attribute), attribute
for attribute in ('Channels', 'Coordinator', 'persist_input', 'FakeLane', 'LaneResult', 'Denied',
                  'BlobStore', 'import_artifact', 'MAX_ARTIFACT_BYTES', 'decide', 'owner'):
    assert getattr(host, attribute, None) is not None, attribute
print('SYMBOLS_OK')

# 顺带把改过的另一个宿主测试文件也做同样的导入检查
import test_integration                                          # noqa: E402
assert hasattr(test_integration, 'test_import_artifact_is_written_into_the_bound_task_workspace')
print('IMPORT_OK tests/test_integration.py')

# 多轮 DECIDE 去重那组宿主用例：本机跑不了断言（要真 Mongo 与真夹具世界），先保证收集阶段成立
import test_decide_delta_rounds as rounds                         # noqa: E402
names = sorted(name for name in dir(rounds) if name.startswith('test_'))
print('IMPORT_OK tests/test_decide_delta_rounds.py:', len(names), '个 test')
for name in names:
    print('  -', name)
for attribute in ('semantic_key', 'KEY_FIELDS', 'LAST_ROUND_WINS', 'READ_FIELD', 'validate_items', 'apply',
                  'read_sections', '_promote', '_recall_will_read'):
    assert hasattr(rounds.decide_delta, attribute), attribute
for attribute in ('queue', 'place', 'STATE_WORDS', 'KIND_WORDS'):
    assert hasattr(rounds.group_admin, attribute), attribute
assert hasattr(rounds.outbound_media, 'attachment_for_speak'), 'attach 的取法被改没了'
for attribute in ('Coordinator', 'DocumentStore', 'FakeLane', 'LaneResult', 'persist_input', 'decide', 'owner',
                  'event', 'import_bytes', 'channel_scene', 'link', 'speak_rows', 'attach_rejections',
                  'PNG', 'JPEG', 'LOCAL', 'LOCAL_SCOPE'):
    assert getattr(rounds, attribute, None) is not None, attribute
print('SYMBOLS_OK tests/test_decide_delta_rounds.py')
