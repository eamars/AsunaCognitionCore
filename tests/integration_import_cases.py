"""集成产物导入的离线用例：端点白名单、工作区边界、默认不覆盖、上限与失败透传真算一遍。

本机 python3 tools/integration_import_offline_check.py 直接跑，不需要 Mongo、不需要 pytest、
不需要 WSL，也不出本机回路：假掉的只有「谁给字节」这一层（fetch／HTTP 连接），
判定（端点别名白名单、URL 拒绝、路径越界、覆盖规则、大小上限、失败原因映射）与
写文件、算 SHA-256 都是仓库里那份真代码在跑。t9 用真 HTTP 服务器在 127.0.0.1 上跑一遍
真取字节路径；真 WSL 命名空间下的同一条路径由操作员在宿主里复测，两者不互相代替。
"""
import hashlib
import http.client
import contextlib
import http.server
import io
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import types
from pathlib import Path

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
    '''只在真库装不上时才假：操作员在隔离宿主跑时用的是真 pymongo／真 httpx。'''
    try:
        __import__(name)
        return False
    except Exception:
        factory()
        return True


def _install_stubs():
    def bson():
        _stub('bson', BSON=types.SimpleNamespace(encode=lambda doc: b'{}'))

    def pymongo():
        root = _stub('pymongo', ASCENDING=1, MongoClient=object,
                     ReturnDocument=types.SimpleNamespace(AFTER=1), WriteConcern=lambda **kw: None)
        root.errors = _stub('pymongo.errors',
                            DuplicateKeyError=type('DuplicateKeyError', (Exception,), {}))
        root.operations = _stub('pymongo.operations', SearchIndexModel=object)

    def httpx():
        _stub('httpx', Client=lambda *a, **k: types.SimpleNamespace(timeout=None, build_request=None,
                                                                    send=None),
              Timeout=lambda *a, **k: None)

    def jsonschema():
        _stub('jsonschema', validate=lambda value, schema: None,
              ValidationError=type('ValidationError', (Exception,), {}))

    def msvcrt():
        _stub('msvcrt', setlocking=lambda handle, mode: None, locking=lambda handle: None)
        _stub('_winapi', __getattr__=lambda name: 0)

    return [name for name, factory in (('bson', bson), ('pymongo', pymongo), ('httpx', httpx),
                                       ('jsonschema', jsonschema), ('msvcrt', msvcrt))
            if _stub_when_missing(name, factory)]


STUBBED = _install_stubs()

from asuna import integration_fetch                                    # noqa: E402
from asuna.integration_import import (DEFAULT_MAX_BYTES, IMPORT_TOOL, IMPORT_TOOL_NAME,   # noqa: E402
                                      MAX_ARTIFACT_BYTES, import_artifact, integration_gated)

# 配置里已有的端点：真取字节时只用这里的地址，模型说什么都换不掉。
ENDPOINTS = [{'name': 'napcat', 'host': '192.0.2.5', 'port': 18080, 'target_port': 3001},
             {'name': 'reports', 'host': '127.0.0.1', 'port': 18081, 'target_port': 8090}]

LOCAL = {'chat': {'scene_id': 'local', 'person_id': 'owner'},
         'integration': {'enabled': True, 'scene_id': 'local', 'person_id': 'owner',
                         'endpoints': [{'name': 'napcat', 'host': '192.0.2.5', 'port': 18080,
                                        'target_port': 3001}]}}


def fetch_returning(**result):
    '''假传输：只负责「端点那边发生了什么」，判定与写文件仍走真代码。'''
    calls = []

    def fetch(endpoint, path, limit):
        calls.append({'endpoint': endpoint, 'path': path, 'limit': limit})
        return {key: (value() if callable(value) else value) for key, value in result.items()}
    fetch.calls = calls
    return fetch


def files_in(directory):
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file())


