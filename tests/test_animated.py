"""Animated pictures (owner 2026-10-08): a still-image model gets a contact sheet of frames taken at even moments
across one loop, and words saying what the sheet is and what it cannot show."""
import base64
import io

from PIL import Image

from asuna import animated
from asuna.blobs import BlobStore
from asuna.vision import local_uploads, media_note, read_image_for_task
from test_local_images import world

RED, BLUE, GREEN, BLACK, WHITE = (220, 30, 30), (30, 30, 220), (30, 200, 30), (0, 0, 0), (255, 255, 255)


def gif(frames, loop=0):
    """frames: [(rgb, ms)]."""
    images = [Image.new('RGB', (40, 30), colour) for colour, _ in frames]
    out = io.BytesIO()
    extra = {} if loop is None else {'loop': loop}
    images[0].save(out, format='GIF', save_all=True, append_images=images[1:], duration=[ms for _, ms in frames],
                   disposal=1, **extra)
    return out.getvalue()


def sheet(png):
    image = Image.open(io.BytesIO(png))
    assert image.format == 'PNG' and getattr(image, 'n_frames', 1) == 1
    return image


def test_a_held_frame_fills_the_moments_and_the_words_say_so():
    png, words = animated.snapshot(gif([(RED, 100), (BLUE, 40000)]))
    sheet(png)
    assert words['kind'] == '动图快照' and words['what'] == '共 2 帧，播一遍约 40.1 秒，一直循环'
    assert words['cells'].startswith('图里是按时间均匀取的 9 个时刻') and '共 2 格' in words['cells']
    assert words['hold'] == '大部分时间（约 40 秒）停在第 2 格的画面' and '不是动画本身' in words['note']


def test_a_blink_between_moments_is_named_as_left_out():
    _, words = animated.snapshot(gif([(BLACK, 1000), (WHITE, 20), (BLACK, 1000)], loop=None))
    assert words['what'].endswith('只播一遍') and '明显不同' in words['missed']
    _, calm = animated.snapshot(gif([(RED, 500), (BLUE, 500), (GREEN, 500)]))
    assert calm['missed'] == '没截到的帧都跟相邻的格子差不多' and calm['flicker'] == '没有快速来回切换的段落'


def test_fast_back_and_forth_is_named_as_flicker():
    _, words = animated.snapshot(gif([(RED, 20), (BLUE, 20)] * 4 + [(GREEN, 2000)]))
    assert words['flicker'].startswith('有 1 段快速来回切换') and '两层叠在一起' in words['flicker']


def test_a_gif_delay_under_20_ms_plays_as_100_ms():
    _, words = animated.snapshot(gif([(RED, 0), (BLUE, 10)]))
    assert words['what'].startswith('共 2 帧，播一遍约 0.2 秒')


def test_a_still_picture_passes_unchanged_and_a_huge_one_says_only_its_first_frame_goes(monkeypatch):
    still = gif([(RED, 100)])
    assert animated.snapshot(still) is None
    assert animated.seen(still, 'image/gif') == ({'media_type': 'image/gif', 'data': base64.b64encode(still).decode()}, None)
    monkeypatch.setattr(animated, 'MAX_FRAMES', 2)
    moving = gif([(RED, 100), (BLUE, 100), (GREEN, 100)])
    image, words = animated.seen(moving, 'image/gif')
    assert base64.b64decode(image['data']) == moving and words['error'].startswith('ANIMATION_NOT_SPLIT: 这张动图太大（3 帧')


def test_read_image_gives_the_model_the_sheet_and_keeps_the_original(store, tmp_path):
    scene, chat = world(store, tmp_path)
    data = gif([(RED, 300), (BLUE, 300), (GREEN, 300)])
    media = local_uploads(store, scene['scope_key'], [{'data': base64.b64encode(data).decode(), 'name': 'a.gif'}], 'm1')
    chat.submit('看', event_id='m1', native_session_id='s-local', native_message_ids=['m1'], media=media)
    ref = media_note(store.db.messages.find_one({'event.event_id': 'm1'}), store.config)['items'][0]['ref']
    task = {'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    result = read_image_for_task(store, BlobStore(store), task, store.config, {'ref': ref})
    assert result['media_type'] == 'image/gif' and result['image']['media_type'] == 'image/png'
    assert sheet(base64.b64decode(result['image']['data'])).width > 40 and result['animated']['what'].startswith('共 3 帧')
    again = read_image_for_task(store, BlobStore(store), task, store.config, {'ref': media['items'][0]['artifact_id']})
    assert again['image']['media_type'] == 'image/png' and 'animated' in again
    assert BlobStore(store).get(media['items'][0]['artifact_id'], scene['scope_key'], operator=True) == data
