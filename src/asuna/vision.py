"""入站图片元数据与行动脑 DSH ``read_image`` 接线。

角色现场仅可获得消息附件的有界元数据和诚实占位符。行动脑按需通过
``read_image`` 拉取当前授权场景的图片；能力来自行动模型路由配置，图片字节
经白名单与大小检查后复用现有 BlobStore 和 DSH durable attachment seam。

读图范围与 A2 跨场景只读联动同一口径：本场景之外，还扫配置里那条有向边指向的场景
（``context_links`` / 路由级 ``read_scenes``，现算自配置，不是工具参数）。放宽的只有**读**——
字节仍按本任务的 scope_key 落盘，写、出站、场景成员资格都不因此放宽；删掉配置键就回到只扫本场景。
"""
from __future__ import annotations
import base64
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .evidence import canonical, sha
from .scene_links import message_times, read_scope
from .state import Denied

MEDIA_KEY = 'asuna_media'
READ_IMAGE_TOOL_NAME = 'read_image'
# DSH v1 附件路径接受的栅格格式；其余类型直接拒收，不假装能送进视觉输入。
IMAGE_MEDIA_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
# 默认就等于硬上限：QQ 照片常有 4–6 MiB，而 DSH 会把请求内图片重编到 1 MiB 目标再发，
# 在拉取这一步拦下 5 MiB 的照片只是我们自己加的围栏，不是路由的能力边界。
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
HARD_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15
MAX_ITEMS_PER_MESSAGE = 8
SCENE_SCAN_MESSAGES = 50
# QQ 的下载 URL 带长 fileid 与 rkey，截断就是静默把链接改坏（拉回来必然是错的或 404）。
# 清单里不内嵌 URL，只在拉取时按原消息回读，所以这里给足长度。
URL_LIMIT = 2048
# 默认只放行这套部署里真出现过的 QQ 多媒体主机（依据是库里存的入站元数据，不是猜的 CDN 名单）。
# 换了 CDN 时清单会带着 host_not_allowed(具体主机) 说明原因，加一行 vision.image_hosts 即可，
# 不静默放宽；显式写 vision.image_hosts: [] 表示谁都不放行。
DEFAULT_IMAGE_HOSTS = ('multimedia.nt.qq.com.cn',)
USER_AGENT = 'asuna-host/1.0 read-image'


def _error_detail(body):
    """非 2xx 时那一小段服务端说明是有用的（例如 QQ 的“下载链接已过期”）。
    只留有界一行，并把临时凭据隐掉。"""
    text = _clean(body.decode('utf-8', 'ignore'), 160)
    return re.sub(r'(rkey"?\s*[:=]\s*"?)[^&\s"]*', r'\1[已隐藏]', text)


def _clean(value, limit):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ''
    return ' '.join(str(value).split())[:limit]


def ref_of(message_id, index):
    """附件的稳定引用：同一场景同一条消息同一段图片，重算不变，也不暴露平台 ID。"""
    return 'att-' + sha(canonical([str(message_id), int(index)]))[:12]


def media_block(message):
    """adapter 注入的规范化媒体块；没有就 None。宿主不解析 OneBot raw，只认这个命名空间。"""
    raw = (message or {}).get('event', {}).get('raw')
    if not isinstance(raw, dict):
        return None
    block = raw.get(MEDIA_KEY)
    return block if isinstance(block, dict) else None


def host_allowed(host, allow_hosts):
    """白名单：精确主机名，或以点开头的条目允许其子域。大小写不敏感。"""
    if not host:
        return False
    host = host.lower()
    for entry in allow_hosts or []:
        entry = str(entry).strip().lower()
        if not entry:
            continue
        if entry.startswith('.'):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def sniff_media_type(data):
    """只认魔数。声明的 content-type 只作为附带信息，不作为依据。"""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return 'image/gif'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def vision_capability(config):
    """这条模型路由现在到底能不能收图：只看配置声明，不看模型名字。"""
    route = (config or {}).get('executor', {})
    vision = (config or {}).get('vision', {})
    modalities = [str(m).lower() for m in (route.get('input_modalities') or [])]
    configured = vision.get('image_hosts')
    hosts = [str(h) for h in (list(DEFAULT_IMAGE_HOSTS) if configured is None else configured)]
    reasons = []
    if 'image' not in modalities:
        reasons.append('route_declares_image_input=false（config.executor.input_modalities 未声明 image）')
    if not hosts:
        reasons.append('image_hosts_allowlist_empty（vision.image_hosts 被显式清空，任何图片 URL 都会被拒）')
    return {'supported': not reasons, 'input_modalities': modalities, 'image_hosts': hosts,
            'max_bytes': int(vision.get('max_bytes', DEFAULT_MAX_BYTES)),
            'timeout_seconds': float(vision.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)),
            'image_dirs': [str(d) for d in (vision.get('image_dirs') or [])],
            'source': 'config.executor.input_modalities + config.vision',
            'unsupported_because': reasons}


