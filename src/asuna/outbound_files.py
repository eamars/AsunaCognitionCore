"""Files she sends to a group through the outbox (ADR-092): registered from a task's folder, offered to her turn, sent
as speak's `file` part, read by the adapter in pieces, their bytes kept 7 days after they were last sent.

- **Registration** (`register`, the action brain's `offer_file`): a file inside the task folder becomes a `file`
  artifact in the task's own scope. The bytes stream into GridFS (`BlobStore.put_stream`); the program computes the
  sha256, the size and the type (`sniff`, from the first bytes: an unknown type is recorded as unknown and still
  goes). Her name for it passes her private words list: a hit warns, by category and entry line, and does not block.
- **What a conversation may send** (`offer`, `file_artifacts_from_program`): a file any of her tasks registered may be
  sent where the channel declares `file`, as her own pictures go anywhere (ADR-066: home outward is her call). Files
  go to groups only (v0).
- **Sending** (`check`): the part names a listed file whose bytes are still stored and whose size is within the
  limit the adapter declared (`capabilities.limit`); the program sets no size or type limit of its own. A file is its
  own message: her record line is 「[文件：名字，大小]」 (「类型没认出来」 added when its type was not recognized) and
  the row carries the `file` descriptor.
- **Bytes** (`serve_piece`): the adapter reads a claimed file in pieces of at most `PIECE_MAX`, fenced by its
  publication, attempt and artifact; it checks the whole file's sha256 itself.
- **Retention**: the bytes are removed `KEEP_DAYS` after the file was last sent, or after it was registered when it
  never was (`media_life.sweep`); the artifact row stays, with when its bytes went. A file named after that fails
  in words that say so.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from .state import Denied, now

KIND = 'file'                      # the artifacts row's kind, and the claim's and the row's field
CAPABILITY = 'file'                # what an adapter declares on its claim, with its platform's limit: file:<bytes>
SOURCE = 'task-file:'              # the source id prefix of a file a task registered (media_life.POLICY)
KEEP_DAYS = 7
PIECE_MAX = 8 * 1024 * 1024        # the largest piece the byte endpoint serves at once
MAX_OFFERED = 8
HEAD_BYTES = 64 * 1024             # what the type is read from
NAME_BYTES = 255                   # a file name, in UTF-8 bytes, as file systems take it
REMOVED = 'removed'                # the artifacts row's storage once its bytes are gone
UNKNOWN_TYPE = '类型没认出来'
FAILED_CODES = ('CHANNEL_DOES_NOT_DECLARE_FILE', 'FILE_OVER_CHANNEL_LIMIT', 'FILE_BYTES_EXPIRED',
                'FILE_DESCRIPTOR_INVALID')

TYPE_WORDS = {
    'application/pdf': 'PDF 文档',
    'application/zip': 'ZIP 压缩包',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word 文档',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel 表格',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint 演示文稿',
    'application/epub+zip': 'EPUB 电子书',
    'application/gzip': 'gzip 压缩包',
    'application/x-7z-compressed': '7z 压缩包',
    'application/vnd.rar': 'RAR 压缩包',
    'image/png': 'PNG 图片', 'image/jpeg': 'JPEG 图片', 'image/gif': 'GIF 图片', 'image/webp': 'WebP 图片',
    'image/svg+xml': 'SVG 图',
    'audio/mpeg': 'MP3 音频', 'audio/mp4': 'M4A 音频', 'audio/ogg': 'Ogg 音频', 'audio/wav': 'WAV 音频',
    'video/mp4': 'MP4 视频',
    'text/plain': '文本', 'text/html': 'HTML 网页', 'application/json': 'JSON',
}
OOXML = ((b'word/', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
         (b'xl/', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
         (b'ppt/', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'))

REGISTERED_NOTE = ('交回去后，说话的那一半在能发文件的群里用 speak 的 file 发（artifact_id 照抄这个）；只发得进群。'
                   '字节留 %d 天，从最后一次发出算，没发过就从登记算；过期了从 /task 再登记一次。' % KEEP_DAYS)
OFFER_NOTE = ('你的任务登记过、这一回合能发进这个群的文件（新的在前）。发就用 speak 的 file，artifact_id 照抄，'
              '它不是文件路径也不是文件名；一个文件单独一条消息，进群文件。没列出的发不了：要发别的，先让任务用 offer_file 登记。')
NO_LIST = '这台机器上没有「别带出去」名单，名字没查'
LISTED = '名字里有「别带出去」名单上的词：%s。不拦，照样能发；要换名字，换个 name 再登记一次'
# A file named after its bytes went (her asks, 2026-10-23; ADR-092 D9): when, and whether the task folder still has
# the original unchanged.
EXPIRED = '这个文件的字节在%s过期了'
SOURCE_KEPT = '；原文件还在任务文件夹（%s），让任务重新登记一次就能发'
SOURCE_GONE = '，任务文件夹里的原文件也不在了（或已改动），要再发得重新做出来'


# ── reading a file ──────────────────────────────────────────────────
def sniff(head, whole=False):
    """The media type of a file from its first bytes (`whole`: they are the whole file); None when not recognized."""
    data = bytes(head or b'')
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    if data.startswith(b'PK\x03\x04') or data.startswith(b'PK\x05\x06'):
        if b'mimetypeapplication/epub+zip' in data[:100]:
            return 'application/epub+zip'
        if b'[Content_Types].xml' in data:
            for marker, media_type in OOXML:
                if marker in data:
                    return media_type
        return 'application/zip'
    from .outbound_media import sniff_media_type
    picture = sniff_media_type(data)
    if picture:
        return picture
    if data.startswith(b'\x1f\x8b'):
        return 'application/gzip'
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return 'application/x-7z-compressed'
    if data.startswith(b'Rar!\x1a\x07'):
        return 'application/vnd.rar'
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return 'audio/mp4' if data[8:12] == b'M4A ' else 'video/mp4'
    if data.startswith(b'OggS'):
        return 'audio/ogg'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data.startswith(b'ID3') or _mpeg_frame(data):
        return 'audio/mpeg'
    return _text_type(data, whole)


def _mpeg_frame(data):
    """An MPEG audio frame header: sync bits, a version and a layer that exist (layer 0 is AAC's), a bitrate and a
    sampling rate that exist."""
    if len(data) < 3 or data[0] != 0xFF or data[1] & 0xE0 != 0xE0:
        return False
    return (data[1] & 0x18 != 0x08 and data[1] & 0x06 != 0 and (data[2] >> 4) not in (0, 0xF)
            and (data[2] >> 2) & 0x03 != 0x03)


def _text_type(data, whole):
    """UTF-8 text, decoded from the sample (a character cut at its end is not an error): svg, html, json or plain."""
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    if not data or b'\x00' in data:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        if whole or exc.reason != 'unexpected end of data' or exc.start < len(data) - 3:
            return None
        try:
            text = data[:exc.start].decode('utf-8')
        except UnicodeDecodeError:
            return None
    lead = text.lstrip().lower()
    if lead.startswith('<') and '<svg' in lead[:4096]:
        return 'image/svg+xml'
    if lead.startswith('<!doctype html') or lead.startswith('<html'):
        return 'text/html'
    if lead[:1] in ('{', '['):
        if not whole:
            return 'application/json'
        try:
            json.loads(text)
            return 'application/json'
        except ValueError:
            return 'text/plain'
    return 'text/plain'


def size_words(size):
    """A size for reading: 820 字节, 12.3 KB, 4.5 MB, 1.25 GB."""
    size = int(size or 0)
    if size < 1024:
        return '%d 字节' % size
    if size < 1024 ** 2:
        return '%.1f KB' % (size / 1024)
    if size < 1024 ** 3:
        return '%.1f MB' % (size / 1024 ** 2)
    return '%.2f GB' % (size / 1024 ** 3)


def type_words(media_type):
    return TYPE_WORDS.get(media_type, media_type) if media_type else UNKNOWN_TYPE


def record_line(name, size, media_type=None):
    """Her own record of a file she sent: what her later turns read (D4: an unrecognized type is said, not hidden)."""
    return '[文件：%s，%s%s]' % (name, size_words(size), '' if media_type else '，' + UNKNOWN_TYPE)


def name_problem(name):
    """Why a file name cannot be one, in words; None when it can."""
    if not name:
        return '名字是空的'
    if name != name.strip():
        return '名字前后不能有空格'
    if '/' in name or '\\' in name or name in ('.', '..'):
        return '名字里不能有 / 或 \\，它是文件名，不是路径'
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return '名字里不能有换行或控制字符'
    if len(name.encode('utf-8')) > NAME_BYTES:
        return '名字有 %d 字节，文件名最多 %d 字节（UTF-8，一个汉字 3 字节）' % (len(name.encode('utf-8')), NAME_BYTES)
    return None


# ── registration (the action brain's offer_file) ────────────────────
OFFER_FILE_TOOL = {
    'name': 'offer_file',
    'description': ('Register a file inside /task as one your talking half may send to a group (speak file part): '
                    'the program stores its bytes and reads its size and type. name is what people will see '
                    '(default: the file name). The result gives the artifact_id to hand back.'),
    'parameters': {'path': {'type': 'string', 'required': True},
                   'name': {'type': 'string', 'description': 'the file name people see, e.g. 报告.pdf'}},
}


def register(store, task, root, args):
    """offer_file: register a file of this task's folder in the task's own scope (its binding, never a parameter).
    A refused or failed operation is a result she reads (TASK_OPERATION_FAILED with the reason)."""
    from .blobs import BlobStore
    from .tasks import workspace_reason
    root = Path(root).resolve()
    args = args or {}
    given = str(args.get('path', ''))[:200]
    try:
        scope = (task or {}).get('scope_key')
        if not isinstance(scope, str) or not scope:
            raise ValueError('FILE_SCOPE_MISSING: 这个任务没有绑定对话范围，登记不了；不是参数的问题，重试也一样：'
                             '文件留在 /task 里，在报告里写明')
        target = (root / str(args['path'])).resolve()
        if not target.is_relative_to(root):
            raise PermissionError('PATH_DENIED: path %r 在任务文件夹外；写 /task 里的相对路径，例如 notes.txt 或 '
                                  'out/result.json（不带 /task/ 前缀，不用 ..）' % given)
        if target.is_dir():
            raise IsADirectoryError(given)
        size = target.stat().st_size
        name = str(args.get('name') or target.name)
        problem = name_problem(name)
        if problem:
            raise ValueError('FILE_NAME_INVALID: %s；name 写人看到的文件名，例如 报告.pdf' % problem)
        if size == 0:
            raise ValueError('FILE_EMPTY: %s 是空文件（0 字节），对方收到也打不开；先把内容写进去再登记' % given)
        relative = target.relative_to(root).as_posix()
        with target.open('rb') as handle:
            head = handle.read(HEAD_BYTES)
            handle.seek(0)
            media_type = sniff(head, whole=size <= len(head))
            stored = BlobStore(store).put_stream(handle, scope, KIND, media_type=media_type,
                                                 source_ids=[(SOURCE + '%s:%s' % (task.get('_id'), relative))[:200]],
                                                 # where it came from (the row's sha256 is what it was then): a
                                                 # refusal after the bytes went says what is left there
                                                 fields={'name': name, 'task_id': task.get('_id'), 'source': {
                                                     'task_id': task.get('_id'), 'folder': str(root), 'path': relative}})
    except Exception as exc:
        return {'error': 'TASK_OPERATION_FAILED: ' + workspace_reason(exc, 'offer_file', given),
                'execution': {'exit_code': 1, 'stderr': traceback.format_exc(limit=1)}}
    out = {'registered': True, 'artifact_id': stored['artifact_id'], 'name': name, 'size': size_words(stored['size']),
           'bytes': stored['size'], 'type': type_words(media_type), 'note': REGISTERED_NOTE}
    out.update(name_check(name))
    return out


def name_check(name):
    """What her private words list says about a file name: a warning by category and entry line, never the word."""
    from . import private_words
    entries = private_words.load()
    if entries is None:
        return {'name_check': NO_LIST}
    hits = private_words.find(entries, name)
    if not hits:
        return {}
    return {'name_warning': LISTED % '、'.join('%s 类第 %d 条' % (category, line) for line, category in hits)}


# ── what a conversation may send ────────────────────────────────────
def produced(item):
    """A file one of her tasks registered."""
    return any(str(source).startswith(SOURCE) for source in (item or {}).get('source_ids') or ())


def removed(item):
    return (item or {}).get('storage') == REMOVED


def sends_here(store, scene):
    """Files go out here: a group (v0), whose kind lists the file part and whose adapter declares `file`."""
    from . import capabilities, channel_kinds, outbound_media
    scene = scene or {}
    return (CAPABILITY in channel_kinds.reply_parts(scene.get('_id'))
            and capabilities.carries(store, scene, CAPABILITY) and outbound_media.group_scene(store.config, scene))


def offer(store, scene, *, limit=MAX_OFFERED):
    """The block `file_artifacts_from_program`: the files her tasks registered whose bytes are still stored, newest
    first; None when there are none or files do not go out here."""
    if not sends_here(store, scene):
        return None
    cursor = store.db.artifacts.find({'kind': KIND, 'state': 'DONE', 'storage': 'gridfs'},
                                     {'name': 1, 'size': 1, 'media_type': 1, 'created_at': 1,
                                      'source_ids': 1}).sort('created_at', -1).limit(200)
    items = []
    for row in cursor:
        if not produced(row):
            continue
        items.append({'artifact_id': row['_id'], 'name': row.get('name'), 'size': size_words(row.get('size')),
                      'type': type_words(row.get('media_type')), 'registered_at': row.get('created_at')})
        if len(items) >= limit:
            break
    return {'items': items, 'note': OFFER_NOTE} if items else None


def source_present(item):
    """Whether the task folder still holds the file it was registered from, byte for byte (its size, then its sha256,
    read in pieces)."""
    import hashlib
    source = (item or {}).get('source') or {}
    if not source.get('folder') or not source.get('path'):
        return False
    try:
        root = Path(source['folder']).resolve()
        target = (root / source['path']).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size != item.get('size'):
            return False
        digest = hashlib.sha256()
        with target.open('rb') as handle:
            for piece in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(piece)
        return digest.hexdigest() == item.get('sha256')
    except OSError:
        return False


def expired_words(item, zone, present=None):
    """Why a file named after its bytes went cannot go: when, and whether its original is still in the task folder
    (her asks: never a generic failure)."""
    from . import local_time
    present = source_present(item) if present is None else present
    said = EXPIRED % local_time.stamp(item.get('bytes_removed_at'), zone)
    return said + (SOURCE_KEPT % ((item.get('source') or {}).get('path')) if present else SOURCE_GONE)


def descriptor(raw):
    """A row's or a claim's `file` descriptor, checked; None when its shape is wrong."""
    if not isinstance(raw, dict):
        return None
    artifact, digest, size, name = raw.get('artifact_id'), str(raw.get('sha256') or ''), raw.get('size'), raw.get('name')
    from .outbound_media import SHA256
    if not isinstance(artifact, str) or not 1 <= len(artifact) <= 200 or not SHA256.match(digest):
        return None
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or not isinstance(name, str) or not name:
        return None
    media_type = raw.get('media_type')
    return {'artifact_id': artifact, 'name': name, 'media_type': media_type if isinstance(media_type, str) else None,
            'sha256': digest, 'size': size}


def check(store, ep, scene, artifact_id):
    """(descriptor, None) for a file her speak part may send here, else (None, why in words)."""
    from . import capabilities, local_time
    item = store.db.artifacts.find_one({'_id': artifact_id, 'kind': KIND}) if artifact_id else None
    if item and removed(item):
        return None, expired_words(item, local_time.zone_of(store, (scene or {}).get('_id')))
    offered = ((ep.get('context') or {}).get('file_artifacts_from_program') or {}).get('items') or ()
    if artifact_id not in {row.get('artifact_id') for row in offered if isinstance(row, dict)}:
        return None, '不在 file_artifacts_from_program 里：artifact_id 照抄那里列出的'
    if not item or item.get('state') != 'DONE' or item.get('storage') != 'gridfs':
        return None, '这个文件已经不在了；换 file_artifacts_from_program 里别的'
    from bson import ObjectId
    if not store.db['artifact_blobs.files'].find_one({'_id': ObjectId(item['gridfs_id'])}, {'_id': 1}):
        return None, '这个文件的字节不在存储里了（不是你的错）；要再发就让任务从文件夹里重新登记'
    most = capabilities.limit(store, (scene or {}).get('channel_id'), CAPABILITY)
    if most is not None and item['size'] > most:
        return None, ('这个文件 %s（%d 字节），这里一个文件最多 %s（%d 字节），发不了'
                      % (size_words(item['size']), item['size'], size_words(most), most))
    return {'artifact_id': item['_id'], 'name': item.get('name') or item['_id'], 'media_type': item.get('media_type'),
            'sha256': item['sha256'], 'size': item['size']}, None


def part(meta):
    """The planned row of a file part: her record line, the descriptor, and how the receipt names it."""
    return {'kind': 'file', 'text': record_line(meta['name'], meta['size'], meta.get('media_type')),
            'fields': {KIND: dict(meta)},
            'shown': 'file「%s」%s' % (meta['name'], '' if meta.get('media_type') else '（%s）' % UNKNOWN_TYPE)}


# ── the claim and the bytes ─────────────────────────────────────────
def claim_failure(store, row, limits):
    """The fields a claimed file row fails with before anything is sent (failure, failure_detail), or None: its bytes
    gone, or over the limit the claiming adapter declared. Cheap: whether the original is still in the task folder
    is looked at afterwards, outside the effects lock (`expired_source`)."""
    meta = descriptor(row.get(KIND))
    if not meta:
        return {'failure': 'FILE_DESCRIPTOR_INVALID', 'failure_detail': '这条消息记的文件信息不完整（不是你的错），发不了'}
    item = store.db.artifacts.find_one({'_id': meta['artifact_id']})
    if not item or removed(item) or item.get('storage') != 'gridfs':
        return {'failure': 'FILE_BYTES_EXPIRED', 'failure_detail': '这个文件的字节已经不在存储里了'}
    most = (limits or {}).get(CAPABILITY)
    if most is not None and meta['size'] > most:
        return {'failure': 'FILE_OVER_CHANNEL_LIMIT', 'file_limit': {'bytes': meta['size'], 'limit': most},
                'failure_detail': ('文件 %s（%d 字节），这里一个文件最多 %s（%d 字节）'
                                   % (size_words(meta['size']), meta['size'], size_words(most), most))}
    return None


def expired_source(store, row_id):
    """After a claim failed a row with FILE_BYTES_EXPIRED, outside the effects lock: whether the task folder still
    holds the original (it is hashed), kept on the row as source_present with the words that say so."""
    from . import local_time
    row = store.db.messages.find_one({'_id': row_id}) or {}
    meta = descriptor(row.get(KIND))
    item = store.db.artifacts.find_one({'_id': meta['artifact_id']}) if meta else None
    present = bool(item) and source_present(item)
    if item and removed(item):
        words = expired_words(item, local_time.zone_of(store, row.get('scene_id')), present)
    else:
        words = '这个文件的字节不在存储里了' + (SOURCE_KEPT % (item.get('source') or {}).get('path') if present
                                             else SOURCE_GONE)
    store.db.messages.update_one({'_id': row_id}, {'$set': {'source_present': present, 'failure_detail': words}})
    return present


def _number(query, key):
    value = (query.get(key) or [''])[0]
    if not str(value).isdigit():
        raise ValueError('FILE_PIECE_INVALID: %s 要是非负整数，给的是 %r' % (key, str(value)[:40]))
    return int(value)


def serve_piece(store, row, query):
    """The byte endpoint for a claimed file row: `length` bytes from `offset` (at most PIECE_MAX), of the artifact
    this publication declared (its attempt is checked by the caller); any file her tasks registered may go."""
    from .blobs import BlobStore
    meta = descriptor((row or {}).get(KIND))
    if not meta:
        raise Denied('FILE_NOT_DECLARED')
    wanted = (query.get('artifact_id') or [''])[0]
    if wanted and wanted != meta['artifact_id']:
        raise Denied('ATTACHMENT_ARTIFACT_DENIED')
    offset, length = _number(query, 'offset'), _number(query, 'length')
    if not 0 < length <= PIECE_MAX:
        raise ValueError('FILE_PIECE_INVALID: length 要在 1..%d 之间，给的是 %d' % (PIECE_MAX, length))
    if offset >= meta['size']:
        raise ValueError('FILE_PIECE_INVALID: offset %d 不在文件里（文件 %d 字节）' % (offset, meta['size']))
    item = store.db.artifacts.find_one({'_id': meta['artifact_id']})
    if not item or item.get('kind') != KIND:
        raise Denied('FILE_ARTIFACT_UNAVAILABLE')
    if removed(item) or item.get('state') != 'DONE' or item.get('storage') != 'gridfs':
        raise Denied('FILE_BYTES_EXPIRED')
    if item.get('sha256') != meta['sha256'] or item.get('size') != meta['size']:
        raise Denied('FILE_SHA_MISMATCH')
    data = BlobStore(store).get_range(item['_id'], item['scope_key'], offset, length, operator=True)
    return data, 'application/octet-stream'


# ── after it was sent ───────────────────────────────────────────────
def sent(store, row):
    """A delivered file row: its bytes are kept KEEP_DAYS from now."""
    meta = descriptor((row or {}).get(KIND))
    if meta:
        store.db.artifacts.update_one({'_id': meta['artifact_id'], 'kind': KIND}, {'$set': {'last_sent_at': now()}})


# The adapter's reasons for a file it did not send, in her words (a code never reaches her).
ADAPTER_WORDS = {
    'file_private_target_not_supported': '文件只发得进群，私聊发不了',
    'file_empty': '文件是空的',
    'file_over_limit': '比这条腿能发的最大文件还大',
    'file_name_invalid': '文件名这条腿用不了',
    'file_fetch_unavailable': '适配器没取到文件的字节（不是你的错），可以再发一次',
    'file_fetch_short_piece': '适配器取到的字节不全（不是你的错），可以再发一次',
    'file_sha256_mismatch': '传过去的字节和登记的校验值对不上（不是你的错），可以再发一次',
    'file_stream_no_answer': '平台收文件时没回话，文件没进群；可以再发一次',
    'file_stream_refused': '平台没收下这个文件',
    'file_stream_incomplete': '平台没收全这个文件，文件没进群；可以再发一次',
    'file_upload_failed': '平台没把文件放进群',
    'ws_not_connected': '适配器和平台断开了，没发出去；等连上再发',
    'target_not_authorized': '这个群不在适配器能发的名单里',
}
ADAPTER_OTHER = '适配器没发出去（不是你的错）'


def failure_words(row):
    """Her words for a file row of hers that did not go: a mute as every line says it, else 没发出去 with the
    program's reason, the platform's own words, or the adapter's reason in words."""
    from . import own_mute
    from .context import UNDELIVERED_WORDS
    response = ((row.get('platform_receipt') or {}).get('response') or {})
    if response.get('reason') == own_mute.REASON:
        return own_mute.FAILED_WORDS
    if row.get('failure') in FAILED_CODES:
        why = {'CHANNEL_DOES_NOT_DECLARE_FILE': '这条腿发不了文件'}.get(row['failure']) or row.get('failure_detail')
    else:
        said = response.get('platform') or response.get('wording') or response.get('message')
        reason = str(response.get('reason') or '')
        why = ('平台说：%s' % ' '.join(str(said).split())[:120] if said
               else ADAPTER_WORDS.get(reason) or ('适配器没取到文件的字节（不是你的错）' if reason.startswith('file_fetch_')
                                                else ADAPTER_OTHER))
    return UNDELIVERED_WORDS['FAILED'] + ('：%s' % why if why else '')
