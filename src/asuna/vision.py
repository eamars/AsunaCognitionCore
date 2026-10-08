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

from . import animated, channel_kinds
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
# 默认只放行已装平台声明的多媒体主机（channel_kinds.image_hosts；依据是库里存的入站元数据，不是猜的
# CDN 名单）。换了 CDN 时清单会带着 host_not_allowed(具体主机) 说明原因，加一行 vision.image_hosts 即可，
# 不静默放宽；显式写 vision.image_hosts: [] 表示谁都不放行。
USER_AGENT = 'asuna-host/1.0 read-image'


def _error_detail(body):
    """非 2xx 时那一小段服务端说明是有用的（例如 QQ 的“下载链接已过期”）。
    只留有界一行，并把临时凭据隐掉。"""
    text = _clean(body.decode('utf-8', 'ignore'), 160)
    return re.sub(r'(rkey"?\s*[:=]\s*"?)[^&\s"]*', r'\1[已隐藏]', text)


# What to do when no retry can bring this picture back (both brains read it).
GIVE_UP = '重试也一样：不看这张，照实说没看到'
TRY_LATER = '可以过一会儿再试一次；还不行就不看这张，照实说没看到'


def _too_large(cap):
    return ValueError('IMAGE_TOO_LARGE: 图片超过程序上限 %.1f MiB（%d 字节）；%s' % (cap / 1048576, cap, GIVE_UP))


def _not_a_picture(declared=''):
    return ValueError('IMAGE_TYPE_UNSUPPORTED: 拿到的内容不是 png/jpeg/webp/gif（按文件头判断%s）；%s'
                      % ('，主机声明的是 ' + declared if declared else '', GIVE_UP))


def _fetch_failed(status, detail=''):
    """An HTTP refusal: a 4xx (an expired platform link among them) stays one; a 5xx or 408/429 may pass."""
    said = 'IMAGE_FETCH_FAILED: 图片主机回了 HTTP %s%s' % (status, '（' + detail + '）' if detail else '')
    if status in (408, 425, 429) or status >= 500:
        return ValueError(said + '，是那边暂时的问题；' + TRY_LATER)
    return ValueError(said + '，这个链接已经拉不到了（平台的下载链接会过期）；' + GIVE_UP + '，真需要就请对方重发')


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


LOCAL_UPLOAD = 'local-upload:'          # source of a picture the owner attached in her local chat (+ event id)


def local_uploads(store, scope_key, images, event_id):
    """Pictures the owner attached in her local chat → her images in that chat (BlobStore, kind image) and the
    media block her input row records, the same shape a platform adapter writes. DSH already shows each picture
    to her; this is the program's record of it. A retried input stores nothing twice; one that could not be
    read is recorded as such, never dropped."""
    from .blobs import BlobStore
    source = LOCAL_UPLOAD + str(event_id)
    items = []
    for image in list(images or ())[:MAX_ITEMS_PER_MESSAGE]:
        image = image if isinstance(image, dict) else {}
        name = _clean(image.get('name'), 120) or 'image'
        try:
            data = base64.b64decode(image.get('data') or '', validate=True)
        except ValueError:
            data = b''
        media_type = sniff_media_type(data) if data else None
        if image.get('error') or not media_type or len(data) > HARD_MAX_BYTES:
            items.append({'type': 'image', 'placeholder': f'[图片：{name}（没能读取）]', 'file': name,
                          'unreadable': _clean(image.get('error'), 120) or ('IMAGE_TOO_LARGE' if media_type
                                                                            else 'IMAGE_TYPE_UNSUPPORTED')})
            continue
        digest = sha(data)
        stored = store.db.artifacts.find_one({'scope_key': scope_key, 'kind': 'image', 'sha256': digest,
                                              'source_ids': source, 'state': 'DONE', 'storage': 'gridfs'})
        artifact = stored['_id'] if stored else BlobStore(store).put(
            data, scope_key, 'image', media_type=media_type, source_ids=[source])['artifact_id']
        item = {'type': 'image', 'placeholder': f'[图片：{name}]', 'file': name, 'size': str(len(data)),
                'artifact_id': artifact, 'sha256': digest, 'media_type': media_type}
        for key in ('width', 'height'):
            if isinstance(image.get(key), int) and not isinstance(image.get(key), bool):
                item[key] = image[key]
        items.append(item)
    return {'origin': 'local_upload', 'count': len(items), 'items': items} if items else None


