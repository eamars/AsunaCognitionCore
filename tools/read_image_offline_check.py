#!/usr/bin/env python3
"""看图（read_image）离线自检：零依赖、不联网，真跑一次本机 HTTP 拉取与插件投影。

覆盖：
1. 真实入站元数据形状（照抄线上带图消息的 `event.raw.asuna_media`）→ 有界附件清单；
1a. A2 只读联动：配置里那条边指向的场景里的图也能拉，范围仍现算自配置（删键即回滚）；
2. 能力门（只看配置声明，不按模型名猜）与 allowed_capabilities 裁剪；
3. 真拉取：本机 HTTP 服务 + 真 PNG 字节，全链路核对 sha256 / 字节 / BlobStore / base64；
4. 错误面：超限、非图片、404、重定向出白名单、明文 http、白名单外主机、越场景、
   未知 ref、能力未开、非法参数——都必须是真实错误码，不假装看过；
5. 回执有界：写进 artifacts 的副本不带 base64；
6. 插件投影（装载真 dsh-plugin/tools.ts，只替换那一行包导入）：saveImage 收到原字节
   → ImageBlock + 元数据文本块；附件服务缺失 / 保存失败都如实标 unavailable；
   外加 inject 声明断言——DSH 只放行 inject 列过的 ctx 服务，假 ctx 照不出这条运行时闸门；
7. TokenMeter：内联图片不再被当成文本字节，但份数与字节数如实报；
8. 本机文件目录路径与目录穿越防护。

本机自检用明文 http（所以显式放行 allow_insecure_http）；生产 QQ 链接是 https，
同一条规则在那里会先过 scheme 闸门。退出码：0 全过；1 有用例失败（node 缺失算失败，不静默跳过）。
"""
from __future__ import annotations
import base64
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import types
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'asuna'
FAILURES: list[str] = []
NOTES: list[str] = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + ((' | ' + str(detail)) if detail else ''))
    if not ok:
        FAILURES.append(name)


def png_bytes(width=8, height=6, rgb=(16, 96, 176)):
    """真 PNG（IHDR/IDAT/IEND 带 CRC），不是随手拼的魔数——DSH 的 sharp 也要能收。"""
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))

    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


# ── 真实入站元数据（线上 in-ep-435b26313c18e27b84c855c89e7ada05 的形状）────────
PNG = png_bytes()
PNG_B64 = base64.b64encode(PNG).decode()
MEDIA_MESSAGE = {
    '_id': 'in-ep-435b26313c18e27b84c855c89e7ada05', 'scene_id': 'dm:718372664:3854949696',
    'policy_epoch': 'epoch-selfdev-1', 'scene_seq': 41, 'direction': 'inbound',
    'text': '[图片（未解析）]',
    'event': {'event_id': 'ep-435b26313c18e27b84c855c89e7ada05',
              'raw': {'message_id': 872, 'post_type': 'message', 'asuna_media': {
                  'version': 1, 'count': 2, 'truncated': False, 'items': [
                      {'type': 'image', 'placeholder': '[图片（未解析）]',
                       'file': '2411cf00a42d592c44188041c19e1d29.png', 'file_id': '33855',
                       'url': 'https://multimedia.nt.qq.com.cn/download?file_md5=2411CF00A42D592C44188041C19E1D29',
                       'size': '46695', 'summary': '', 'sub_type': 0},
                      {'type': 'record', 'placeholder': '[语音（未解析）]', 'file': '', 'file_id': '',
                       'url': '', 'size': '0', 'summary': '', 'sub_type': 0}]}}}}
TASK = {'_id': 'task-1', 'scene_id': 'dm:718372664:3854949696', 'scope_key': 'dm:718372664:3854949696',
        'policy_epoch': 'epoch-selfdev-1'}


# ── 最小 store 替身：只实现 vision.py 用到的那几个查询 ─────────────────────────
class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, key, direction=1):
        self.rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def limit(self, n):
        return list(self.rows[:n])


def _matches(row, query):
    for key, want in query.items():
        found = row
        for part in key.split('.'):
            if not isinstance(found, dict) or part not in found:
                return False
            found = found[part]
        if found != want:
            return False
    return True