def attachments_of(message, *, config=None, limit=MAX_ITEMS_PER_MESSAGE):
    """一条消息 → 有界附件清单（只列图片；其它类型只保留占位符事实）。"""
    block = media_block(message)
    if not block:
        return []
    vision = vision_capability(config or {})
    out = []
    for index, item in enumerate(block.get('items') or []):
        if not isinstance(item, dict) or item.get('type') != 'image':
            continue
        if len(out) >= limit:
            break
        message_id = (message or {}).get('_id') or (message or {}).get('event', {}).get('event_id') or 'message'
        url = _clean(item.get('url'), URL_LIMIT)
        name = _clean(item.get('file'), 120)
        parsed = urlsplit(url) if url else None
        host = (parsed.hostname or '') if parsed else ''
        entry = {'ref': ref_of(message_id, index), 'type': 'image',
                 'placeholder': _clean(item.get('placeholder'), 120),
                 'source_message_id': message_id,
                 'declared_bytes': _clean(item.get('size'), 16),
                 'summary': _clean(item.get('summary'), 80)}
        if name:
            entry['file'] = name
        if url:
            entry['url_host'] = host
        reason = None
        scheme_ok = bool(parsed and parsed.scheme in ('https', 'http') and not parsed.username and not parsed.password)
        local_ok = bool(name and vision['image_dirs'] and '/' not in name and '\\' not in name)
        if 'image' not in vision['input_modalities']:
            # 路由本身不收图：清单里就标不可拉，别让她以为拉了能看到东西。
            reason = 'route_declares_image_input=false（当前模型路由不收图片）'
        elif not url and not local_ok:
            reason = 'no_source（元数据里没有 URL，也没有可用的本机文件目录配置）'
        elif url and not scheme_ok:
            reason = f'url_scheme_denied（scheme={parsed.scheme or '空'}）'
        elif url and not host_allowed(host, vision['image_hosts']) and not local_ok:
            reason = f'host_not_allowed（{host or '未知主机'} 不在 vision.image_hosts 白名单）'
        entry['pullable'] = reason is None
        entry['pull_via'] = ('url' if scheme_ok and host_allowed(host, vision['image_hosts'])
                             else ('local_file' if local_ok else None))
        if reason:
            entry['not_pullable_because'] = reason
        out.append(entry)
    return out


def readable_image_scenes(store, task, config):
    """本任务能读图的范围：本场景（围栏照旧）+ 配置声明的只读联动场景（A2 同一口径）。

    联动集合现算自配置（``scene_links.read_scope``），不是工具参数：她既不能把范围换宽，
    也不能把别人的场景说成自己的。本场景与任务记录不同步仍然拒（不猜）；联动场景在库里
    查不到、或纪元与本任务不同步，就照实不扫它——那条边本来只是「额外能读」，缺了不算围栏不对。
    """
    scene = store.db.scenes.find_one({'_id': task['scene_id']})
    if (not isinstance(scene, dict) or scene.get('scope_key') != task['scope_key']
            or scene.get('policy_epoch') != task['policy_epoch']):
        raise Denied('VISION_SCENE_FENCE_MISMATCH')
    out = [{'scene_id': scene.get('_id'), 'linked': False}]
    for scene_id in read_scope(config, scene)['linked_scenes']:
        doc = store.db.scenes.find_one({'_id': scene_id})
        if not isinstance(doc, dict) or doc.get('policy_epoch') != task['policy_epoch']:
            continue
        out.append({'scene_id': scene_id, 'linked': True})
    return out