# ── 成功导入 ────────────────────────────────────────────────────────────
def t1_success_writes_bytes_and_reports_hash():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        body = b'adapter report\n' * 4
        fetch = fetch_returning(status=200, declared=len(body), body=body, content_type='text/plain')
        result = import_artifact({'endpoint': 'reports', 'artifact_path': '/reports/latest.txt',
                                  'target_relative_path': 'imports/report.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
        assert result.get('imported') is True, result
        assert result['target_relative_path'] == 'imports/report.txt', result
        assert result['target_path'] == str((workspace / 'imports/report.txt').resolve()), result
        assert result['bytes'] == len(body) and result['sha256'] == hashlib.sha256(body).hexdigest(), result
        assert result['http_status'] == 200 and result['overwritten'] is False, result
        assert (workspace / 'imports/report.txt').read_bytes() == body, '写进工作区的字节不对'
        assert files_in(workspace) == ['imports/report.txt'], files_in(workspace)
        # 地址来自配置，不是模型给的字符串。
        assert fetch.calls[0]['endpoint']['host'] == '127.0.0.1' and fetch.calls[0]['endpoint']['port'] == 18081, \
            fetch.calls
        assert fetch.calls[0]['path'] == '/reports/latest.txt', fetch.calls
        return '写入 %d 字节，sha256=%s…' % (result['bytes'], result['sha256'][:12])


# ── 未知端点（含把 URL 当端点名） ────────────────────────────────────────
def t2_unknown_endpoint_is_denied_without_fetching():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        for name in ('nope', 'http://127.0.0.1:8080', 'https://x.example', 'NAPCAT', ''):
            fetch = fetch_returning(status=200, body=b'x')
            result = import_artifact({'endpoint': name, 'artifact_path': '/a', 'target_relative_path': 'a.txt'},
                                     endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
            assert result.get('error') == 'UNKNOWN_ENDPOINT', (name, result)
            assert result['configured_endpoints'] == ['napcat', 'reports'], result
            assert not fetch.calls, '未知端点也去取了字节'
        assert files_in(workspace) == [], files_in(workspace)
        # 一个端点都没配时，任何别名都不该被放行。
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a', 'target_relative_path': 'a.txt'},
                                 endpoints=[], workspace=workspace, fetch=fetch_returning(status=200, body=b'x'))
        assert result.get('error') == 'UNKNOWN_ENDPOINT' and result['configured_endpoints'] == [], result
        return '未知别名与 URL 形式的 endpoint 全部拒绝，未发起任何请求'


# ── 任意 URL 被拒（不是通用下载器） ─────────────────────────────────────
def t3_arbitrary_url_is_rejected():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        cases = {'http://evil.example/a': 'ARTIFACT_PATH_IS_URL',
                 'https://evil.example/a': 'ARTIFACT_PATH_IS_URL',
                 '//evil.example/a': 'ARTIFACT_PATH_IS_URL',
                 '/a?next=/b': None,                            # 查询串留在本端点内，允许
                 '/a?u=http://evil.example/': 'ARTIFACT_PATH_IS_URL',   # 带 scheme 的一律不当路径
                 'reports/latest.txt': 'INVALID_ARTIFACT_PATH',  # 少了开头的 /
                 '/a/../b': 'INVALID_ARTIFACT_PATH',
                 '/a\\b': 'INVALID_ARTIFACT_PATH',
                 '/a\x07b': 'INVALID_ARTIFACT_PATH'}
        for path, expected in cases.items():
            fetch = fetch_returning(status=200, body=b'x')
            result = import_artifact({'endpoint': 'napcat', 'artifact_path': path,
                                      'target_relative_path': 'a.txt'},
                                     endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
            if expected:
                assert result.get('error') == expected, (path, result)
                assert not fetch.calls, '路径不合法却还是去取了'
            else:
                assert result.get('imported') is True, (path, result)
        assert files_in(workspace) == ['a.txt'], files_in(workspace)
        return 'URL 形式（scheme、协议相对）一律拒绝；合法路径只有端点内路径'


# ── 目标路径越界 ────────────────────────────────────────────────────────
def t4_target_path_escape_is_denied():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        (workspace / 'keep.txt').write_bytes(b'keep')
        bad = ['../escape.txt', 'a/../../x', '../../etc/passwd', '/etc/passwd', 'C:evil.txt', 'C:/evil.txt',
               'a//b', 'dir/', './a.txt', 'a/./b.txt', 'a\x00b']
        for relative in bad:
            fetch = fetch_returning(status=200, body=b'x')
            result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a',
                                      'target_relative_path': relative},
                                     endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
            assert result.get('error') in ('TARGET_PATH_MUST_BE_RELATIVE', 'INVALID_TARGET_PATH'), \
                (relative, result)
            assert not fetch.calls, '路径不合法却还是去取了'
        assert files_in(workspace) == ['keep.txt'], files_in(workspace)
        assert (workspace / 'keep.txt').read_bytes() == b'keep'
        assert not (workspace.parent / 'escape.txt').exists(), '写到工作区外面去了'
        note = '绝对路径、盘符、.. 与怪字符全部拒绝，工作区外没有多出文件'
        # 符号链接指向外面时也要挡住（Windows 上没权限建符号链接就跳过这一项）。
        try:
            link = workspace / 'link.txt'
            outside = Path(tempfile.mkdtemp()) / 'outside.txt'
            outside.write_bytes(b'outside')
            link.symlink_to(outside)
            result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a',
                                      'target_relative_path': 'link.txt'},
                                     endpoints=ENDPOINTS, workspace=workspace,
                                     fetch=fetch_returning(status=200, body=b'x'))
            assert result.get('error') == 'TARGET_PATH_OUTSIDE_WORKSPACE', result
            assert outside.read_bytes() == b'outside', '符号链接被写穿了'
            note += '；符号链接指向外面也挡住'
        except (OSError, NotImplementedError) as exc:
            note += '；符号链接项跳过（%s）' % type(exc).__name__
        return note


