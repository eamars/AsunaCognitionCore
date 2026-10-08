"""render_svg (ADR-027): an SVG in the task folder becomes her own PNG; pictures it links to outside itself are
never loaded, and nothing outside the task folder is read."""
import base64

import pytest

from asuna import svg_render

PNG = base64.b64decode('iVBORw0KGBoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


@pytest.fixture
def host():
    asked = []
    svg_render.attach(lambda args: asked.append(args) or {'png': base64.b64encode(PNG).decode(), 'width': 1, 'height': 1})
    yield asked
    svg_render.attach(None)


def test_an_svg_becomes_her_picture(tmp_path, host):
    (tmp_path / 'pelican.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                                          '<circle cx="5" cy="5" r="4" fill="#fa0"/></svg>', encoding='utf-8')
    registered = []
    result = svg_render.render({'path': 'pelican.svg', 'width': 400, 'background': 'white'}, workspace=tmp_path,
                               register=lambda body, meta: registered.append((body, meta)) or {'registered': True, 'artifact_id': 'blob-1'})
    assert result['rendered'] and result['artifact']['artifact_id'] == 'blob-1'
    assert (tmp_path / result['target_relative_path']).read_bytes() == PNG
    assert result['target_relative_path'].startswith('images/pelican-') and 'links_dropped' not in result
    assert registered == [(PNG, {'endpoint': 'svg', 'artifact_path': 'pelican.svg'})], 'source integration:svg:<path>, hers'
    assert host[0]['width'] == 400 and host[0]['background'] == 'white' and '<circle' in host[0]['svg']


def test_links_to_pictures_outside_the_svg_are_dropped_and_said(tmp_path, host):
    (tmp_path / 'a.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10">'
        '<image href="C:/Users/someone/secret.png" width="10" height="10"/>'
        '<image xlink:href="/etc/hosts.png" width="10" height="10"/>'
        '<image href="data:image/png;base64,AAAA" width="1" height="1"/>'
        '<filter id="f"><feImage href="https://example.com/x.png"/></filter></svg>', encoding='utf-8')
    result = svg_render.render({'path': '/task/a.svg'}, workspace=tmp_path)
    sent = host[0]['svg']
    assert 'secret.png' not in sent and 'hosts.png' not in sent and 'example.com' not in sent
    assert 'data:image/png;base64,AAAA' in sent
    assert result['links_dropped'] == 3


def test_refusals_say_what_to_do(tmp_path, host):
    (tmp_path / 'e.svg').write_text('<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
                                    encoding='utf-8')
    (tmp_path / 'bad.svg').write_text('<svg><g></svg>', encoding='utf-8')
    (tmp_path / 'ok.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>', encoding='utf-8')
    assert svg_render.render({'path': 'e.svg'}, workspace=tmp_path)['error'] == 'SVG_DECLARES_ENTITIES'
    assert svg_render.render({'path': 'bad.svg'}, workspace=tmp_path)['error'] == 'SVG_NOT_PARSED'
    assert svg_render.render({'path': 'missing.svg'}, workspace=tmp_path)['error'] == 'SVG_NOT_FOUND'
    assert svg_render.render({'path': 'ok.png'}, workspace=tmp_path)['error'] == 'INVALID_SVG_PATH'
    assert svg_render.render({'path': '../outside.svg'}, workspace=tmp_path)['error'] == 'SVG_PATH_OUTSIDE_WORKSPACE'
    assert svg_render.render({'path': 'ok.svg', 'width': 5000}, workspace=tmp_path)['error'] == 'INVALID_WIDTH'
    assert host == [], 'nothing reached the renderer'


def test_without_the_host_the_tool_is_not_offered_and_says_so(tmp_path):
    svg_render.attach(None)
    assert not svg_render.available()
    assert svg_render.render({'path': 'a.svg'}, workspace=tmp_path)['error'] == 'SVG_RENDERER_UNAVAILABLE'
