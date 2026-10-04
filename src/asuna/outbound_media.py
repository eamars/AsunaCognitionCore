"""出站图片附件：DECIDE 的 attach → SPEAK 行上的元数据 → 通道字节端点 → 已送达历史。

字节只在 BlobStore（GridFS）里。messages 行只带 ``{artifact_id, media_type, sha256, size}``，
不带 base64：普通 BSON 行 1 MiB 上限，而一张 QQ 照片常有 4–6 MiB。领取方（napcat-qq 0.5.0）
先在 claim 里拿到这份元数据，再按 publication + attempt 来取字节 —— 取字节的围栏全在这个模块里，
HTTP 层只做路由与写响应。

第一版只开 owner 的 QQ 私聊：``session_class=owner_private`` 且该场景的路由 ``target.type=dm``。
群方向确定性拒绝，不静默降级成「只发文字却报平台已送达」——那种回执会声称对方收到了一张从没
到达的图。历史投影里的附件位同理：只有送达回执对得上的图才算「我发过这张图」。

图可以来自两个地方：这个场景自己登记的（``read_image`` 看过的、``import_integration_artifact``
导入时顺手登记的），以及**同一主人的另一个 owner_private 场景**登记的——生图和导入只在本机
owner 任务里能做，而要说图的那一轮常在 QQ 私聊，两个入口都是主人自己的私人空间。这一条边由
``image_scopes`` 现算自配置：canonical person、session_class、联动边三项都过才多开那个 scope；
群、别人的场景、没联动的场景、public 会话一律不在列表里。字节端点用 ``row_image_scopes`` 从
行自己重算同一份列表，不接受调用方传进来的 scope。
"""
from __future__ import annotations

import hashlib
import re

try:                                  # 宿主内：与 channels / history_query 同一套围栏
    from .state import Denied
    from .visibility import OWNER_PRIVATE
except Exception:                     # 同目录平铺加载（离线自检）也认
    from state import Denied
    from visibility import OWNER_PRIVATE

try:                                  # 谁是同一个人、哪两个场景联动：只看配置（scene_links 是唯一来源）
    from . import scene_links
    from . import visibility
except Exception:                     # 拿不到就只认本场景，与只开本场景时的行为逐字一致
    try:
        import scene_links
        import visibility
    except Exception:
        scene_links = None
        visibility = None

SHA256 = re.compile(r'^[0-9a-f]{64}$')

# 与 napcat-qq 0.5.0 同一口径：适配器自己的上限是 8 MiB，超过它它就不取字节。
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MEDIA_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
CAPABILITY = 'image'                  # claim 上声明的能力名；不声明就只拿得到文字
ATTACHMENT_KIND = 'image'             # BlobStore 里图片 artifact 的 kind（vision.py 写这个）
ATTACHMENT_KEY = 'attachment'
SKIPPED_KEY = 'attachment_skipped'
NO_CAPABILITY = 'channel_does_not_declare_image'
MAX_ITEMS_OFFERED = 6                 # 一轮最多给她看几张可引用的图
IMPORTED_NOTE = ('这张图已经登记进这个场景的存储，可以在要发图的那一轮从 '
                 'image_artifacts_from_program 里引用；同一主人的另一个私聊入口也能引用它。')

OFFER_NOTE = ('这些是程序已经存好、这一轮可以随你要说的那条消息一起发出去的图片。'
              '想发就在 DECIDE 里给 attach:[{"artifact_id":"…","why":"…"}]（至多 1 条），'
              'artifact_id 只能照抄下面列出的值——它不是文件路径也不是文件名。'
              '正文里不要写文件路径、文件名或「见图」之类的话，图是随这条消息一起到的。'
              '没列出的图片不能发；一轮最多带一张。')