def scene_attachments(store, task, config, *, limit=MAX_ITEMS_PER_MESSAGE, scan=SCENE_SCAN_MESSAGES):
    """本场景（外加按配置只读联动的场景）最近的入站图片。范围由任务绑定，参数换不了它。"""
    scenes = readable_image_scenes(store, task, config)
    rows, scanned = [], []
    for scope in scenes:
        found = list(store.db.messages.find({'scene_id': scope['scene_id'],
                                             'policy_epoch': task['policy_epoch'],
                                             'direction': 'inbound'},
                                            {'_id': 1, 'scene_id': 1, 'scene_seq': 1, 'direction': 1,
                                             'text': 1, 'event.raw': 1, 'occurred_at': 1, 'received_at': 1})
                     .sort('scene_seq', -1).limit(scan))
        scanned.append({'scene_id': scope['scene_id'], 'linked': scope['linked'], 'messages': len(found)})
        for row in found:
            row['_linked_scene'] = bool(scope['linked'])
            rows.append(row)
    # 各场景的 scene_seq 互不可比：跨场景归并用与 history_query 同一口径的有效时间。
    times = message_times(store, rows)
    rows.sort(key=lambda row: (times.get(row.get('_id'), ('', ''))[0], row.get('scene_seq') or 0))
    items = []
    for row in rows:
        linked = bool(row.pop('_linked_scene', False))
        for entry in attachments_of(row, config=config):
            entry['scene_seq'] = row.get('scene_seq')
            entry['scene_id'] = row.get('scene_id')
            entry['linked_scene'] = linked
            items.append(entry)
    truncated = len(items) > limit
    return {'scene_id': scene_id_of(task), 'attachments': items[-limit:], 'truncated': truncated,
            'scanned_messages': len(rows), 'scanned_scenes': scanned,
            'linked_scenes': [scope['scene_id'] for scope in scenes if scope['linked']],
            'vision': vision_capability(config)}


def scene_id_of(task):
    return _clean((task or {}).get('scene_id'), 90)


class _RedirectDenied(Exception):
    """重定向跳出白名单：允许列表里的站点不能把我们带进内网任意端口。"""


class _KeepInsideAllowList(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_hosts):
        super().__init__()
        self.allow_hosts = allow_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urlsplit(newurl).hostname or '').lower()
        if not host_allowed(host, self.allow_hosts):
            raise _RedirectDenied(host or '未知主机')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def pull_bytes(entry, config, *, max_bytes=None):
    """按元数据把图片字节拉回来。返回 (bytes, media_type, via, source)。失败一律抛真实错误码。

    只用标准库：这条路径要能在没有第三方 HTTP 库的离线自检里真跑一次真实 socket，
    不能只对着替身断言。
    """
    vision = vision_capability(config)
    cap = min(int(max_bytes or vision['max_bytes']), HARD_MAX_BYTES)
    if entry.get('pull_via') == 'url':
        url = _clean(entry.get('url'), URL_LIMIT)
        if not url:
            raise ValueError('IMAGE_URL_MISSING')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' and not config.get('vision', {}).get('allow_insecure_http'):
            raise ValueError('IMAGE_INSECURE_URL_DENIED')
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        opener = urllib.request.build_opener(_KeepInsideAllowList(vision['image_hosts']))
        try:
            with opener.open(request, timeout=vision['timeout_seconds']) as response:
                status = getattr(response, 'status', None) or 200
                if status != 200:
                    raise ValueError(f'IMAGE_FETCH_FAILED:HTTP_{status}')
                final_host = (urlsplit(response.geturl()).hostname or '').lower()
                content_type = response.headers.get('content-type', '') or ''
                chunks = []
                total = 0
                while True:
                    part = response.read(65536)
                    if not part:
                        break
                    total += len(part)
                    if total > cap:
                        raise ValueError(f'IMAGE_TOO_LARGE:>{cap}')
                    chunks.append(part)
                data = b''.join(chunks)
        except _RedirectDenied as exc:
            raise ValueError(f'IMAGE_REDIRECT_HOST_DENIED:{exc}') from exc
        except urllib.error.HTTPError as exc:
            try:
                detail = _error_detail(exc.read(512) or b'')
            except Exception:  # noqa: BLE001 读不到原因也要报状态码
                detail = ''
            raise ValueError(f'IMAGE_FETCH_FAILED:HTTP_{exc.code}' + (f':{detail}' if detail else '')) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ValueError(f'IMAGE_FETCH_FAILED:{type(exc).__name__}') from exc
        if not host_allowed(final_host, vision['image_hosts']):
            raise ValueError(f'IMAGE_REDIRECT_HOST_DENIED:{final_host or '未知主机'}')
    elif entry.get('pull_via') == 'local_file':
        name = _clean(entry.get('file'), 120)
        if not name or '/' in name or '\\' in name:
            raise ValueError('IMAGE_FILE_NAME_DENIED')
        data = None
        for directory in vision['image_dirs']:
            base = Path(directory)
            candidate = (base / name)
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(base.resolve()) or not resolved.is_file():
                continue
            if resolved.stat().st_size > cap:
                raise ValueError(f'IMAGE_TOO_LARGE:>{cap}')
            data = resolved.read_bytes()
            break
        if data is None:
            raise ValueError('IMAGE_FILE_NOT_AVAILABLE')
        content_type = ''
        final_host = ''
    else:
        raise ValueError('IMAGE_SOURCE_UNAVAILABLE')
    media_type = sniff_media_type(data)
    if media_type is None:
        raise ValueError('IMAGE_TYPE_UNSUPPORTED:只支持 png/jpeg/webp/gif（按魔数判定）')
    if not data:
        raise ValueError('IMAGE_EMPTY')
    return data, media_type, entry.get('pull_via'), {'host': final_host, 'content_type': _clean(content_type, 80)}