# ── 默认不覆盖 ──────────────────────────────────────────────────────────
def t5_default_does_not_overwrite():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        target = workspace / 'out' / 'report.txt'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'original')
        fetch = fetch_returning(status=200, body=b'brand new')
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/report',
                                  'target_relative_path': 'out/report.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
        assert result.get('error') == 'TARGET_EXISTS', result
        assert result['existing_bytes'] == len(b'original'), result
        assert target.read_bytes() == b'original', '默认不覆盖却没保住原文件'
        assert not fetch.calls, '目标已存在还去取了字节'
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/report',
                                  'target_relative_path': 'out/report.txt', 'overwrite': True},
                                 endpoints=ENDPOINTS, workspace=workspace,
                                 fetch=fetch_returning(status=200, body=b'brand new'))
        assert result.get('imported') is True and result['overwritten'] is True, result
        assert target.read_bytes() == b'brand new', target.read_bytes()
        # 目录不能当文件覆盖；overwrite 只接受真正的布尔值。
        (workspace / 'dir').mkdir()
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a', 'target_relative_path': 'dir'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
        assert result.get('error') == 'TARGET_IS_DIRECTORY', result
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a', 'target_relative_path': 'x.txt',
                                  'overwrite': 'true'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
        assert result.get('error') == 'INVALID_OVERWRITE', result
        return '默认保住原文件（且不去取字节）；overwrite=true 才替换'