PEER_NOTE = ('其中标了 from_linked_scene 的那几张不是这个场景里生成的，是你另一个只属于'
             '你自己的私聊入口里存的图，程序确认过那一边也是你本人的私人空间，可以照发。')


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_media_type(data):
    """只认魔数，和 vision.sniff_media_type 同一张表（离线用例逐条比对，防两处漂移）。"""
    if not isinstance(data, (bytes, bytearray)):
        return None
    data = bytes(data)
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return 'image/gif'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def parse_supports(query):
    """``?supports=image,voice`` → ``['image','voice']``；老适配器不带这个参数就是空。"""
    out = []
    for value in (query or {}).get('supports') or []:
        for item in str(value).split(','):
            item = item.strip().lower()
            if item and item not in out:
                out.append(item)
    return out


def supports_image(supports) -> bool:
    return CAPABILITY in tuple(supports or ())


def descriptor(row):
    """行上那份附件元数据（校验过的副本）；形状不对就当没有，不猜。"""
    raw = (row or {}).get(ATTACHMENT_KEY)
    if not isinstance(raw, dict):
        return None
    artifact_id = raw.get('artifact_id')
    digest = str(raw.get('sha256') or '').strip().lower()
    media_type = raw.get('media_type')
    if not isinstance(artifact_id, str) or not 1 <= len(artifact_id) <= 200:
        return None
    if not SHA256.match(digest):
        return None
    if media_type not in MEDIA_TYPES:
        return None
    out = {'artifact_id': artifact_id, 'media_type': media_type, 'sha256': digest}
    size = raw.get('size')
    if isinstance(size, int) and not isinstance(size, bool) and 0 < size <= MAX_ATTACHMENT_BYTES:
        out['size'] = size
    return out


def declared(row):
    """这条 publication **现在**到底有没有声明「随这条消息发一张图」。

    ``descriptor`` 只看元数据在不在；行上记着 ``attachment_skipped`` 说明当前这一次领取根本没把
    图带出去（领取方没声明能收图），留在行上的元数据只是让历史看得见「这条本来带图」。字节端点要
    问的是前者，不是后者——否则一条只发了文字的消息还能把图字节领走。
    """
    if (row or {}).get(SKIPPED_KEY):
        return None
    return descriptor(row)


def attachment_for_speak(ep):
    """这一轮被程序接受的那张图 → SPEAK 第一行要写的元数据（没有就 None）。

    图只跟最后一次 DECIDE 走：``decide_delta.apply`` 每一轮都把 ``delta_results['attach']`` 重写成
    本轮接受的那一张 —— 本轮没给、或给的那张被退回，就没有这一项，也就没有图（前一轮那张不会跟着走）。
    schema 一轮至多一条，所以这里只看那一条，形状不对就当没有。
    """
    items = ((ep or {}).get('delta_results') or {}).get('attach') or []
    item = items[0] if items and isinstance(items[0], dict) else None
    return descriptor({ATTACHMENT_KEY: item}) if item else None


def target_allowed(config, scene, session_class):
    """第一版的收件方向：owner 私聊 + 该场景路由 target.type=dm。返回 (可以, 原因)。"""
    if session_class != OWNER_PRIVATE:
        return False, 'session_class_not_owner_private'
    scene_id = (scene or {}).get('_id')
    channel_id = (scene or {}).get('channel_id')
    if not scene_id or not channel_id:
        return False, 'scene_has_no_channel_route'
    try:
        from .channels import route_for_scene       # 路由只有一份来源，这里不另算一遍
        route = route_for_scene(config, channel_id, scene_id)
    except Exception:
        return False, 'channel_route_not_authorized'
    if ((route or {}).get('target') or {}).get('type') != 'dm':
        return False, 'target_not_dm'
    return True, ''


def _route_person(config, scene, channel_id=None):
    """这个场景是谁的私人空间：dm 路由上写的 person_id，没有就看场景唯一的成员。"""
    scene_id = (scene or {}).get('_id')
    channel_id = channel_id or (scene or {}).get('channel_id')
    person = ''
    if channel_id and scene_id:
        try:
            from .channels import route_for_scene   # 路由只有一份来源，这里不另算一遍
            person = (route_for_scene(config, channel_id, scene_id) or {}).get('person_id') or ''
        except Exception:
            person = ''
    if person:
        return person
    members = [item for item in ((scene or {}).get('members') or []) if isinstance(item, str) and item]
    return members[0] if len(members) == 1 else ''


