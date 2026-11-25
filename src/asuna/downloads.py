"""web_fetch's save (ADR-120 D2): an address's bytes into the task's folder and its conversation's own files.

The plugin fetches the bytes on the one network line (fetch.js `SlimFetch.download`: the task's network, the public-only
check where its origin may not reach the owner's own network, any content type, at most `MAX_BYTES`, a body over it
refused and nothing kept) and hands them over with the call (`ToolBroker.call`'s `body`, base64 in the one worker line,
never in the call's record). The access table decides first: `save` needs `own_files` besides the network
(`tasks.needs`). Here the bytes are written and registered:

- **The file**: `/task/downloads/<name>`, the name `save` gives, else the address's last part, made safe as a received
  file's copy is (`received_files.safe_name`), with the extension of its type when it has none; never over another
  file: a second one of that name gets ` (2)`. It is a file of the task's folder like any other.
- **The record**: a row of the task's own conversation (its binding's scope), its type read from the bytes
  (`outbound_files.sniff`), source `download:<task>:downloads/<name>`, kept as a task file is (media_life.POLICY). A
  picture (PNG, JPEG, WebP, GIF within the 8 MiB a picture goes out at) goes through the picture registration
  (`outbound_media.register_imported_image`), anything else is a `file` row with its name, as offer_file registers one.
  Neither is on a list yet: offer_file by its id puts it there; read_image or received_file reads it by its id.
- **What she reads**: 「存好了：…」 with its id, its /task path and the sha256 of the bytes as they were fetched.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import outbound_files, outbound_media
from .blobs import BlobStore

SOURCE = 'download:'               # the source id prefix of a saved address (media_life.POLICY)
FOLDER = 'downloads'               # /task/downloads/
MAX_BYTES = 20 * 1024 * 1024       # §11: at most 20 MB; fetch.js SAVE_MAX_BYTES refuses a body over it
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp',
              'application/pdf': 'pdf', 'application/zip': 'zip', 'application/json': 'json', 'text/plain': 'txt',
              'text/html': 'html', 'image/svg+xml': 'svg', 'video/mp4': 'mp4', 'audio/mpeg': 'mp3'}
# Her words (§9, her 0668): the name, the size, the type, the conversation it belongs to.
SAVED = '存好了：%s（%s，%s，记在%s）'
NOTES = {'image': '要发就用 offer_file，artifact_id 写这个；要看就用 read_image，ref 写这个 id。',
         'file': '要发就用 offer_file，artifact_id 写这个；要读就用 received_file，ref 写这个 id，或读 path 那个文件。'}


def saves(args):
    """Whether a web_fetch call saves what it fetches: `save` is a file name (blank: the address's own) or true."""
    save = (args or {}).get('save')
    return save is True or isinstance(save, str)


def saved(item):
    """A row web_fetch saved."""
    return any(str(source).startswith(SOURCE) for source in (item or {}).get('source_ids') or ())


def name_for(save, url, media_type):
    """The file name: `save`'s when it gives one, else the address's last part, made safe, with the extension of its
    type when it has none."""
    from .received_files import safe_name
    given = save.strip() if isinstance(save, str) else ''
    name = safe_name(given or unquote(urlsplit(str(url or '')).path.rsplit('/', 1)[-1]))
    extension = EXTENSIONS.get(media_type)
    return safe_name('%s.%s' % (name, extension)) if extension and '.' not in name else name


def _create(folder, name):
    """A new file in `folder` named `name`, or `name (2)`, `name (3)`… when one exists: (its path, open for writing).
    Never over another file, a save running beside this one included."""
    stem, dot, extension = name.rpartition('.')
    number = 1
    while True:
        candidate = name if number == 1 else '%s (%d)%s' % (stem if dot else name, number,
                                                            dot + extension if dot else '')
        try:
            return folder / candidate, open(folder / candidate, 'xb')
        except FileExistsError:
            number += 1


def save(store, task, task_dir, args, body):
    """web_fetch with `save`: the fetched bytes (`body`: the plugin's {url, status, content_type, data (base64)}) written
    to /task/downloads/ and registered in the task's own conversation. Raises a coded error for a body that is not one
    (the plugin's fault: it refuses too large or empty bodies itself)."""
    scope = (task or {}).get('scope_key')
    if not isinstance(scope, str) or not scope:
        raise ValueError('FILE_SCOPE_MISSING: 这个任务没有绑定对话范围，存不进这个对话的文件；不是参数的问题，重试也一样')
    body = body if isinstance(body, dict) else {}
    try:
        data = base64.b64decode(body.get('data') or '', validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValueError('WEB_SAVE_BODY_INVALID: 取回来的字节交接时坏了（%s）；是程序的错，不是参数的问题'
                         % type(exc).__name__) from exc
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('WEB_SAVE_BODY_INVALID: 取回来的是 %d 字节，要在 1..%d 之间；是程序的错，不是参数的问题'
                         % (len(data), MAX_BYTES))
    media_type = outbound_files.sniff(data[:outbound_files.HEAD_BYTES], whole=len(data) <= outbound_files.HEAD_BYTES)
    root = Path(task_dir).resolve()
    folder = root / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    target, handle = _create(folder, name_for(args.get('save'), body.get('url') or args.get('url'), media_type))
    try:
        with handle:
            handle.write(data)
        relative = '%s/%s' % (FOLDER, target.name)
        fields = {'name': target.name, 'task_id': task['_id'],
                  'source': {'task_id': task['_id'], 'folder': str(root), 'path': relative}}
        artifact_id, kind = _register(store, scope, data, media_type, fields,
                                      (SOURCE + '%s:%s' % (task['_id'], relative))[:200])
    except BaseException:
        target.unlink(missing_ok=True)          # nothing kept when it could not be recorded
        raise
    out = {'saved': SAVED % (target.name, outbound_files.size_words(len(data)), outbound_files.type_words(media_type),
                             _where(store, task)),
           'artifact_id': artifact_id, 'path': '/task/' + relative, 'sha256': hashlib.sha256(data).hexdigest(),
           'note': NOTES[kind]}
    if kind == outbound_files.KIND:
        out.update(outbound_files.name_check(target.name))
    return out


def _register(store, scope, data, media_type, fields, source):
    """(artifact id, kind) of the saved bytes in `scope`: a picture through the picture registration, anything else
    (a picture over what goes out as one included) a file row."""
    if media_type in outbound_media.MEDIA_TYPES:
        made = outbound_media.register_imported_image(store, scope, data, source=source, fields=fields) or {}
        if made.get('registered'):
            return made['artifact_id'], outbound_media.ATTACHMENT_KIND
        if made.get('reason') != 'ATTACHMENT_OVER_LIMIT':
            raise ValueError('WEB_SAVE_NOT_STORED: 存储没收下（%s）；不是参数的问题' % made.get('reason'))
    stored = BlobStore(store).put(data, scope, outbound_files.KIND, media_type=media_type, source_ids=[source],
                                  fields=fields)
    return stored['artifact_id'], outbound_files.KIND


def _where(store, task):
    """The task's conversation as she reads it (People.scene_title)."""
    from .people import People
    from .records import scenes as scene_records
    scene = scene_records.get(store, task['scene_id']) or {'_id': task['scene_id']}
    return People(store, (store.config.get('chat') or {}).get('persona')).scene_title(scene)