def local_upload_item(message, item):
    """A picture the program stored itself from the owner's local chat: never a platform message's claim."""
    return (isinstance(item, dict) and isinstance(item.get('artifact_id'), str)
            and (media_block(message) or {}).get('origin') == 'local_upload'
            and not (message or {}).get('event', {}).get('channel'))


def vision_capability(config, route='executor'):
    """这条模型路由现在到底能不能收图：只看配置声明，不看模型名字。route 是 executor（行动脑）或 character（角色脑）。"""
    lane = route
    route = (config or {}).get(lane, {})
    vision = (config or {}).get('vision', {})
    modalities = [str(m).lower() for m in (route.get('input_modalities') or [])]
    configured = vision.get('image_hosts')
    hosts = [str(h) for h in (channel_kinds.image_hosts() if configured is None else configured)]
    reasons = []
    if 'image' not in modalities:
        reasons.append(f'route_declares_image_input=false（config.{lane}.input_modalities 未声明 image）')
    if not hosts:
        reasons.append('image_hosts_allowlist_empty（vision.image_hosts 被显式清空，任何图片 URL 都会被拒）')
    return {'supported': not reasons, 'input_modalities': modalities, 'image_hosts': hosts,
            'max_bytes': int(vision.get('max_bytes', DEFAULT_MAX_BYTES)),
            'timeout_seconds': float(vision.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)),
            'image_dirs': [str(d) for d in (vision.get('image_dirs') or [])],
            'source': f'config.{lane}.input_modalities + config.vision',
            'unsupported_because': reasons}


MARKET_IDS = ('emoji_id', 'emoji_package_id', 'key')


def sticker_kind(item):
    """'market' (a store sticker the platform can send again by its ids), 'custom' (a picture sent as a
    sticker: kept by its bytes), or None (a photo). The adapter marks stickers; for items stored before it
    did, the platform's kind module may tell from the item (channel_kinds.sticker_of). A store sticker
    without its ids is kept by its bytes like a custom one."""
    marked = item.get('sticker') or channel_kinds.sticker_of(item)
    if marked == 'market':
        return 'market' if all(_clean(item.get(key), 64) for key in MARKET_IDS) else 'custom'
    return 'custom' if marked == 'custom' else None


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
        kind = sticker_kind(item)
        if kind:
            # The platform said this picture was sent as a sticker (ADR-016): she may keep it on her shelf.
            entry['sticker'] = kind
            if kind == 'market':
                entry['market'] = {key: _clean(item.get(key), 64) for key in MARKET_IDS}
        if local_upload_item(message, item):
            # Stored by the program when the owner sent it: read back from the blob store, no host involved.
            reason = None if 'image' in vision['input_modalities'] else 'route_declares_image_input=false（当前模型路由不收图片）'
            entry.update(pullable=reason is None, pull_via='blob', in_conversation=True)
            if reason:
                entry['not_pullable_because'] = reason
            out.append(entry)
            continue
        if url:
            entry['url_host'] = host
        reason = None
        scheme_ok = bool(parsed and parsed.scheme in ('https', 'http') and not parsed.username and not parsed.password)
        local_ok = bool(name and vision['image_dirs'] and '/' not in name and '\\' not in name)
        if item.get('unreadable'):
            reason = 'unreadable（' + _clean(item['unreadable'], 80) + '）'
        elif 'image' not in vision['input_modalities']:
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
        raise Denied('VISION_SCENE_FENCE_MISMATCH: 这个对话和任务记录对不上了（换了纪元或范围）；不是参数的问题，'
                     '重试也一样：停下这一步，把没看成写进结果')
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