def _linked_scene_ids(config, scene_id):
    """配置里与这个场景有联动的其他场景（同一主人的两个私人入口之间不认方向）。

    ``context_links`` 本身是有向的读边。这里对**同一 canonical person 的两个 owner_private
    场景**双向认：两边都是主人自己的私人空间，把自己生成的图递给自己另一个入口不会把
    owner_private 的数据带进 public 会话（public→private 那种降级由
    ``visibility.without_link_downgrades`` 在启动时挡掉）。别的场景对仍然按有向边读。
    """
    if scene_links is None or not scene_id:
        return []
    try:
        links = scene_links.context_links(config)
    except Exception:
        return []
    out = list(links.get(scene_id) or ())
    for reader, targets in links.items():
        if scene_id in (targets or ()):
            out.append(reader)
    return [item for item in dict.fromkeys(out) if item and item != scene_id][:scene_links.MAX_LINKS]


def _canonical(config, db, person_id):
    if scene_links is None or not person_id:
        return person_id
    try:
        return scene_links.canonical_person_id(config, db, person_id)
    except Exception:
        return person_id


def image_scopes(store, config, scene, session_cls=None, person_id=None):
    """这一轮能引用哪些场景里登记的图（本场景永远排第一）。

    除本场景外只多开一种：同一 canonical person 的另一个 ``owner_private`` dm 场景，且配置里
    这两个场景之间有联动边。session_class 由 visibility 现算，「谁是同一个人」只看
    canonical_persons，联动只看 context_links／路由 read_scenes——模型和适配器都改不了这个
    列表。群、别人的场景、没联动的场景、public 会话都不在这里。
    """
    own = (scene or {}).get('scope_key')
    out = [own] if own else []
    scene_id = (scene or {}).get('_id')
    if scene_links is None or visibility is None or not scene_id:
        return out
    if session_cls is None:
        try:
            session_cls = visibility.session_class(config, store.db, scene, person_id or '')
        except Exception:
            return out
    if session_cls != OWNER_PRIVATE:
        return out
    if person_id is None:
        person_id = _route_person(config, scene)
    mine = _canonical(config, store.db, person_id)
    if not mine:
        return out
    for peer_id in _linked_scene_ids(config, scene_id):
        try:
            peer = store.db.scenes.find_one({'_id': peer_id})
        except Exception:
            continue
        if not isinstance(peer, dict) or peer.get('kind') != 'dm' or not peer.get('scope_key'):
            continue
        peer_person = _route_person(config, peer)
        if not peer_person:
            continue
        try:
            if visibility.session_class(config, store.db, peer, peer_person) != OWNER_PRIVATE:
                continue
        except Exception:
            continue
        if _canonical(config, store.db, peer_person) != mine:
            continue
        if peer['scope_key'] not in out:
            out.append(peer['scope_key'])
    return out


def row_image_scopes(store, row):
    """这条消息那一轮能引用哪些 scope：全部从行自己算（场景、路由上的人、session_class）。"""
    row = row or {}
    try:
        scene = store.db.scenes.find_one({'_id': row.get('scene_id')}) or {}
    except Exception:
        scene = {}
    if not scene.get('scope_key'):
        scene = dict(scene, _id=row.get('scene_id'), scope_key=row.get('scope_key'))
    return image_scopes(store, store.config, scene,
                        person_id=_route_person(store.config, scene, row.get('channel_id')))


