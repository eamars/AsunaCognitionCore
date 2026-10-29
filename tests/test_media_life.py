"""Stored pictures live by their kind (media_life.POLICY); a video becomes its contact sheet when pulled and its bytes
are never stored."""
import io
import re

import pytest

from asuna import animated, media_life, vision
from asuna.config import ROOT


def a_video(seconds=3, fps=10, sound=False):
    av = pytest.importorskip('av')
    from PIL import Image
    out = io.BytesIO()
    with av.open(out, mode='w', format='mp4') as container:
        stream = container.add_stream('mpeg4', rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
        for i in range(seconds * fps):
            shade = int(255 * i / (seconds * fps))                 # the picture changes over time
            frame = av.VideoFrame.from_image(Image.new('RGB', (64, 48), (shade, 255 - shade, 80)))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return out.getvalue()


def test_a_video_becomes_one_labelled_sheet_with_words_that_say_there_is_no_sound():
    sheet, words = animated.video_snapshot(a_video())
    assert sheet.startswith(b'\x89PNG')
    assert words['kind'] == '视频快照' and '约 3 秒' in words['what'] and '没有声音轨' in words['what']
    assert '格子里没有声音' in words['note'] and words['cells'].startswith('图里是按时间均匀取的 9 个时刻')
    assert vision.sniff_video_type(a_video()) == 'video/mp4'


def test_a_video_that_cannot_be_split_says_why_and_gives_no_picture():
    sheet, words = animated.video_snapshot(b'\x00\x00\x00\x18ftypmp42 not really a video')
    assert sheet is None and words['error'].startswith('VIDEO_NOT_SPLIT')


def test_a_video_over_the_cap_is_refused_before_download_with_its_size():
    big = vision.VIDEO_MAX_BYTES + 1
    message = {'_id': 'in-ep-v', 'event': {'raw': {'asuna_media': {'count': 1, 'items': [
        {'type': 'video', 'placeholder': '[视频（未解析）]', 'file': 'a.mp4', 'size': str(big),
         'url': 'https://multimedia.nt.qq.com.cn/download?x=1'}]}}}}
    [entry] = vision.attachments_of(message, config={})
    assert entry['type'] == 'video' and not entry['pullable']
    assert '视频 32.0 MB，超过上限 32 MB，没下载' in entry['not_pullable_because']
    assert '%d MB' % vision.VIDEO_MAX_MB in vision.READ_IMAGE_TOOL['description']


def test_every_kind_of_stored_picture_names_its_life_cycle():
    """Each source prefix the code stores pictures under is in media_life.POLICY."""
    written = set()
    for path in (ROOT / 'src' / 'asuna').glob('*.py'):
        text = path.read_text(encoding='utf-8')
        written |= set(re.findall(r"^(?:POOL_SOURCE|SOURCE|PRODUCED_SOURCE|EDIT_SOURCE) = '([a-z-]+:)'", text, re.M))
    written |= {'file:', 'in-', 'local-upload:'}
    assert written and written <= set(media_life.POLICY), written - set(media_life.POLICY)