def pull_bytes(entry, config, *, max_bytes=None, timeout=None):
    """按元数据把图片字节拉回来。返回 (bytes, media_type, via, source)。失败一律抛真实错误码。

    只用标准库：这条路径要能在没有第三方 HTTP 库的离线自检里真跑一次真实 socket，
    不能只对着替身断言。
    """
    vision = vision_capability(config)
    cap = min(int(max_bytes or vision['max_bytes']), HARD_MAX_BYTES)
    if entry.get('pull_via') == 'url':
        url = _clean(entry.get('url'), URL_LIMIT)
        if not url:
            raise ValueError('IMAGE_URL_MISSING: 原消息里已经没有这张图的链接；' + GIVE_UP)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' and not config.get('vision', {}).get('allow_insecure_http'):
            raise ValueError('IMAGE_INSECURE_URL_DENIED: 这张图的链接是 %s，程序只拉 https；%s' % (parsed.scheme or '空', GIVE_UP))
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        opener = urllib.request.build_opener(_KeepInsideAllowList(vision['image_hosts']))
        try:
            with opener.open(request, timeout=timeout or vision['timeout_seconds']) as response:
                status = getattr(response, 'status', None) or 200
                if status != 200:
                    raise _fetch_failed(status)
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
                        raise _too_large(cap)
                    chunks.append(part)
                data = b''.join(chunks)
        except _RedirectDenied as exc:
            raise ValueError(f'IMAGE_REDIRECT_HOST_DENIED: 图片链接跳到了 {exc}，不在 vision.image_hosts 白名单里；{GIVE_UP}') from exc
        except urllib.error.HTTPError as exc:
            try:
                detail = _error_detail(exc.read(512) or b'')
            except Exception:  # noqa: BLE001 读不到原因也要报状态码
                detail = ''
            raise _fetch_failed(exc.code, detail) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ValueError(f'IMAGE_FETCH_FAILED: 连不上图片主机（{type(exc).__name__}，限时 '
                             f'{timeout or vision["timeout_seconds"]:g} 秒）；{TRY_LATER}') from exc
        if not host_allowed(final_host, vision['image_hosts']):
            raise ValueError(f'IMAGE_REDIRECT_HOST_DENIED: 图片链接跳到了 {final_host or '未知主机'}，'
                             f'不在 vision.image_hosts 白名单里；{GIVE_UP}')
    elif entry.get('pull_via') == 'local_file':
        name = _clean(entry.get('file'), 120)
        if not name or '/' in name or '\\' in name:
            raise ValueError('IMAGE_FILE_NAME_DENIED: 附件的文件名 %r 是空的或带路径分隔符，程序不按它找本机文件；%s'
                             % (name, GIVE_UP))
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
                raise _too_large(cap)
            data = resolved.read_bytes()
            break
        if data is None:
            raise ValueError('IMAGE_FILE_NOT_AVAILABLE: 本机图片目录里没有 %s（可能已被清理）；%s' % (name, GIVE_UP))
        content_type = ''
        final_host = ''
    else:
        raise ValueError('IMAGE_SOURCE_UNAVAILABLE: 这张图没有能拉的来源（没有可用的链接，也没有本机文件）；' + GIVE_UP)
    media_type = sniff_media_type(data)
    if media_type is None:
        raise _not_a_picture(_clean(content_type, 80))
    if not data:
        raise ValueError('IMAGE_EMPTY: 拉回来是空的（0 字节）；' + TRY_LATER)
    return data, media_type, entry.get('pull_via'), {'host': final_host, 'content_type': _clean(content_type, 80)}


ARTIFACT_REF = re.compile(r'blob-[0-9a-f]{16,64}')