# ── 大小上限 ────────────────────────────────────────────────────────────
def t6_size_limit_is_enforced_before_writing():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/big', 'max_bytes': 100,
                                  'target_relative_path': 'big.bin'},
                                 endpoints=ENDPOINTS, workspace=workspace,
                                 fetch=fetch_returning(status=200, declared=5000, body=b''))
        assert result.get('error') == 'ARTIFACT_TOO_LARGE', result
        assert result['declared_bytes'] == 5000 and result['max_bytes'] == 100, result
        assert files_in(workspace) == [], files_in(workspace)
        # 没有 Content-Length 时按实际读回的字节数判（真取字节最多读 limit+1）。
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/big', 'max_bytes': 100,
                                  'target_relative_path': 'big.bin'},
                                 endpoints=ENDPOINTS, workspace=workspace,
                                 fetch=fetch_returning(status=200, declared=None, body=b'x' * 101))
        assert result.get('error') == 'ARTIFACT_TOO_LARGE', result
        assert result['bytes_read'] == 101 and result['max_bytes'] == 100, result
        assert files_in(workspace) == [], files_in(workspace)
        for bad in (0, -1, MAX_ARTIFACT_BYTES + 1, '1024', None):
            fetch = fetch_returning(status=200, body=b'x')
            args = {'endpoint': 'napcat', 'artifact_path': '/a', 'target_relative_path': 'a.txt'}
            if bad is not None:
                args['max_bytes'] = bad
            result = import_artifact(args, endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
            if bad is None:
                assert result.get('imported') is True and result['max_bytes'] == DEFAULT_MAX_BYTES, result
            else:
                assert result.get('error') == 'INVALID_MAX_BYTES', (bad, result)
                assert not fetch.calls, '上限不合法却还是去取了'
        assert DEFAULT_MAX_BYTES <= MAX_ARTIFACT_BYTES, (DEFAULT_MAX_BYTES, MAX_ARTIFACT_BYTES)
        return '声明超限与实际读回超限都不写文件；默认上限 %d 字节，硬顶 %d 字节' % (DEFAULT_MAX_BYTES, MAX_ARTIFACT_BYTES)


# ── 失败状态透传 ────────────────────────────────────────────────────────
def t7_http_status_and_transport_are_passed_through():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        for status in (302, 401, 403, 404, 429, 500, 503):
            fetch = fetch_returning(status=status, declared=0, body=b'')
            result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/x',
                                      'target_relative_path': 'x.txt'},
                                     endpoints=ENDPOINTS, workspace=workspace, fetch=fetch)
            assert result.get('error') == 'ARTIFACT_HTTP_STATUS', (status, result)
            assert result['http_status'] == status, result
        assert files_in(workspace) == [], files_in(workspace)
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/moved', 'target_relative_path': 'm.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace,
                                 fetch=fetch_returning(status=301, location='http://elsewhere.example/m', body=b''))
        assert result.get('error') == 'ARTIFACT_HTTP_STATUS' and result['http_status'] == 301, result
        assert result.get('location') == 'http://elsewhere.example/m', result
        assert files_in(workspace) == [], '重定向被自动跟了'
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/x', 'target_relative_path': 'x.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace,
                                 fetch=fetch_returning(transport_error='ConnectionRefusedError: [Errno 111]'))
        assert result.get('error') == 'ARTIFACT_TRANSPORT_FAILED', result
        assert 'ConnectionRefusedError' in result['detail'], result
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/x', 'target_relative_path': 'x.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=fetch_returning(body=b'x'))
        assert result.get('error') == 'ARTIFACT_TRANSPORT_FAILED', result
        result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/x', 'target_relative_path': 'x.txt'},
                                 endpoints=ENDPOINTS, workspace=workspace, fetch=lambda *a: None)
        assert result.get('error') == 'ARTIFACT_TRANSPORT_FAILED', result
        return '非 200 一律带真实状态返回（302 不跟随），取不到字节报传输失败'


# ── 只读输入不被写穿 ────────────────────────────────────────────────────
def t8_protected_input_is_not_overwritten():
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        protected = workspace / 'input.json'
        protected.write_text('{"frozen":true}', encoding='utf-8')
        for relative in ('input.json', 'input.json'):
            fetch = fetch_returning(status=200, body=b'stale')
            result = import_artifact({'endpoint': 'napcat', 'artifact_path': '/a',
                                      'target_relative_path': relative},
                                     endpoints=ENDPOINTS, workspace=workspace, fetch=fetch,
                                     protected=[protected])
            assert result.get('error') == 'TARGET_PATH_PROTECTED', (relative, result)
            assert not fetch.calls, '只读输入也去取了字节'
        assert protected.read_text(encoding='utf-8') == '{"frozen":true}'
        return '任务里只读的输入文件不会被导入覆盖'


# ── 真 HTTP：127.0.0.1 上真取一次字节 ──────────────────────────────────
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/ok':
            body = b'integration artifact body\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith('/big'):
            self.send_response(200)
            self.send_header('Content-Length', '100000')
            self.end_headers()
            self.wfile.write(b'x' * 4096)
        elif self.path.startswith('/streamed'):
            self.send_response(200)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            for _ in range(8):
                self.wfile.write(b'%x\r\n' % 64 + b'y' * 64 + b'\r\n')
            self.wfile.write(b'0\r\n\r\n')
        elif self.path.startswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1:1/elsewhere')
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()


