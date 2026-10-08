"""render_svg (ADR-027): an SVG file in the task folder made into a PNG she can look at and send.

The Host renders it (resvg, packages/cognition-core/src/svg.js); this side reads the file, makes it safe to render
and keeps the result. resvg would load a picture an <image> names by an absolute path on this machine, so every
<image> or <feImage> whose link is not an embedded data: picture loses that link before rendering, and an SVG that
declares XML entities is refused. The PNG is written under images/ (never over a file) and registered as her own
picture (source integration:svg:<path>), like a drawn one: read_image takes its artifact_id, and it can be sent.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

RENDER_SVG_TOOL_NAME = 'render_svg'
MAX_SVG_BYTES = 2 * 1024 * 1024
MIN_WIDTH, MAX_WIDTH = 16, 2048
XLINK = '{http://www.w3.org/1999/xlink}href'
SVG_NS = 'http://www.w3.org/2000/svg'
AGAIN = '可以改了再渲染一次；还不行就写进报告'

RENDER_SVG_TOOL = {
    'name': RENDER_SVG_TOOL_NAME,
    'description': ('Render an SVG file from /task into a PNG picture: it is written under images/ and stored as your '
                    'own picture, so read_image can look at it (pass artifact.artifact_id) and it can be sent. '
                    'Pictures the SVG links to are not loaded (embed them as data: URIs); text uses the fonts '
                    'installed on the Host.'),
    'parameters': {
        'path': {'type': 'string', 'required': True, 'description': 'the .svg file, relative to /task'},
        'width': {'type': 'integer', 'description': f'output width in pixels ({MIN_WIDTH}–{MAX_WIDTH}); '
                                                    'default the SVG\'s own width, at most 2048'},
        'background': {'type': 'string', 'description': 'a CSS colour painted behind the picture, e.g. "white"; '
                                                       'default transparent'},
    },
}

_host = None


def attach(render):
    """The Host's renderer: render({svg, width, background}) -> {png (base64), width, height}."""
    global _host
    _host = render


def available():
    return _host is not None


def _error(reason, note, **detail):
    return {'rendered': False, 'error': reason, **detail, 'note': note}


def _source_path(workspace, value):
    if not isinstance(value, str) or not value.strip() or not value.lower().endswith('.svg'):
        return None, _error('INVALID_SVG_PATH', 'path 是 /task 里的一个 .svg 文件（相对路径）。', path=value)
    relative = value.strip().removeprefix('/task/').lstrip('/')
    root = Path(workspace).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        return None, _error('SVG_PATH_OUTSIDE_WORKSPACE', '只能渲染本次任务工作区里的文件。', path=value)
    if not target.is_file():
        return None, _error('SVG_NOT_FOUND', '工作区里没有这个文件；先用 write_file 写好 .svg。', path=value)
    return (target, relative), None


def safe_svg(text):
    """(svg, dropped links) or raises ValueError: links to pictures outside the file removed; no entity declarations."""
    if '<!ENTITY' in text:
        raise ValueError('SVG_DECLARES_ENTITIES')
    root = ET.fromstring(text)
    dropped = 0
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] not in ('image', 'feImage'):
            continue
        for key in ('href', XLINK):
            link = element.get(key)
            if link is not None and not link.strip().lower().startswith('data:'):
                del element.attrib[key]
                dropped += 1
    ET.register_namespace('', SVG_NS)
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    return ET.tostring(root, encoding='unicode'), dropped


def render(args, *, workspace, register=None, now=None):
    """One SVG from the task folder rendered to a PNG in it, registered as her picture."""
    if _host is None:
        return _error('SVG_RENDERER_UNAVAILABLE', '渲染服务这会儿没接上，不是参数的问题；' + AGAIN + '。')
    found, failure = _source_path(workspace, args.get('path'))
    if failure:
        return failure
    source, relative = found
    width = args.get('width')
    if width is not None and not (type(width) is int and MIN_WIDTH <= width <= MAX_WIDTH):
        return _error('INVALID_WIDTH', f'width 是 {MIN_WIDTH}–{MAX_WIDTH} 的整数像素，或者不给（用 SVG 自己的宽）。', width=width)
    background = args.get('background')
    if background is not None and not (isinstance(background, str) and 0 < len(background) <= 40):
        return _error('INVALID_BACKGROUND', 'background 是一个 CSS 颜色，比如 "white" 或 "#fff"。', background=background)
    data = source.read_bytes()
    if len(data) > MAX_SVG_BYTES:
        return _error('SVG_TOO_LARGE', 'SVG 超过 2 MiB；把内嵌的大图换小或拆开。', bytes=len(data))
    try:
        svg, dropped = safe_svg(data.decode('utf-8'))
    except UnicodeDecodeError:
        return _error('SVG_NOT_UTF8', 'SVG 要是 UTF-8 文本。')
    except ValueError as exc:
        if str(exc) == 'SVG_DECLARES_ENTITIES':
            return _error('SVG_DECLARES_ENTITIES', 'SVG 里不能声明 XML 实体（<!ENTITY>）；去掉再渲染。')
        return _error('SVG_NOT_PARSED', 'SVG 不是格式正确的 XML：' + str(exc)[:160] + '；改好再渲染。')
    except ET.ParseError as exc:
        return _error('SVG_NOT_PARSED', 'SVG 不是格式正确的 XML：' + str(exc)[:160] + '；改好再渲染。')
    try:
        reply = _host({'svg': svg, **({'width': width} if width else {}), **({'background': background} if background else {})})
    except Exception as exc:
        return _error('SVG_RENDER_FAILED', '渲染没成功：' + str(exc)[:200] + '；' + AGAIN + '。')
    body = base64.b64decode(reply['png'])
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%d-%H%M%S')
    target_relative = 'images/%s-%s-%s.png' % (Path(relative).stem[:40], stamp, hashlib.sha256(body).hexdigest()[:8])
    target = Path(workspace).resolve() / target_relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write(body)
    except OSError as exc:
        return _error('PNG_WRITE_FAILED', '图没写进工作区，不是参数的问题；' + AGAIN + '。',
                      detail=(type(exc).__name__ + ': ' + (exc.strerror or str(exc)))[:200])
    value = {'rendered': True, 'svg': relative, 'target_relative_path': target_relative, 'width': reply.get('width'),
             'height': reply.get('height'), 'bytes': len(body), 'media_type': 'image/png'}
    if dropped:
        value['links_dropped'] = dropped
        value['links_note'] = '有 %d 处指向外部图片的链接没有加载（只认 data: 内嵌图）。' % dropped
    if register is not None:
        try:
            outcome = register(body, {'endpoint': 'svg', 'artifact_path': relative})
        except Exception as exc:
            outcome = {'registered': False, 'reason': (type(exc).__name__ + ': ' + str(exc))[:120]}
        if isinstance(outcome, dict) and outcome:
            value['artifact'] = outcome
    value['note'] = ('渲染结果还没人看过：先用 read_image 传 artifact.artifact_id 亲眼看一遍，不对就改 SVG 再渲染。'
                     'artifact_id 是可以随消息发出去的那张。')
    return value