def read_image_for_task(store, blobs, task, config, args, *, route='executor', offered=()):
    """read_image 的实际执行：场景围栏 → 能力核对 → 拉字节 → 落 BlobStore → 交给插件的视觉输入载荷。

    两个脑共用这一个工具：行动脑按任务调用，角色脑按她这回合的场景调用（role_tools.py）；`task` 只需要
    scene_id、scope_key、policy_epoch，围栏与落盘口径完全相同，route 只决定核对哪条路由能不能收图。
    ref 也可以是一张已存好的图的 artifact_id（她画的、本场景存的、这一轮可发的 ``offered``），用来回看。"""
    args = args if isinstance(args, dict) else {}
    unknown = set(args) - {'ref', 'max_bytes'}
    if unknown:
        raise ValueError('READ_IMAGE_ARGUMENT_DENIED: 不认识的参数 %s；只收 ref' % '、'.join(sorted(unknown)))
    ref = args.get('ref')
    if not isinstance(ref, str) or not 4 <= len(ref) <= 80:
        raise ValueError('INVALID_READ_IMAGE_REF: ref 要是 4..80 字的字符串，给的是 %s；照抄图旁标的 ref（att-…），'
                         '或一张存好的图的 artifact_id（blob-…）'
                         % ('%d 字' % len(ref) if isinstance(ref, str) else '没给' if ref is None else type(ref).__name__))
    # The size cap is the program's (vision.max_bytes); DSH scales every picture for the model. A caller's own
    # max_bytes only refused pictures over its guess (2026-10-06: 20 KB-200 KB guesses on stickers), so an old
    # call that still sends one is read with the program's cap.
    max_bytes = None
    capability = vision_capability(config, route)
    if not capability['supported']:
        raise ValueError('VISION_ROUTE_UNSUPPORTED: 这条模型路由收不了图（%s）；重试也一样%s'
                         % ('；'.join(capability['unsupported_because']),
                            '' if route == 'character' else '：不看图能做的先做，看不了的写进结果'))
    if ARTIFACT_REF.fullmatch(ref):
        return stored_image(store, blobs, task, config, ref, max_bytes, offered)
    listing = scene_attachments(store, task, config, limit=MAX_ITEMS_PER_MESSAGE, scan=SCENE_SCAN_MESSAGES)
    entry = next((item for item in listing['attachments'] if item['ref'] == ref), None)
    if not entry:
        # 不区分「不存在」与「在围栏外的场景／别的纪元」：不借这个工具探测别人的图。只列本任务可读范围里的 ref。
        recent = [item['ref'] for item in listing['attachments']]
        raise ValueError('IMAGE_ATTACHMENT_NOT_IN_SCENE: %s 不在这个对话最近的图里；%s'
                         % (ref, '最近的是 ' + '、'.join(recent) + '，ref 照抄其中一个' if recent
                            else '最近 %d 条消息里没有图，%s' % (SCENE_SCAN_MESSAGES, GIVE_UP)))
    if not entry.get('pullable'):
        raise ValueError('IMAGE_NOT_PULLABLE: 这张图拉不了（%s）；%s'
                         % (entry.get('not_pullable_because') or '原因不明', GIVE_UP))
    if entry.get('pull_via') == 'blob':
        # A picture from the owner's local chat: already stored when it arrived; read it back, store nothing new.
        data, blob = local_upload_bytes(store, blobs, task, config, entry, max_bytes)
        media_type, via, source = sniff_media_type(data), 'blob', {'host': '', 'content_type': ''}
    else:
        full = dict(entry)
        full['url'] = (media_source_url(store, task, config, entry))
        data, media_type, via, source = pull_bytes(full, config, max_bytes=max_bytes)
        blob = None
    digest = sha(data)
    shown, moving = animated.seen(data, media_type)
    if blob is None:
        # 字节按**本任务**的 scope 落盘：图来自联动场景也不会写进别人场景的账本。
        blob = (blobs.put(data, task['scope_key'], 'image', media_type=media_type,
                          source_ids=[entry['source_message_id']]) if blobs else None)
    payload = {'ref': ref, 'scene_id': task['scene_id'],
               'image_scene_id': _clean(entry.get('scene_id'), 90) or task['scene_id'],
               'linked_scene': bool(entry.get('linked_scene')),
               'source_message_id': entry['source_message_id'],
               'placeholder': entry.get('placeholder'), 'summary': entry.get('summary') or None,
               'sticker': entry.get('sticker') or None, 'media_type': media_type, 'bytes': len(data), 'sha256': digest, 'pulled_via': via,
               'source': source, 'blob_artifact': (blob or {}).get('artifact_id'),
               'blob_sha256': (blob or {}).get('sha256'),
               'image': shown, **({'animated': moving} if moving else {}),
               'visual': 'awaiting_attachment',
               'note': '图片字节已按本次调用真实拉取；此前正文里的占位符只说明这里出现过一张图，不代表内容已被读过。'}
    if payload['linked_scene']:
        payload['scene_note'] = ('这张图来自本场景按配置只读联动的另一个场景（同一个人在那边的入口）。'
                                 '放宽的只有读：字节按本任务的 scope 存，写与出站不因此放宽。')
    return payload