def image_artifacts(store, scope_keys, *, limit=MAX_ITEMS_OFFERED, own_scope=None):
    """本轮可引用的图片：这些 scope 里已存好的 image artifact（新的在前，最多 limit 条）。

    只列 kind=image / state=DONE / storage=gridfs 且字节不超过上限的那些；老行没有 created_at
    就排在后面。这里不读字节 —— 读字节与认格式在 accept_artifact 里，被选中时才做一次。
    来自别的场景（同一主人的另一个私人入口）的那几张会多带 ``from_linked_scene`` 与 ``scene_id``，
    让她看得见这张图不是这个场景里生成的；只有一个 scope 时行形状与只认本场景时逐字一致。
    """
    scopes = [scope_keys] if isinstance(scope_keys, str) else [item for item in (scope_keys or ()) if item]
    if not scopes:
        return []
    wanted = scopes[0] if len(scopes) == 1 else {'$in': scopes}
    own_scope = own_scope or (scopes[0] if len(scopes) == 1 else None)
    try:
        cursor = store.db.artifacts.find({'scope_key': wanted, 'kind': ATTACHMENT_KIND,
                                         'state': 'DONE', 'storage': 'gridfs'})
        # 每轮都要问一次，所以读是有界的：新的在前、只取够用的几份元数据行，字节一个都不读。
        if hasattr(cursor, 'sort'):
            cursor = cursor.sort('created_at', -1)
        if hasattr(cursor, 'limit'):
            cursor = cursor.limit(max(1, int(limit or 1)) * 10)
        rows = list(cursor)
    except Exception:
        return []
    rows.sort(key=lambda row: str(row.get('created_at') or ''), reverse=True)
    out = []
    for row in rows:
        size, digest = row.get('size'), str(row.get('sha256') or '').strip().lower()
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ATTACHMENT_BYTES:
            continue
        if not SHA256.match(digest):
            continue
        media_type = row.get('media_type')
        item = {'artifact_id': row.get('_id'), 'sha256': digest, 'size': size,
                'media_type': media_type if media_type in MEDIA_TYPES else None,
                'created_at': row.get('created_at')}
        scope = row.get('scope_key')
        if own_scope is not None and scope != own_scope:
            item['from_linked_scene'] = True
            item['scene_id'] = scope[len('scene:'):] if isinstance(scope, str) and \
                scope.startswith('scene:') else scope
        out.append(item)
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def offer(store, config, scene, session_class, person_id=None, *, limit=MAX_ITEMS_OFFERED):
    """上下文里那块 ``image_artifacts_from_program``；方向不允许或没图可引用就不出现。"""
    allowed, _reason = target_allowed(config, scene, session_class)
    if not allowed:
        return None
    own_scope = (scene or {}).get('scope_key')
    items = image_artifacts(store, image_scopes(store, config, scene, session_class, person_id),
                            limit=limit, own_scope=own_scope)
    if not items:
        return None
    note = OFFER_NOTE + (PEER_NOTE if any(item.get('from_linked_scene') for item in items) else '')
    return {'items': items, 'note': note}


def accept_artifact(store, blobs, artifact_id, scope_keys):
    """程序接受一张图准备随这条消息发出去：读一次字节、认魔数、按行内 sha 复核。

    ``scope_keys`` 是程序算好的可引用 scope 列表（本场景 + 同一主人的另一个 owner_private
    场景）；artifact 的 scope 不在列表里就是 ATTACHMENT_SCOPE_DENIED。返回行上要写的元数据；
    任何一条不成立都抛 Denied（调用方逐条记进 rejections）。
    """
    scopes = [scope_keys] if isinstance(scope_keys, str) else [item for item in (scope_keys or ()) if item]
    item = store.db.artifacts.find_one({'_id': artifact_id})
    if not item or item.get('state') != 'DONE' or item.get('storage') != 'gridfs':
        raise Denied('ATTACHMENT_ARTIFACT_UNAVAILABLE')
    if item.get('scope_key') not in scopes:
        raise Denied('ATTACHMENT_SCOPE_DENIED')
    if item.get('kind') != ATTACHMENT_KIND:
        raise Denied('ATTACHMENT_NOT_AN_IMAGE')
    size = item.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ATTACHMENT_BYTES:
        raise Denied('ATTACHMENT_OVER_LIMIT')
    try:
        # 按 artifact 自己的 scope 读：跨不跨场景由上面那份列表决定，这里不放宽 BlobStore 的判定
        data = blobs.get(artifact_id, item['scope_key'], operator=True)   # 内部按行内 sha 复核
    except ValueError as exc:
        raise Denied('ATTACHMENT_HASH_MISMATCH') from exc
    media_type = sniff_media_type(data)
    if media_type is None:
        raise Denied('ATTACHMENT_NOT_AN_IMAGE')
    return {'artifact_id': artifact_id, 'media_type': media_type, 'sha256': sha256_of(data),
            'size': len(data)}