def _serving():
    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def t9_real_http_get_reads_bytes_and_reports_status():
    server = _serving()
    port = server.server_address[1]
    closed = False
    try:
        ok = integration_fetch.http_get('127.0.0.1', port, '/ok', 1024, 5)
        assert ok['status'] == 200 and ok['body'] == b'integration artifact body\n', ok
        assert ok['declared'] == len(ok['body']) and ok['content_type'] == 'text/plain', ok
        missing = integration_fetch.http_get('127.0.0.1', port, '/missing', 1024, 5)
        assert missing['status'] == 404 and missing['transport_error'] is None, missing
        big = integration_fetch.http_get('127.0.0.1', port, '/big', 100, 5)
        assert big['status'] == 200 and big['declared'] == 100000 and big['body'] == b'', \
            '声明超限就该停止读体：%s' % {k: v for k, v in big.items() if k != 'body'}
        streamed = integration_fetch.http_get('127.0.0.1', port, '/streamed', 200, 5)
        assert streamed['status'] == 200 and len(streamed['body']) <= 201, \
            {k: v for k, v in streamed.items() if k != 'body'}
        redirect = integration_fetch.http_get('127.0.0.1', port, '/redirect', 1024, 5)
        assert redirect['status'] == 302 and redirect['location'] == 'http://127.0.0.1:1/elsewhere', redirect
        server.shutdown(); server.server_close(); closed = True   # 真把端口关掉
        dead = integration_fetch.http_get('127.0.0.1', port, '/ok', 1024, 2)
        assert dead['transport_error'] and dead['status'] is None, dead
        return '真 HTTP 往返：200 取到 %d 字节、404 透传、声明超限不读体、chunked 最多读 limit+1' % len(ok['body'])
    finally:
        if not closed:
            server.shutdown(); server.server_close()


def t10_real_fetch_feeds_the_platform_writer():
    '''真 HTTP 字节 → 真判定 → 真写工作区，串起来跑一遍。'''
    server = _serving()
    port = server.server_address[1]
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        endpoints = [{'name': 'local', 'host': '127.0.0.1', 'port': port, 'target_port': port}]

        def fetch(endpoint, path, limit):
            return integration_fetch.http_get(endpoint['host'], endpoint['port'], path, limit, 5)
        try:
            result = import_artifact({'endpoint': 'local', 'artifact_path': '/ok',
                                      'target_relative_path': 'artifacts/ok.txt'},
                                     endpoints=endpoints, workspace=workspace, fetch=fetch)
            assert result.get('imported') is True, result
            written = (workspace / 'artifacts/ok.txt').read_bytes()
            assert written == b'integration artifact body\n', written
            assert result['sha256'] == hashlib.sha256(written).hexdigest(), result
            over = import_artifact({'endpoint': 'local', 'artifact_path': '/big', 'max_bytes': 100,
                                    'target_relative_path': 'artifacts/big.bin'},
                                   endpoints=endpoints, workspace=workspace, fetch=fetch)
            assert over.get('error') == 'ARTIFACT_TOO_LARGE' and over['declared_bytes'] == 100000, over
            assert (workspace / 'artifacts/big.bin').exists() is False, '超限却还是留了文件'
            gone = import_artifact({'endpoint': 'local', 'artifact_path': '/missing',
                                    'target_relative_path': 'artifacts/missing.txt'},
                                   endpoints=endpoints, workspace=workspace, fetch=fetch)
            assert gone.get('error') == 'ARTIFACT_HTTP_STATUS' and gone['http_status'] == 404, gone
            assert (workspace / 'artifacts/missing.txt').exists() is False
            return '真取字节写进 %s，sha256=%s…；超限与 404 都没留下文件' % (
                result['target_relative_path'], result['sha256'][:12])
        finally:
            server.shutdown()
            server.server_close()