def stored_image(store, blobs, task, config, artifact_id, max_bytes=None, offered=()):
    """Look again at a picture already stored as an image artifact: one in this scene's own scope, one she
    made herself (her own generator, any scene), or one this turn was offered to send. Anything else answers
    exactly like an unknown id, so the tool cannot be used to probe other people's pictures."""
    from .outbound_media import produced
    row = store.db.artifacts.find_one({'_id': artifact_id, 'kind': 'image', 'state': 'DONE', 'storage': 'gridfs'})
    if (not blobs or not row or not (row.get('scope_key') == task.get('scope_key') or produced(row)
                                     or artifact_id in (offered or ()))):
        raise ValueError('IMAGE_ARTIFACT_NOT_READABLE: %s 不是能看的图：没有这张，或它不在这个对话里、不是你画的、'
                         '也不是这一轮可发的；自己画的图照抄 generate_image 回执里的 artifact.artifact_id' % artifact_id)
    data = blobs.get(artifact_id, row['scope_key'], operator=True)
    cap = min(int(max_bytes or vision_capability(config)['max_bytes']), HARD_MAX_BYTES)
    if len(data) > cap:
        raise _too_large(cap)
    media_type = sniff_media_type(data)
    if media_type is None:
        raise _not_a_picture()
    shown, moving = animated.seen(data, media_type)
    return {'ref': artifact_id, 'artifact_id': artifact_id, 'scene_id': task['scene_id'],
            'media_type': media_type, 'bytes': len(data), 'sha256': sha(data), 'pulled_via': 'artifact',
            'produced': produced(row),
            'image': shown, **({'animated': moving} if moving else {}),
            'visual': 'awaiting_attachment',
            'note': '这是存好的那张图本身；看完再判断它是不是要的样子。'}


LOCAL_NOT_IN_SCENE = 'IMAGE_ATTACHMENT_NOT_IN_SCENE: 这张图的原消息已经不在这个对话可读的范围里；' + GIVE_UP


def local_upload_bytes(store, blobs, task, config, entry, max_bytes=None):
    """A local-chat picture's stored bytes, re-checked against the row that records it: the row must be the
    program's own local input (no platform envelope), and the artifact must be in that row's scope with that
    input as its source — a platform message naming an artifact id gets nothing."""
    scene_id = _clean(entry.get('scene_id'), 90) or task['scene_id']
    if scene_id not in {scope['scene_id'] for scope in readable_image_scenes(store, task, config)}:
        raise ValueError(LOCAL_NOT_IN_SCENE)
    row = store.db.messages.find_one({'_id': entry['source_message_id'], 'scene_id': scene_id,
                                      'policy_epoch': task['policy_epoch']})
    items = (media_block(row) or {}).get('items') or [] if row else []
    item = next((item for index, item in enumerate(items) if ref_of(row['_id'], index) == entry['ref']), None)
    if not local_upload_item(row, item):
        raise ValueError(LOCAL_NOT_IN_SCENE)
    artifact = store.db.artifacts.find_one({'_id': item['artifact_id'], 'kind': 'image', 'state': 'DONE',
                                            'storage': 'gridfs'})
    if (not blobs or not artifact or artifact.get('scope_key') != row.get('scope_key')
            or LOCAL_UPLOAD + str(row['event'].get('event_id')) not in (artifact.get('source_ids') or [])):
        raise ValueError('IMAGE_SOURCE_UNAVAILABLE: 这张本机聊天里的图已经不在存储里了；' + GIVE_UP)
    data = blobs.get(artifact['_id'], artifact['scope_key'], operator=True)
    cap = min(int(max_bytes or vision_capability(config)['max_bytes']), HARD_MAX_BYTES)
    if len(data) > cap:
        raise _too_large(cap)
    if sniff_media_type(data) is None:
        raise _not_a_picture()
    return data, {'artifact_id': artifact['_id'], 'sha256': artifact['sha256']}


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