def serve(store, blobs, row, declared):
    """字节端点的围栏：只发这一条 publication 自己声明的那张图，且行内 sha 复核通过。

    返回 ``(data, media_type)``。``BlobStore.get`` 的 operator 谓词不放宽：这里显式以 operator
    身份读，并且额外要求 artifact 行的 scope 与 sha 就是这条 publication 声明的那一份。
    scope 那份列表用 ``row_image_scopes`` 从行自己重算（场景、路由上的人、session_class 都现算），
    所以能发出去的范围与 DECIDE 当时看到的清单一致，不接受调用方传 scope。

    第一道闸是「这条到底声明了没」：行上记着 ``attachment_skipped``（领取方没声明 image 能力）就
    直接拒，不看元数据——围栏在 serve 里自己判，不靠 claim 阶段与 HTTP 层替它记得。
    """
    if (row or {}).get(SKIPPED_KEY):
        raise Denied('ATTACHMENT_NOT_DECLARED')       # 图没跟着这条出去，字节也不给
    item = store.db.artifacts.find_one({'_id': declared['artifact_id']})
    if not item or item.get('state') != 'DONE' or item.get('storage') != 'gridfs':
        raise Denied('ATTACHMENT_ARTIFACT_UNAVAILABLE')
    if item.get('scope_key') not in row_image_scopes(store, row):
        raise Denied('ATTACHMENT_SCOPE_DENIED')
    if str(item.get('sha256') or '').strip().lower() != declared['sha256']:
        raise Denied('ATTACHMENT_SHA_MISMATCH')
    try:
        data = blobs.get(declared['artifact_id'], item['scope_key'], operator=True)
    except ValueError as exc:
        raise Denied('ATTACHMENT_HASH_MISMATCH') from exc
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise Denied('ATTACHMENT_OVER_LIMIT')
    media_type = sniff_media_type(data)
    if media_type is None:
        raise Denied('ATTACHMENT_NOT_AN_IMAGE')
    if media_type != declared['media_type']:
        raise Denied('ATTACHMENT_MEDIA_TYPE_MISMATCH')
    return data, media_type


def register_imported_image(store, scope_key, data, *, source=None):
    """把刚导入的字节登记成这个 scope 里的 image artifact；不是图片就什么都不做。

    哈希与格式都以宿主自己从字节算出来的为准（BlobStore.put 自己算 sha 并回读复核），行动侧
    声明的 nothing 都不参与。超过出站上限、scope 不认识、存储写失败都不登记，只如实回报原因——
    文件已经写进工作区了，不能因为登记失败把一次成功的导入判成失败。返回 None 表示「这不是图，
    没什么可报」。
    """
    media_type = sniff_media_type(data)
    if media_type is None:
        return None
    size = len(data)
    if not 0 < size <= MAX_ATTACHMENT_BYTES:
        return {'registered': False, 'reason': 'ATTACHMENT_OVER_LIMIT', 'media_type': media_type,
                'bytes': size, 'max_bytes': MAX_ATTACHMENT_BYTES,
                'note': '文件已经写进工作区，但超过出站图片上限 %d 字节，没有登记成可引用的图。'
                        % MAX_ATTACHMENT_BYTES}
    try:
        from .blobs import BlobStore
        stored = BlobStore(store).put(bytes(data), scope_key, ATTACHMENT_KIND, media_type=media_type,
                                      source_ids=[source[:200]] if source else ())
    except Exception as exc:
        reason = str(exc).split(':')[0].split(' ')[0].strip() or 'ARTIFACT_REGISTER_FAILED'
        return {'registered': False, 'reason': reason[:80], 'media_type': media_type, 'bytes': size,
                'note': '文件已经写进工作区，但没有登记成可引用的图；原因如实带在这里。'}
    return {'registered': True, 'artifact_id': stored['artifact_id'], 'media_type': media_type,
            'sha256': stored['sha256'], 'bytes': stored['size'], 'scope_key': scope_key,
            'note': IMPORTED_NOTE}