# ── 命名空间里那份取字节脚本的报告契约 ──────────────────────────────────
def t11_fetch_script_report_contract():
    '''脚本 main 的报告：别名再核一遍、只写 200 的体、字节数与 SHA-256 一起报。'''
    original = (integration_fetch.CONFIG_PATH, integration_fetch.BODY_PATH, integration_fetch.http_get)
    with tempfile.TemporaryDirectory() as raw:
        config = Path(raw) / 'config.json'
        config.write_text(json.dumps({'endpoints': {'napcat': {'host': '127.0.0.1', 'port': 18080}}}),
                          encoding='utf-8')
        body_path = Path(raw) / 'artifact.bin'
        integration_fetch.CONFIG_PATH = str(config)
        integration_fetch.BODY_PATH = str(body_path)
        try:
            def report(request, body=b'artifact', status=200, declared=None, error=None):
                def fake(host, port, path, limit, timeout, connect=None):
                    fake.seen = {'host': host, 'port': port, 'path': path, 'limit': limit}
                    return {'status': status, 'declared': declared, 'content_type': None,
                            'location': None, 'transport_error': error, 'body': body}
                integration_fetch.http_get = fake
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    integration_fetch.main(['integration_fetch.py', json.dumps(request)])
                return json.loads(buffer.getvalue().strip()), fake

            value, fake = report({'endpoint': 'napcat', 'path': '/report', 'limit': 1024, 'timeout': 5})
            assert value['status'] == 200 and value['bytes'] == len(b'artifact'), value
            assert value['sha256'] == hashlib.sha256(b'artifact').hexdigest(), value
            assert body_path.read_bytes() == b'artifact', '200 的体没写进 /data'
            assert fake.seen == {'host': '127.0.0.1', 'port': 18080, 'path': '/report', 'limit': 1024}, fake.seen
            value, _ = report({'endpoint': 'evil', 'path': '/report', 'limit': 1024},
                              body=b'should not be fetched')
            assert value['status'] is None and 'ENDPOINT_NOT_CONFIGURED' in value['transport_error'], value
            body_path.unlink()
            value, _ = report({'endpoint': 'napcat', 'path': '/gone', 'limit': 1024}, body=b'', status=404)
            assert value['status'] == 404 and value['bytes'] == 0, value
            assert not body_path.exists(), '非 200 也写了体文件'
            value, _ = report({'endpoint': 'napcat', 'path': 'http://evil.example/a', 'limit': 1024})
            assert 'INVALID_FETCH_REQUEST' in value['transport_error'], value
            value, _ = report({'endpoint': 'napcat', 'path': '/report', 'limit': 10 ** 9})
            assert 'INVALID_FETCH_REQUEST' in value['transport_error'], value
            value, _ = report({'endpoint': 'napcat', 'path': '/report', 'limit': 1024},
                              status=None, body=b'', error='TimeoutError: timed out')
            assert value['status'] is None and 'TimeoutError' in value['transport_error'], value
            assert not body_path.exists(), '取失败也写了体文件'
            return '别名再核、只写 200 的体、URL 与超限在命名空间里也被挡住'
        finally:
            integration_fetch.CONFIG_PATH, integration_fetch.BODY_PATH, integration_fetch.http_get = original