def line_refs(message, config, recognize=None):
    """The refs of a platform line's readable pictures, as a short note under the line in her conversation:
    the placeholder says a picture was there, the ref is what read_image takes. Empty when there is none.
    ``recognize`` (entries -> {ref: words}) adds what she already knows of a sticker (stickers.recognized)."""
    every = attachments_of(message, config=config)
    known = recognize(every) if recognize else {}
    entries = [entry for entry in every
               if entry.get('pullable') or entry.get('sticker') == 'market' or entry['ref'] in known]
    pictures = [entry['ref'] for entry in entries if not entry.get('sticker')]
    stickers = [entry['ref'] + ('，' + known[entry['ref']] if entry['ref'] in known else '')
                for entry in entries if entry.get('sticker')]
    # A sticker's ref is also what keeping it takes (ADR-016); a store sticker can be kept without looking.
    return (('（图 ref：' + '、'.join(pictures) + '）') if pictures else '') + \
           (('（表情包 ref：' + ('；' if known else '、').join(stickers) + '）') if stickers else '')


def media_note(message, config):
    """给角色现场的附件元数据：不把图片字节放进上下文。"""
    block = media_block(message)
    if not block:
        return None
    # Her own route decides whether she can look herself; the action brain's is what a delegation would use.
    capability = vision_capability(config, 'character')
    items = attachments_of(message, config=config)
    others = [item for item in (block.get('items') or []) if isinstance(item, dict) and item.get('type') != 'image']
    note = {'items': items or None,
            'other_media_placeholders': [_clean(item.get('placeholder'), 120) for item in others][:MAX_ITEMS_PER_MESSAGE] or None,
            'count': block.get('count'), 'truncated': bool(block.get('truncated')),
            'can_pull': capability['supported'],
            'unsupported_because': capability['unsupported_because'] or None,
            'meaning': (('这些是对方在本机聊天里直接发给你的图，就在对话里，你看得见。要交给行动脑处理，'
                         '把图的 ref 一起交代给它，它也用 read_image 读。')
                        if block.get('origin') == 'local_upload' and not (message or {}).get('event', {}).get('channel')
                        else ('图片只有元数据和占位符，尚未进入上下文；想看就用 read_image(ref) 自己看，'
                              '交给行动脑做事时把 ref 一起交代。没看就是没看过，占位符不代表看过；其他媒体仍只有占位符。')
                        if capability['supported']
                        else ('图片只有元数据和占位符，尚未进入上下文；有需要时可委托行动脑按需读取。'
                              '不拉就不进上下文。占位符本身不代表看过图片；其他媒体仍只有占位符。'))}
    return {k: v for k, v in note.items() if v is not None}


READ_IMAGE_TOOL = {
    'name': READ_IMAGE_TOOL_NAME,
    'description': ('按需拉取本授权场景某条消息里的图片附件，并把它变成这一轮真实的视觉输入（Pull 模式：'
                    '入站只带元数据与占位符，没调用就等于没看过）。ref 照抄附件清单（attachments、media_from_program）'
                    '或对话里图片旁标出的 ref；只认这个对话最近的几张图。'
                    '按配置只读联动的场景（同一个人在另一个入口）里的图也在范围内，清单会标 linked_scene=true。'
                    'ref 也可以是一张已存好的图的 artifact_id（blob-…）：自己画的图（generate_image 回执里的 '
                    'artifact.artifact_id）、本场景存过的图、这一轮可发的图——画完或发之前用它亲眼看一遍。'
                    '大小不用管：程序按自己的上限拉，给模型之前会自己缩放。'
                    '路由不支持图片、主机不在白名单、超过程序上限或不是 png/jpeg/webp/gif 都会返回真实错误码，不会假装看过。'),
    'parameters': {'ref': {'type': 'string', 'required': True}}}


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