class Collection:
    def __init__(self, rows):
        self.rows = rows

    def find_one(self, query):
        return next((row for row in self.rows if _matches(row, query)), None)

    def find(self, query, projection=None):
        return Cursor([row for row in self.rows if _matches(row, query)])


class FakeStore:
    def __init__(self, scenes, messages):
        self.db = types.SimpleNamespace(scenes=Collection(scenes), messages=Collection(messages))


class FakeBlobs:
    def __init__(self):
        self.saved = []

    def put(self, data, scope, kind, source_ids=None):
        self.saved.append({'bytes': data, 'scope': scope, 'kind': kind, 'source_ids': source_ids})
        return {'artifact_id': 'blob-fake-1', 'sha256': hashlib.sha256(data).hexdigest(),
                'scope_key': scope, 'kind': kind, 'bytes': len(data)}


# ── 本机 HTTP：真 socket、真重定向、真 404 ─────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802
        kind = self.routes.get(self.path.split('?')[0], 'missing')
        if kind == 'png':
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
        elif kind == 'html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>not an image</body></html>')
        elif kind == 'big':
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            for _ in range(40):
                self.wfile.write(b'\x00' * 65536)
        elif kind == 'expired':
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"retcode":-5503007,"retmsg":"download url has expired",'
                             b'"rkey":"CAESMGoieAXqbqKk"}')
        elif kind == 'redirect-out':
            self.send_response(302)
            self.send_header('Location', 'http://localhost:%d/png' % self.server.server_port)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix='read-image-check-'))
    # 装真文件：vision.py / evidence.py / config.py / tokens.py 原样复制；
    # state.py 只替 Denied（真 state.py 顶层要 import pymongo，本检查没有）。
    pkg = work / 'asuna_pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    sys.modules['httpx'] = types.ModuleType('httpx')  # evidence.py 顶层 import，本检查不出网
    # scene_links.py 也得带上：真 vision.py 现在从同包读只读联动范围
    for name in ('vision.py', 'evidence.py', 'config.py', 'tokens.py', 'scene_links.py'):
        shutil.copy(SRC / name, pkg / name)
    (pkg / 'state.py').write_text('class Denied(PermissionError):\n    pass\n', encoding='utf-8')
    sys.path.insert(0, work.as_posix())
    from asuna_pkg import tokens as token_module
    from asuna_pkg import vision

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Handler.routes = {'/png': 'png', '/html': 'html', '/big': 'big', '/expired': 'expired',
                    '/redirect-out': 'redirect-out'}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'

    def config(*, hosts=('127.0.0.1', 'multimedia.nt.qq.com.cn'), modalities=('text', 'image'),
               insecure=True, image_dirs=(), max_bytes=4 * 1024 * 1024):
        return {'task_mode': 'workspace', 'executor': {'input_modalities': list(modalities)},
                'vision': {'image_hosts': list(hosts), 'allow_insecure_http': insecure,
                           'image_dirs': list(image_dirs), 'max_bytes': max_bytes, 'timeout_seconds': 5}}

    def store_with(url, *, scene_ok=True):
        scene = {'_id': TASK['scene_id'], 'scope_key': TASK['scope_key'] if scene_ok else 'other',
                 'policy_epoch': TASK['policy_epoch']}
        message = json.loads(json.dumps(MEDIA_MESSAGE))
        message['event']['raw']['asuna_media']['items'][0]['url'] = url
        return FakeStore([scene], [message])

    try:
        # 1. 真实元数据 → 有界清单
        items = vision.attachments_of(MEDIA_MESSAGE, config=config())
        ref = items[0]['ref']
        check('元数据清单只列图片并给出稳定 ref', len(items) == 1 and items[0]['type'] == 'image'
              and ref == vision.ref_of(MEDIA_MESSAGE['_id'], 0), items)
        check('清单保留诚实占位符与声明字节', items[0]['placeholder'] == '[图片（未解析）]'
              and items[0]['declared_bytes'] == '46695', items[0])
        check('清单不内嵌 URL（只记主机），避免临时链接长期进上下文',
              'url' not in items[0] and items[0]['url_host'] == 'multimedia.nt.qq.com.cn', items[0])
        check('ref 可重算（同一消息同一段不变）', vision.ref_of(MEDIA_MESSAGE['_id'], 0) == ref)
        # 1b. adapter 现在真实发的形状：没有 version/truncated，sub_type 是字符串，summary 有值
        now = json.loads(json.dumps(MEDIA_MESSAGE))
        live = now['event']['raw']['asuna_media']
        live.pop('version'), live.pop('truncated')
        live['items'][0].update({'sub_type': '1', 'summary': '[动画表情]',
                                 'url': 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid='
                                        + 'EhS9' * 22 + '&rkey=' + 'CAESMI' * 16})
        live_items = vision.attachments_of(now, config=config())
        check('线上真实形状（无 version、sub_type 为字符串、长 URL）照样出可拉清单',
              len(live_items) == 1 and live_items[0]['pullable'] is True
              and live_items[0]['ref'] == vision.ref_of(now['_id'], 0)
              and live_items[0]['url_host'] == 'multimedia.nt.qq.com.cn', live_items)

        note = vision.media_note(MEDIA_MESSAGE, config())
        check('角色现场只给媒体事实：语音段以占位符事实保留', note['can_pull'] is True
              and note['other_media_placeholders'] == ['[语音（未解析）]'], note.get('other_media_placeholders'))

        # 2. 能力门与 allowed_capabilities 裁剪
        off = vision.vision_capability(config(modalities=('text',), hosts=()))
        check('路由未声明 image 且白名单为空 → 不支持，并给出两条原因',
              off['supported'] is False and len(off['unsupported_because']) == 2, off['unsupported_because'])
        check('能力不足时 read_image 不进任务能力清单',
              vision.route_filtered_tool_names([{'name': 'read_image'}, {'name': 'web_search'}],
                                               config(modalities=('text',))) == ['web_search'])
        check('能力齐备时 read_image 进能力清单',
              vision.route_filtered_tool_names([{'name': 'read_image'}], config()) == ['read_image'])
        blocked = vision.attachments_of(MEDIA_MESSAGE, config=config(modalities=('text',)))[0]
        check('路由不收图时清单直接标不可拉并说明原因',
              blocked['pullable'] is False and 'route_declares_image_input' in blocked['not_pullable_because'],
              blocked)
        elsewhere = vision.attachments_of(MEDIA_MESSAGE, config=config(hosts=('example.com',)))[0]
        check('白名单外主机 → 清单标不可拉并说明 host_not_allowed',
              elsewhere['pullable'] is False and 'host_not_allowed' in elsewhere['not_pullable_because'],
              elsewhere)

        # 3. 真拉取全链路
        store = store_with(f'{base}/png')
        blobs = FakeBlobs()
        result = vision.read_image_for_task(store, blobs, TASK, config(), {'ref': ref})
        check('真拉取：魔数判定 png 且字节数一致',
              result['media_type'] == 'image/png' and result['bytes'] == len(PNG),
              {key: result[key] for key in ('media_type', 'bytes')})
        check('真拉取：sha256 对得上原字节', result['sha256'] == hashlib.sha256(PNG).hexdigest())
        check('真拉取：base64 解回来就是原字节', base64.b64decode(result['image']['data']) == PNG)
        check('真拉取：字节进了既有 BlobStore（scope/kind/来源消息）',
              blobs.saved and blobs.saved[0]['bytes'] == PNG and blobs.saved[0]['scope'] == TASK['scope_key']
              and blobs.saved[0]['kind'] == 'image'
              and blobs.saved[0]['source_ids'] == [MEDIA_MESSAGE['_id']], blobs.saved)
        check('真拉取：来源主机如实记录', result['source']['host'] == '127.0.0.1', result['source'])
        check('真拉取：视觉输入状态先标 awaiting（最终由插件的附件保存结果决定）',
              result['visual'] == 'awaiting_attachment')
        # 3b. 真实 QQ 下载 URL 很长（长 fileid + rkey）：不能被截成坏链接，URL 也不进清单
        long_url = f'{base}/png?appid=1407&fileid=' + 'EhS9' * 60 + '&rkey=' + 'CAQSMB' * 40
        deep_store = store_with(long_url)
        deep = vision.read_image_for_task(deep_store, blobs, TASK, config(), {'ref': ref})
        entry = vision.attachments_of(MEDIA_MESSAGE, config=config())[0]
        check('长下载 URL 不被截断：仍能拉到那张图，回读 URL 与原值一致',
              len(long_url) > 420 and deep['media_type'] == 'image/png'
              and vision.media_source_url(deep_store, TASK, config(), entry) == long_url,
              (len(long_url), len(vision.media_source_url(deep_store, TASK, config(), entry))))

        # 4. 回执有界
        receipt = vision.inline_summary(result)
        receipt_text = json.dumps(receipt, ensure_ascii=False)
        check('回执不带 base64 且体积有界', PNG_B64 not in receipt_text and 'image' not in receipt
              and len(receipt_text) < 4096 and receipt['inline_image']['base64_chars'] == len(PNG_B64),
              len(receipt_text))

        # 5. 错误面
        def expect(name, call, code, errors=(ValueError,)):
            try:
                call()
            except errors as exc:
                check(name, code in str(exc), str(exc))
            except Exception as exc:  # noqa: BLE001
                check(name, False, f'{type(exc).__name__}: {exc}')
            else:
                check(name, False, '没有报错')

        expect('字节超上限 → IMAGE_TOO_LARGE',
               lambda: vision.read_image_for_task(store_with(f'{base}/big'), blobs, TASK, config(max_bytes=1024), {'ref': ref}),
               'IMAGE_TOO_LARGE')
        expect('非图片响应 → IMAGE_TYPE_UNSUPPORTED',
               lambda: vision.read_image_for_task(store_with(f'{base}/html'), blobs, TASK, config(), {'ref': ref}),
               'IMAGE_TYPE_UNSUPPORTED')
        expect('404 → IMAGE_FETCH_FAILED:HTTP_404',
               lambda: vision.read_image_for_task(store_with(f'{base}/missing'), blobs, TASK, config(), {'ref': ref}),
               'IMAGE_FETCH_FAILED:HTTP_404')
        try:
            vision.read_image_for_task(store_with(f'{base}/expired'), blobs, TASK, config(), {'ref': ref})
        except ValueError as exc:
            check('链接过期 → IMAGE_FETCH_FAILED:HTTP_400 带服务端原因（不泄露 rkey）',
                  str(exc).startswith('IMAGE_FETCH_FAILED:HTTP_400')
                  and 'download url has expired' in str(exc) and 'CAESMGoieAXqbqKk' not in str(exc), str(exc))
        else:
            check('链接过期 → IMAGE_FETCH_FAILED:HTTP_400 带服务端原因', False, '没有报错')
        expect('重定向跳出白名单 → IMAGE_REDIRECT_HOST_DENIED',
               lambda: vision.read_image_for_task(store_with(f'{base}/redirect-out'), blobs, TASK, config(), {'ref': ref}),
               'IMAGE_REDIRECT_HOST_DENIED')
        expect('明文 http 未放行 → IMAGE_INSECURE_URL_DENIED',
               lambda: vision.pull_bytes({'pull_via': 'url', 'url': f'{base}/png'},
                                         config(hosts=('127.0.0.1',), insecure=False)),
               'IMAGE_INSECURE_URL_DENIED')
        check('明文 http 显式放行后本机真拉到字节',
              vision.pull_bytes({'pull_via': 'url', 'url': f'{base}/png'},
                                config(hosts=('127.0.0.1',), insecure=True))[0] == PNG)
        expect('未知 ref → IMAGE_ATTACHMENT_NOT_IN_SCENE',
               lambda: vision.read_image_for_task(store, blobs, TASK, config(), {'ref': 'att-000000000000'}),
               'IMAGE_ATTACHMENT_NOT_IN_SCENE')
        expect('场景围栏不符 → Denied(VISION_SCENE_FENCE_MISMATCH)',
               lambda: vision.read_image_for_task(store_with(f'{base}/png', scene_ok=False), blobs, TASK, config(),
                                                  {'ref': ref}),
               'VISION_SCENE_FENCE_MISMATCH', errors=(vision.Denied,))
        expect('路由不支持图片 → VISION_ROUTE_UNSUPPORTED',
               lambda: vision.read_image_for_task(store, blobs, TASK, config(modalities=('text',)), {'ref': ref}),
               'VISION_ROUTE_UNSUPPORTED')
        expect('多余参数 → READ_IMAGE_ARGUMENT_DENIED',
               lambda: vision.read_image_for_task(store, blobs, TASK, config(),
                                                  {'ref': ref, 'scene_id': '别的场景'}),
               'READ_IMAGE_ARGUMENT_DENIED')
        expect('非法 ref → INVALID_READ_IMAGE_REF',
               lambda: vision.read_image_for_task(store, blobs, TASK, config(), {'ref': 'x'}),
               'INVALID_READ_IMAGE_REF')

        # 5b. A2 只读联动：本场景之外那条边指向的场景里的图，也能按同一道围栏拉
        LINKED = 'qq:3768713357:dm:673225019'
        own_doc = {'_id': TASK['scene_id'], 'scope_key': TASK['scope_key'],
                   'policy_epoch': TASK['policy_epoch']}
        linked_doc = {'_id': LINKED, 'scope_key': 'scene:' + LINKED, 'policy_epoch': TASK['policy_epoch']}
        linked_message = json.loads(json.dumps(MEDIA_MESSAGE))
        linked_message['_id'] = 'in-ep-245d91c91ae4294a9addd1fb644d67e9'
        linked_message['scene_id'] = LINKED
        linked_message['scene_seq'] = 34
        linked_message['occurred_at'] = '2026-09-25T13:13:40Z'
        linked_message['event']['raw']['asuna_media']['items'] = [
            dict(linked_message['event']['raw']['asuna_media']['items'][0],
                 sub_type='0', url=f'{base}/png?fileid=linked&rkey=CAESMI')]
        linked_ref = vision.ref_of(linked_message['_id'], 0)

        def linked_config(links=True, *, linked_doc_ok=True, epoch='same'):
            cfg = config()
            if links:
                cfg['context_links'] = {TASK['scene_id']: [LINKED]}
            doc = dict(linked_doc)
            if epoch == 'other':
                doc['policy_epoch'] = 'epoch-other'
            scenes = [own_doc] + ([doc] if linked_doc_ok else [])
            rows = [MEDIA_MESSAGE, linked_message]
            return FakeStore(scenes, rows), cfg

        both_store, both_cfg = linked_config()
        listing = vision.scene_attachments(both_store, TASK, both_cfg, limit=8, scan=50)
        by_ref = {item['ref']: item for item in listing['attachments']}
        check('只读联动场景的图进清单，并写明它来自哪个场景',
              linked_ref in by_ref and by_ref[linked_ref]['scene_id'] == LINKED
              and by_ref[linked_ref]['linked_scene'] is True
              and by_ref[linked_ref]['pullable'] is True
              and by_ref[ref]['linked_scene'] is False, listing['scanned_scenes'])
        check('清单如实报出扫了哪些场景（联动那条边写在 linked_scenes 里）',
              {s['scene_id'] for s in listing['scanned_scenes']} == {TASK['scene_id'], LINKED}
              and listing['linked_scenes'] == [LINKED], listing['scanned_scenes'])
        pulled = vision.read_image_for_task(both_store, blobs, TASK, both_cfg, {'ref': linked_ref})
        check('联动场景那张图真拉到了：魔数与字节一致，并标明来自联动场景',
              pulled['media_type'] == 'image/png' and pulled['bytes'] == len(PNG)
              and pulled['image_scene_id'] == LINKED and pulled['linked_scene'] is True
              and 'scene_note' in pulled,
              {key: pulled[key] for key in ('media_type', 'bytes', 'image_scene_id', 'linked_scene')})
        check('联动场景的字节仍按本任务 scope 落盘（不写进别人场景的账本）',
              blobs.saved[-1]['scope'] == TASK['scope_key']
              and blobs.saved[-1]['source_ids'] == [linked_message['_id']], blobs.saved[-1])
        check('联动条目的下载 URL 按它自己的场景回读（不串场景、不被截断）',
              vision.media_source_url(both_store, TASK, both_cfg, by_ref[linked_ref])
              == f'{base}/png?fileid=linked&rkey=CAESMI')
        block_linked = vision.task_attachment_context(both_store, TASK, both_cfg, None)
        check('行动输入的清单也带来源场景与联动标记（她看得见这条来自哪）',
              bool(block_linked) and block_linked['linked_scenes'] == [LINKED]
              and any(item['ref'] == linked_ref and item['linked_scene'] is True
                      for item in block_linked['attachments']), list(block_linked or {}))
        expect('删掉配置里那条边 → 回到只扫本场景（IMAGE_ATTACHMENT_NOT_IN_SCENE）',
               lambda: vision.read_image_for_task(both_store, blobs, TASK, config(), {'ref': linked_ref}),
               'IMAGE_ATTACHMENT_NOT_IN_SCENE')
        expect('联动场景纪元与本任务不同步 → 照实不扫它',
               lambda: vision.read_image_for_task(linked_config(epoch='other')[0], blobs, TASK, both_cfg,
                                                  {'ref': linked_ref}),
               'IMAGE_ATTACHMENT_NOT_IN_SCENE')
        expect('配置写了边但库里没那个场景 → 不猜，清单里没有它',
               lambda: vision.read_image_for_task(linked_config(linked_doc_ok=False)[0], blobs, TASK, both_cfg,
                                                  {'ref': linked_ref}),
               'IMAGE_ATTACHMENT_NOT_IN_SCENE')

        # 6. 本机文件目录路径
        image_dir = work / 'napcat'
        image_dir.mkdir()
        (image_dir / '2411cf00a42d592c44188041c19e1d29.png').write_bytes(PNG)
        local_entry = vision.attachments_of(MEDIA_MESSAGE, config=config(hosts=(), image_dirs=(image_dir,)))[0]
        check('无可用 URL 但配了本机目录 → 走 local_file',
              local_entry['pullable'] is True and local_entry['pull_via'] == 'local_file', local_entry)
        check('本机文件真读到同样字节',
              vision.pull_bytes(dict(local_entry, file='2411cf00a42d592c44188041c19e1d29.png'),
                                config(hosts=(), image_dirs=(image_dir,)))[0] == PNG)
        expect('目录穿越被拒 → IMAGE_FILE_NAME_DENIED',
               lambda: vision.pull_bytes({'pull_via': 'local_file', 'file': '../secrets.txt'},
                                         config(hosts=(), image_dirs=(image_dir,))),
               'IMAGE_FILE_NAME_DENIED')

        # 7. 行动输入里的附件段
        block = vision.task_attachment_context(store, TASK, config(), MEDIA_MESSAGE)
        check('行动输入只带清单与路由说明，不带图片正文',
              block and 'base64' not in json.dumps(block, ensure_ascii=False)
              and block['attachments'][0]['ref'] == ref and 'read_image' in block['route'],
              list(block or {}))
        limited = vision.task_attachment_context(store, TASK, config(modalities=('text',)), MEDIA_MESSAGE)
        check('能力未开时行动输入说明原因', bool(limited['unsupported_because']), limited['unsupported_because'])

        # 8. TokenMeter：内联图片不算文本字节
        body = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': '你好'},
                                                         {'type': 'image_url',
                                                          'image_url': {'url': 'data:image/png;base64,' + PNG_B64}}]}]}
        meter = token_module.TokenMeter(config(), None, None)
        with_image = meter.measure(body)
        plain = meter.measure({'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': '你好'}]}]})
        raw_bytes = len(json.dumps(body, ensure_ascii=False, sort_keys=True).encode())
        check('内联图片不被当成文本字节计入保守上界（只留一个标记）',
              with_image['input_tokens'] - plain['input_tokens'] < 80 and with_image['input_tokens'] < raw_bytes,
              (with_image['input_tokens'], plain['input_tokens'], raw_bytes))
        check('内联图片份数与字节如实报出', with_image['inline_images'] == 1
              and with_image['inline_image_bytes'] == len(PNG), with_image)

        # 9. 插件投影：装载真 tools.ts（只替换那一行包导入）
        node = shutil.which('node')
        if not node:
            check('插件投影（node 可用）', False, '沙箱里没有 node')
        else:
            source = (ROOT / 'dsh-plugin' / 'tools.ts').read_text(encoding='utf-8')
            anchor = "import { defineTool } from '@deepseek-ai/dsh-tools';"
            check('tools.ts 仍只依赖那一行包导入（可被自检装载）', source.count(anchor) == 1)
            (work / 'tools.mjs').write_text(source.replace(anchor, 'const defineTool = (definition) => definition;'),
                                            encoding='utf-8')
            driver = work / 'driver.mjs'
            driver.write_text(f'''
import assert from 'node:assert/strict';
import {{ asunaRender, attachImage, imageBlock, inject }} from '{(work / 'tools.mjs').as_posix()}';
// DSH 运行时只放行 inject 里声明过的 ctx 服务：少声明一条，真宿主上每一次 read_image 都会如实抛
// `cannot get property "attachments" without inject`（2026-09-25 实测：字节拉回来了，图没进模型）。
// 本自检用假 ctx 装载插件，照不出这道运行时闸门，所以直接断言声明本身。
assert.ok(Array.isArray(inject) && inject.includes('tools') && inject.includes('attachments'),
  'tools.ts 的 inject 必须同时声明 tools 与 attachments，实际：' + JSON.stringify(inject));
const png = Buffer.from('{PNG_B64}', 'base64');
const value = {{ ref: 'att-test', media_type: 'image/png', bytes: png.length, sha256: 'x',
  image: {{ media_type: 'image/png', data: png.toString('base64') }}, visual: 'awaiting_attachment' }};
const saved = [];
const ctx = {{ attachments: {{ saveImage: async (input) => {{ saved.push(input);
  return {{ attachmentId: 'sha256:' + 'a'.repeat(64), mediaType: input.mediaType, bytes: input.data.byteLength, width: 8, height: 6 }}; }} }} }};
const attached = await attachImage(ctx, value);
assert.equal(attached.visual, 'attached');
assert.equal(attached.image.attachmentId, 'sha256:' + 'a'.repeat(64));
assert.equal(attached.image.bytes, png.length);
assert.equal(Buffer.compare(Buffer.from(saved[0].data), png), 0);
assert.equal(saved[0].mediaType, 'image/png');
assert.equal(saved[0].name, 'att-test');
assert.ok(!('data' in attached.image));
const blocks = asunaRender(null, attached);
assert.equal(blocks.length, 2);
assert.equal(blocks[0].type, 'image');
assert.equal(blocks[0].attachment.attachmentId, attached.image.attachmentId);
assert.equal(blocks[1].type, 'text');
assert.ok(!blocks[1].text.includes('{PNG_B64}'));
assert.ok(blocks[1].text.includes('attached'));
assert.deepEqual(imageBlock(attached), {{ type: 'image', attachment: attached.image }});
const plain = asunaRender(null, {{ ok: true, facts: [] }});
assert.equal(plain.length, 1);
assert.equal(plain[0].type, 'text');
const missing = await attachImage({{}}, value);
assert.equal(missing.visual, 'unavailable:ATTACHMENT_SERVICE_MISSING');
assert.equal(asunaRender(null, missing).length, 1);
const failing = await attachImage({{ attachments: {{ saveImage: async () => {{
  throw Object.assign(new Error('boom'), {{ code: 'IMAGE_ADMISSION_TOO_LARGE' }}); }} }} }}, value);
assert.equal(failing.visual, 'unavailable:IMAGE_ADMISSION_TOO_LARGE');
console.log(JSON.stringify({{ ok: true, inject: inject, visual: attached.visual, blocks: blocks.map(b => b.type),
  text_bytes: blocks[1].text.length, missing: missing.visual, failing: failing.visual }}));
''', encoding='utf-8')
            proc = subprocess.run([node, driver.as_posix()], capture_output=True, text=True, timeout=60)
            ok = proc.returncode == 0 and proc.stdout.strip().startswith('{')
            check('插件投影：saveImage 收到原字节并产出 ImageBlock + 元数据文本块', ok,
                  (proc.stdout or proc.stderr).strip()[:300])
            if ok:
                NOTES.append('node 投影读数：' + proc.stdout.strip())
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)

    for note in NOTES:
        print('NOTE ' + note)
    print('看图自检：' + ('全部通过' if not FAILURES else f'{len(FAILURES)} 项失败：' + '; '.join(FAILURES)))
    return 0 if not FAILURES else 1


if __name__ == '__main__':
    sys.exit(main())
