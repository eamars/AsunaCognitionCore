"""Owner-local import of one artifact from an already configured integration endpoint.

Stdlib only on purpose. Every decision that the owner will be judged on — the
endpoint whitelist, "not an arbitrary URL downloader", the workspace write
boundary, the default no-overwrite rule, the size ceiling and the honest
failure mapping — is computed here, so the offline self-check can run this same
code with an injected fetch and a temporary workspace: no WSL, no Mongo, no
network. `integration.IntegrationRunner` only supplies the real fetch (one
managed namespace GET over a configured relay) and the real workspace.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

IMPORT_TOOL_NAME = 'import_integration_artifact'
# The managed namespace caps file size at 8 MiB (prlimit fsize); the tool caps
# lower so a fetched artifact can never fill the runtime storage by accident.
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_BYTES = 1 * 1024 * 1024
MAX_PATH_CHARS = 512

IMPORT_TOOL = {
    'name': IMPORT_TOOL_NAME,
    'description': ('Owner integration grant only. Read one artifact from an endpoint alias already configured in '
                    '/integration/config.json and write the bytes into this task workspace at target_relative_path. '
                    'endpoint is a configured alias, never a URL or host:port; artifact_path is a path on that '
                    'endpoint (plain HTTP/1.1 GET over the configured relay, redirects are reported, not followed). '
                    'Existing files are kept unless overwrite=true; max_bytes defaults to 1 MiB and is capped at '
                    '4 MiB. Returns the relative path, absolute path, byte count and SHA-256 actually written, or '
                    'the real failure: unknown endpoint, URL rejected, path outside the workspace, target exists, '
                    'over limit, HTTP status or transport error. When the bytes are actually a PNG/JPEG/WebP/GIF '
                    'image (file signature, not the name), the host additionally registers them as an image '
                    'artifact in this task\'s own scene scope and the result carries `artifact` metadata with the '
                    'host-recomputed sha256 and artifact_id, so a later turn can send that picture out; other '
                    'bytes are unaffected and the result is unchanged.'),
    'parameters': {'endpoint': {'type': 'string', 'required': True},
                   'artifact_path': {'type': 'string', 'required': True},
                   'target_relative_path': {'type': 'string', 'required': True},
                   'overwrite': {'type': 'boolean'},
                   'max_bytes': {'type': 'integer'}}}


def integration_gated(tool):
    """True when only the owner-local integration grant may run this tool.

    The name of this tool does not start with `integration_`, so the broker must
    ask one predicate instead of trusting the prefix.
    """
    return isinstance(tool, str) and (tool.startswith('integration_') or tool == IMPORT_TOOL_NAME)


_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def _error(reason, **detail):
    return {'error': reason, **detail}


def _blank(value):
    return not isinstance(value, str) or not value or bool(_CONTROL.search(value)) or len(value) > MAX_PATH_CHARS


def resolve_endpoint(endpoints, name):
    """Whitelist lookup by configured alias only; an address or URL is simply unknown."""
    configured = [entry.get('name') for entry in (endpoints or ()) if isinstance(entry, dict)]
    if _blank(name) or name not in configured:
        return None, _error('UNKNOWN_ENDPOINT', endpoint=name if isinstance(name, str) else None,
                            configured_endpoints=configured,
                            note='只能读 /integration/config.json 里已配置的端点别名；不接受 URL、主机或端口。')
    return next(entry for entry in endpoints if entry.get('name') == name), None


def validate_artifact_path(value):
    """A path on the endpoint, not a URL: this tool is not a general downloader."""
    if _blank(value):
        return None, _error('INVALID_ARTIFACT_PATH', artifact_path=value if isinstance(value, str) else None,
                            note='artifact_path 是非空字符串，最长 %d 字符，不能含控制字符。' % MAX_PATH_CHARS)
    if '://' in value or value.startswith('//'):
        return None, _error('ARTIFACT_PATH_IS_URL', artifact_path=value,
                            note='这里只接受端点内的路径；工具不会去取任意 URL。')
    if value.startswith('\\') or '\\' in value:
        return None, _error('INVALID_ARTIFACT_PATH', artifact_path=value, note='路径里不要用反斜杠。')
    if not value.startswith('/'):
        return None, _error('INVALID_ARTIFACT_PATH', artifact_path=value, note='artifact_path 必须以 / 开头。')
    if any(part == '..' for part in value.split('/')):
        return None, _error('INVALID_ARTIFACT_PATH', artifact_path=value, note='端点路径里不允许 ..。')
    return value, None


def validate_target_path(value):
    """Relative, plain, no traversal: the write stays inside this task workspace."""
    if _blank(value):
        return None, _error('INVALID_TARGET_PATH', target_relative_path=value if isinstance(value, str) else None,
                            note='target_relative_path 是任务工作区内的相对路径。')
    if '\\' in value:
        return None, _error('INVALID_TARGET_PATH', target_relative_path=value, note='用 / 分隔目录。')
    if value.startswith('/') or re.match(r'^[A-Za-z]:', value):
        return None, _error('TARGET_PATH_MUST_BE_RELATIVE', target_relative_path=value,
                            note='只能写进本次任务工作区，不接受绝对路径或盘符。')
    if any(part in ('', '.', '..') for part in value.split('/')):
        return None, _error('INVALID_TARGET_PATH', target_relative_path=value,
                            note='不允许空段、. 与 ..（含结尾多余的 /）。')
    return value, None


def resolve_target(workspace, relative, protected=()):
    """Resolve inside the granted workspace; symlinks and protected inputs cannot be escaped."""
    root = Path(workspace).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        return None, _error('TARGET_PATH_OUTSIDE_WORKSPACE', target_relative_path=relative,
                            note='解析后的目标不在本次任务工作区里（可能是符号链接指向外面）。')
    for path in protected or ():
        path = Path(path).resolve()
        if target == path or target.is_relative_to(path):
            return None, _error('TARGET_PATH_PROTECTED', target_relative_path=relative,
                                note='那是任务里只读的输入文件，不能覆盖。')
    return target, None


def classify_fetch(result, limit, *, endpoint, artifact_path):
    """Map what the transport actually saw to an honest reason, or None to write."""
    where = {'endpoint': endpoint, 'artifact_path': artifact_path}
    if not isinstance(result, dict):
        return _error('ARTIFACT_TRANSPORT_FAILED', detail='fetch 没有返回任何结果', **where)
    if result.get('transport_error'):
        return _error('ARTIFACT_TRANSPORT_FAILED', detail=str(result['transport_error'])[:400], **where)
    status = result.get('status')
    if type(status) is not int:
        return _error('ARTIFACT_TRANSPORT_FAILED', detail='没有拿到 HTTP 状态', **where)
    if status != 200:
        failure = _error('ARTIFACT_HTTP_STATUS', http_status=status, bytes_read=len(result.get('body') or b''),
                         note='端点返回的不是 200；状态如实透传，重定向不自动跟随。', **where)
        if result.get('location'):
            failure['location'] = str(result['location'])[:300]
        return failure
    declared = result.get('declared')
    if type(declared) is int and declared > limit:
        return _error('ARTIFACT_TOO_LARGE', declared_bytes=declared, max_bytes=limit,
                      note='端点声明的大小就超过上限，字节没有全部读回。', **where)
    body = result.get('body')
    if not isinstance(body, (bytes, bytearray)):
        return _error('ARTIFACT_TRANSPORT_FAILED', detail='响应体不是字节', **where)
    if len(body) > limit:
        return _error('ARTIFACT_TOO_LARGE', bytes_read=len(body), max_bytes=limit,
                      note='实际读回的字节数超过上限（可能没有 Content-Length）。', **where)
    return None


def import_artifact(args, *, endpoints, workspace, fetch, protected=(), register=None):
    """One artifact, configured endpoint only, written by the platform into the task workspace.

    ``register(data, meta)`` is an optional host-side hook called after a successful write, with the
    bytes actually written. It decides whether they are worth registering (an image, in practice) and
    returns a dict to report under ``artifact``, or ``None`` when there is nothing to report — a
    non-image import then returns exactly what it returned before this hook existed. A raising or
    failing hook never turns a completed import into a failure: the reason is reported honestly.
    """
    if not isinstance(args, dict):
        return _error('INVALID_IMPORT_ARGUMENTS')
    endpoint, failure = resolve_endpoint(endpoints, args.get('endpoint'))
    if failure:
        return failure
    path, failure = validate_artifact_path(args.get('artifact_path'))
    if failure:
        return failure
    relative, failure = validate_target_path(args.get('target_relative_path'))
    if failure:
        return failure
    limit = args.get('max_bytes', DEFAULT_MAX_BYTES)
    if type(limit) is not int or not 1 <= limit <= MAX_ARTIFACT_BYTES:
        return _error('INVALID_MAX_BYTES', max_bytes=limit if type(limit) is int else None,
                      max_allowed=MAX_ARTIFACT_BYTES, default=DEFAULT_MAX_BYTES)
    overwrite = args.get('overwrite', False)
    if not isinstance(overwrite, bool):
        return _error('INVALID_OVERWRITE', overwrite=str(overwrite)[:40])
    target, failure = resolve_target(workspace, relative, protected)
    if failure:
        return failure
    if target.is_dir():
        return _error('TARGET_IS_DIRECTORY', target_relative_path=relative)
    existed = target.exists()
    if existed and not overwrite:
        return _error('TARGET_EXISTS', target_relative_path=relative, existing_bytes=target.stat().st_size,
                      note='默认不覆盖；确认要换掉才传 overwrite=true。')
    result = fetch(endpoint, path, limit)
    failure = classify_fetch(result, limit, endpoint=endpoint.get('name'), artifact_path=path)
    if failure:
        return failure
    body = bytes(result.get('body') or b'')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('wb' if overwrite else 'xb') as handle:
            handle.write(body)
    except FileExistsError:
        return _error('TARGET_EXISTS', target_relative_path=relative,
                      note='写入时目标已经存在（默认不覆盖）。')
    except OSError as exc:
        return _error('TARGET_WRITE_FAILED', target_relative_path=relative,
                      detail=(type(exc).__name__ + ': ' + str(exc))[:300])
    value = {'imported': True, 'endpoint': endpoint.get('name'), 'artifact_path': path,
             'target_relative_path': relative, 'target_path': str(target), 'bytes': len(body),
             'sha256': hashlib.sha256(body).hexdigest(), 'http_status': result.get('status'),
             'content_type': result.get('content_type'), 'max_bytes': limit,
             'overwritten': bool(existed and overwrite)}
    if register is not None:
        # 登记只看真写进工作区的字节；它失败不能把一次成功的导入判成失败，原因如实带在 artifact 里。
        try:
            outcome = register(body, {'endpoint': endpoint.get('name'), 'artifact_path': path,
                                      'target_relative_path': relative})
        except Exception as exc:
            outcome = {'registered': False, 'reason': (type(exc).__name__ + ': ' + str(exc))[:120]}
        if isinstance(outcome, dict) and outcome:
            value['artifact'] = outcome
    return value