def read_image_for_task(store, blobs, task, config, args):
    """read_image 的实际执行：场景围栏 → 能力核对 → 拉字节 → 落 BlobStore → 交给插件的视觉输入载荷。"""
    args = args if isinstance(args, dict) else {}
    unknown = set(args) - {'ref', 'max_bytes'}
    if unknown:
        raise ValueError('READ_IMAGE_ARGUMENT_DENIED:' + ','.join(sorted(unknown)))
    ref = args.get('ref')
    if not isinstance(ref, str) or not 4 <= len(ref) <= 80:
        raise ValueError('INVALID_READ_IMAGE_REF')
    max_bytes = args.get('max_bytes')
    if max_bytes is not None and (not isinstance(max_bytes, int) or isinstance(max_bytes, bool)
                                  or not 1024 <= max_bytes <= HARD_MAX_BYTES):
        raise ValueError('INVALID_READ_IMAGE_MAX_BYTES')
    capability = vision_capability(config)
    if not capability['supported']:
        raise ValueError('VISION_ROUTE_UNSUPPORTED:' + ';'.join(capability['unsupported_because']))
    listing = scene_attachments(store, task, config, limit=MAX_ITEMS_PER_MESSAGE, scan=SCENE_SCAN_MESSAGES)
    entry = next((item for item in listing['attachments'] if item['ref'] == ref), None)
    if not entry:
        # 不区分「不存在」与「在围栏外的场景／别的纪元」：不借这个工具探测别人的图。
        raise ValueError('IMAGE_ATTACHMENT_NOT_IN_SCENE')
    if not entry.get('pullable'):
        raise ValueError('IMAGE_NOT_PULLABLE:' + str(entry.get('not_pullable_because') or ''))
    full = dict(entry)
    full['url'] = (media_source_url(store, task, config, entry))
    data, media_type, via, source = pull_bytes(full, config, max_bytes=max_bytes)
    digest = sha(data)
    # 字节按**本任务**的 scope 落盘：图来自联动场景也不会写进别人场景的账本。
    blob = blobs.put(data, task['scope_key'], 'image', source_ids=[entry['source_message_id']]) if blobs else None
    payload = {'ref': ref, 'scene_id': task['scene_id'],
               'image_scene_id': _clean(entry.get('scene_id'), 90) or task['scene_id'],
               'linked_scene': bool(entry.get('linked_scene')),
               'source_message_id': entry['source_message_id'],
               'placeholder': entry.get('placeholder'), 'summary': entry.get('summary') or None,
               'media_type': media_type, 'bytes': len(data), 'sha256': digest, 'pulled_via': via,
               'source': source, 'blob_artifact': (blob or {}).get('artifact_id'),
               'blob_sha256': (blob or {}).get('sha256'),
               'image': {'media_type': media_type, 'data': base64.b64encode(data).decode()},
               'visual': 'awaiting_attachment',
               'note': '图片字节已按本次调用真实拉取；此前正文里的占位符只说明这里出现过一张图，不代表内容已被读过。'}
    if payload['linked_scene']:
        payload['scene_note'] = ('这张图来自本场景按配置只读联动的另一个场景（同一个人在那边的入口）。'
                                 '放宽的只有读：字节按本任务的 scope 存，写与出站不因此放宽。')
    return payload


def media_source_url(store, task, config, entry):
    """URL 不进清单（避免把带 rkey 的临时链接长期抄进上下文），拉取时按原消息回读。

    回读走与清单同一道围栏：条目写着哪个场景就回那个场景读，不在本任务可读集合里就返回空。
    """
    scene_id = _clean(entry.get('scene_id'), 90) or task['scene_id']
    if scene_id not in {scope['scene_id'] for scope in readable_image_scenes(store, task, config)}:
        return ''
    row = store.db.messages.find_one({'_id': entry['source_message_id'], 'scene_id': scene_id,
                                      'policy_epoch': task['policy_epoch']})
    block = media_block(row)
    if not block:
        return ''
    wanted = entry['ref']
    for index, item in enumerate(block.get('items') or []):
        if ref_of(row['_id'], index) == wanted and isinstance(item, dict):
            return _clean(item.get('url'), URL_LIMIT)
    return ''