def import_register(store, task):
    """给 ``import_integration_artifact`` 的登记回调：只登记到这个任务自己绑定的 scope。

    scope 取自任务绑定，不是参数——工具参数面没有 scope 这一项，行动侧改不了它。任务没有
    scope（或没有 store）就不登记，导入行为与改动前逐字一致。
    """
    scope_key = (task or {}).get('scope_key')
    if store is None or not isinstance(scope_key, str) or not scope_key:
        return None

    def register(data, meta=None):
        meta = meta or {}
        source = 'integration:%s:%s' % (meta.get('endpoint'), meta.get('artifact_path'))
        return register_imported_image(store, scope_key, data, source=source)

    return register


def receipt_evidence(row, store=None):
    """平台回执里那份附件证据（适配器真的取到并发了图才会写）。行里没带就按 _id 窄取一次。"""
    raw = (row or {}).get('platform_receipt')
    if not isinstance(raw, dict) and store is not None and row.get('_id'):
        full = store.db.messages.find_one({'_id': row['_id']}, {'platform_receipt': 1}) or {}
        raw = full.get('platform_receipt')
    if not isinstance(raw, dict):
        return None
    response = raw.get('response')
    att = response.get(ATTACHMENT_KEY) if isinstance(response, dict) else None
    return att if isinstance(att, dict) else None


def sent_attachment(row, store=None):
    """这条已送达消息真的带出去的那张图；没有就 None。

    平台回执带附件证据时必须 sha 对得上且 ``sha256_verified`` 为真；回执没带证据时仍算发过，
    但标 ``attested=False``，措辞上不说成平台确认过。
    """
    declared = descriptor(row)
    if not declared or (row or {}).get('direction') != 'outbound':
        return None
    if row.get('delivery_state') != 'DELIVERED' or row.get(SKIPPED_KEY):
        return None
    evidence = receipt_evidence(row, store)
    if evidence is None:
        return dict(declared, attested=False)
    if str(evidence.get('sha256') or '').strip().lower() != declared['sha256']:
        return None
    if evidence.get('sha256_verified') is not True:
        return None
    return dict(declared, attested=True)


def history_slot(row, store=None):
    """历史行上的附件位：让她看得见「我发过这张图」，也看得见图没跟着出去。"""
    declared = descriptor(row)
    if not declared or (row or {}).get('direction') != 'outbound':
        return None
    if row.get(SKIPPED_KEY):
        return {'sent': False, 'reason': str(row[SKIPPED_KEY])[:80],
                'note': '这条本来要带一张图，但领取这条消息的通道没声明能收图片，只有文字发出去了'}
    sent = sent_attachment(row, store)
    if sent is None:
        if row.get('delivery_state') != 'DELIVERED':
            return None
        return {'sent': False, 'reason': 'attachment_evidence_mismatch',
                'note': '这条记着要带一张图，但送达回执里的附件对不上，不能当成图已经发出去了'}
    size = sent.get('size')
    note = '我发过这张图（%s%s）' % (sent['media_type'], '，%d 字节' % size if size else '')
    if not sent.get('attested'):
        note += '；平台回执没带附件证据，这条按程序自己的记录算'
    slot = {'sent': True, 'media_type': sent['media_type'], 'sha256': sent['sha256'],
            'attested': bool(sent.get('attested')), 'note': note}
    if size:
        slot['bytes'] = size
    return slot