# ── 闸门：QQ 任务拿不到这个工具 ─────────────────────────────────────────
def t12_tool_is_only_in_the_owner_integration_group():
    from asuna.integration import INTEGRATION_TOOLS, event_granted, owner_profile
    from asuna.state import Denied
    names = [tool['name'] for tool in INTEGRATION_TOOLS]
    assert IMPORT_TOOL in INTEGRATION_TOOLS and names.count(IMPORT_TOOL_NAME) == 1, names
    assert integration_gated(IMPORT_TOOL_NAME) and integration_gated('integration_status'), '导入工具没被闸门认出来'
    assert not integration_gated('read_file') and not integration_gated('sandbox_run'), '普通工具被误认成集成工具'
    assert not integration_gated(None) and not integration_gated(IMPORT_TOOL_NAME.upper())
    # 能力清单的推导跟 tasks.py / coordinator.py 一样：只有 event_granted 为真才并入这一组。
    owner_event = {'scene_id': 'local', 'person_id': 'owner', 'integration_profile': 'owner'}
    qq_event = {'scene_id': 'group-a', 'person_id': 'qq:A'}   # QQ 任务的事件不带 integration_profile
    assert event_granted(LOCAL, owner_event) is True, '本机 owner 私聊场景没通过闸门'
    owner_allowed = [t['name'] for t in INTEGRATION_TOOLS if event_granted(LOCAL, owner_event)]
    assert IMPORT_TOOL_NAME in owner_allowed, owner_allowed
    assert event_granted(LOCAL, qq_event) is False, 'QQ 场景的事件不该被认成 owner 集成授权'
    qq_allowed = [t['name'] for t in INTEGRATION_TOOLS if event_granted(LOCAL, qq_event)]
    assert IMPORT_TOOL_NAME not in qq_allowed, qq_allowed
    # QQ 事件自己声称 integration_profile=owner 也不算：闸门看的是场景与人，不是消息里的字。
    forged_events = (dict(qq_event, integration_profile='owner'),
                    {'scene_id': 'local', 'person_id': 'stranger', 'integration_profile': 'owner'})
    for forged in forged_events:
        try:
            event_granted(LOCAL, forged)
            raise AssertionError('不该通过闸门：%s' % forged)
        except Denied as exc:
            assert 'INTEGRATION_OWNER_REQUIRED' in str(exc), exc
    # 宿主设置里关掉开关，等于收回授权：老任务也不能再用。
    off = json.loads(json.dumps(LOCAL))
    off['integration']['enabled'] = False
    try:
        event_granted(off, owner_event)
        raise AssertionError('关掉开关后仍然放行')
    except Denied as exc:
        assert 'INTEGRATION_OWNER_REQUIRED' in str(exc), exc
    return '工具只在 owner 集成组里；QQ 场景、外人场景与关闭开关都进不来'


def t13_workspace_tools_do_not_carry_it():
    '''普通工作区工具清单里没有它：QQ 任务的基础能力清单不可能包含导入。'''
    try:
        from asuna.tasks import WORKSPACE_TOOLS
    except Exception as exc:
        raise AssertionError('真 tasks.py 装不上（%s: %s）；这条要操作员在宿主里跑' % (type(exc).__name__, exc))
    names = [tool['name'] for tool in WORKSPACE_TOOLS]
    assert IMPORT_TOOL_NAME not in names, names
    from asuna.integration import INTEGRATION_TOOLS
    assert IMPORT_TOOL_NAME in [tool['name'] for tool in INTEGRATION_TOOLS]
    spec = next(tool for tool in INTEGRATION_TOOLS if tool['name'] == IMPORT_TOOL_NAME)
    assert set(spec['parameters']) == {'endpoint', 'artifact_path', 'target_relative_path',
                                       'overwrite', 'max_bytes'}, spec
    assert spec['parameters']['endpoint']['required'] is True, spec
    return 'WORKSPACE_TOOLS 不含导入工具；参数面固定为 endpoint/artifact_path/target_relative_path'


CASES = [t1_success_writes_bytes_and_reports_hash, t2_unknown_endpoint_is_denied_without_fetching,
         t3_arbitrary_url_is_rejected, t4_target_path_escape_is_denied, t5_default_does_not_overwrite,
         t6_size_limit_is_enforced_before_writing, t7_http_status_and_transport_are_passed_through,
         t8_protected_input_is_not_overwritten, t9_real_http_get_reads_bytes_and_reports_status,
         t10_real_fetch_feeds_the_platform_writer, t11_fetch_script_report_contract,
         t12_tool_is_only_in_the_owner_integration_group, t13_workspace_tools_do_not_carry_it]


def run_all():
    results = []
    for case in CASES:
        try:
            results.append((case.__name__, True, case()))
        except AssertionError as exc:
            results.append((case.__name__, False, str(exc) or '断言失败'))
        except Exception as exc:            # 夹具没接住也要报成失败，不冒充通过
            results.append((case.__name__, False, '%s: %s' % (type(exc).__name__, exc)))
    return results


if __name__ == '__main__':
    for name, ok, note in run_all():
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ' — ' + note if note else ''))