def task_attachment_context(store, task, config, source_message):
    """行动任务输入里的附件段：让她知道有什么可拉、ref 是什么、没拉过就是没看过。"""
    capability = vision_capability(config)
    current = attachments_of(source_message, config=config) if source_message else []
    for entry in current:
        # 当前这条消息按定义就在本任务自己的场景里。
        entry['scene_id'] = task['scene_id']
        entry['linked_scene'] = False
    scene = scene_attachments(store, task, config) if capability['supported'] else {'attachments': []}
    items = current or scene['attachments']
    if not items:
        return None
    return {'attachments': items, 'scene_attachments': scene['attachments'], 'vision': capability,
            'linked_scenes': scene.get('linked_scenes') or None,
            'scanned_scenes': scene.get('scanned_scenes') or None,
            'route': ('用 read_image(ref) 按需拉取；成功返回的 image 才是本次真实看到的视觉输入。'
                      '未调用的附件正文没有被读过，不要说看过。linked_scene=true 的那条来自按配置'
                      '只读联动的场景（同一个人在另一个入口发的），拉取与落盘仍按本任务的围栏与 scope。'),
            'unsupported_because': capability['unsupported_because']}


def media_note(message, config):
    """给角色现场的附件元数据：不把图片字节放进上下文。"""
    block = media_block(message)
    if not block:
        return None
    capability = vision_capability(config)
    items = attachments_of(message, config=config)
    others = [item for item in (block.get('items') or []) if isinstance(item, dict) and item.get('type') != 'image']
    note = {'items': items or None,
            'other_media_placeholders': [_clean(item.get('placeholder'), 120) for item in others][:MAX_ITEMS_PER_MESSAGE] or None,
            'count': block.get('count'), 'truncated': bool(block.get('truncated')),
            'can_pull': capability['supported'],
            'unsupported_because': capability['unsupported_because'] or None,
            'meaning': ('图片只有元数据和占位符，尚未进入上下文；有需要时可委托行动脑按需读取。'
                        '不拉就不进上下文。占位符本身不代表看过图片；其他媒体仍只有占位符。')}
    return {k: v for k, v in note.items() if v is not None}


READ_IMAGE_TOOL = {
    'name': READ_IMAGE_TOOL_NAME,
    'description': ('按需拉取本授权场景某条消息里的图片附件，并把它变成这一轮真实的视觉输入（Pull 模式：'
                    '入站只带元数据与占位符，没调用就等于没看过）。ref 取自任务输入的 attachments 清单。'
                    '按配置只读联动的场景（同一个人在另一个入口）里的图也在范围内，清单会标 linked_scene=true。'
                    '路由不支持图片、主机不在白名单、超限或不是 png/jpeg/webp/gif 都会返回真实错误码，不会假装看过。'),
    'parameters': {'ref': {'type': 'string', 'required': True}, 'max_bytes': {'type': 'integer'}}}


class VisionService:
    """broker 侧入口：每次调用绑到调用任务自己的场景与纪元，字节复用既有 GridFS BlobStore。

    没有新集合、没有新端口、没有第二个存储服务：图片字节进 `artifact_blobs`，
    回执进已有的 artifacts 行（不带 base64）。
    """

    def __init__(self, store):
        self.store = store
        from .blobs import BlobStore
        self.blobs = BlobStore(store)

    def read_image(self, task, args):
        return read_image_for_task(self.store, self.blobs, task, self.store.config, args)


def route_filtered_tool_names(tools, config):
    """任务能力清单按行动路由的真实能力裁剪：路由不收图时 read_image 不进清单。

    schema 可见性跟着真实能力走，broker 的执行校验仍在原处兜底；两层不互相替代。
    """
    names = [t['name'] if isinstance(t, dict) else str(t) for t in tools]
    if not vision_capability(config)['supported']:
        names = [name for name in names if name != READ_IMAGE_TOOL_NAME]
    return names


def inline_summary(result):
    """写进 artifacts 回执的有界副本：字节已在 GridFS，回执里不留 base64（普通 BSON 行 1 MiB 上限）。"""
    image = result.get('image') or {}
    data = image.get('data') or ''
    out = {k: v for k, v in result.items() if k not in ('image', 'visual')}
    out['inline_image'] = {'media_type': image.get('media_type'), 'base64_chars': len(data),
                           'host_state': result.get('visual'),
                           'note': ('base64 只交给调用方的 DSH 插件；是否真的成为这一轮的视觉输入，'
                                    '看模型侧回执里的 visual 字段（attached / unavailable:原因）。')}
    return out
