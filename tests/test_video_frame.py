"""ADR-120 landing 5 (D4), on the fixture world in memory (test_whose's home: the Web chat at home, g1 an outside group,
g2 a home group): read_image of a video with `at` gives that one frame, kept as a picture of this conversation. Only
what would fail silently and costly: the wrong frame, a frame kept in another conversation or twice, a frame cut from
another conversation's video outside, a moment past the end not said, and a frame kept or lost against its lifetime."""
import base64
import hashlib
import io

import pytest

from asuna import access, media_children, media_life, vision
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records
from asuna.store.words import Set
from test_own_files import PNG, a_line_with_a_picture, denied_rows, where
from test_whose import LOCAL, home  # noqa: F401  (home: a fixture)

COLOURS = ((220, 30, 30), (30, 200, 40), (40, 50, 220))      # one second each
OLD = '2026-01-01T00:00:00+00:00'


def a_video(fps=10):
    av = pytest.importorskip('av')
    from PIL import Image
    out = io.BytesIO()
    with av.open(out, mode='w', format='mp4') as container:
        stream = container.add_stream('mpeg4', rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
        for colour in COLOURS:
            for _ in range(fps):
                for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB', (64, 48), colour))):
                    container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return out.getvalue()


@pytest.fixture
def videos(home, monkeypatch):
    """The fixture world with links of example.invalid allowed, every pull answered with the coloured video, counted."""
    store = home
    store.config['vision'] = {'image_hosts': ['example.invalid']}
    data, pulls = a_video(), []

    def download(url, *args, **kwargs):
        pulls.append(url)
        return data, 'example.invalid', 'video/mp4'
    monkeypatch.setattr(vision, 'download', download)
    monkeypatch.setattr(media_children, 'VIDEO', None)        # cut in this process (no Host's video child here)
    return store, pulls


def a_video_line(store, scene_id, key):
    return a_line_with_a_picture(store, scene_id, key, item={'type': 'video', 'url': 'https://example.invalid/v.mp4',
                                                            'placeholder': '[视频]', 'file': 'v.mp4'})


def cut(store, scene_id, ref, at, origin, by=None):
    return vision.read_image_for_task(store, BlobStore(store), where(scene_id), store.config, {'ref': ref, 'at': at},
                                      origin=origin, by=by)


def frames(store):
    return [row for row in artifact_records.of_kind(store, 'image').rows()
            if str((row.get('source_ids') or [''])[0]).startswith(vision.FRAME_SOURCE)]


def test_a_frame_at_its_moment_is_kept_once_as_a_picture_of_this_conversation(videos):
    from PIL import Image
    store, pulls = videos
    ref = a_video_line(store, 'g1', 'v1')
    seen = cut(store, 'g1', ref, 1.5, 'outside')
    data = base64.b64decode(seen['image']['data'])
    image = Image.open(io.BytesIO(data))
    assert seen['media_type'] == 'image/jpeg' and image.size == (64, 48), 'the frame at its own size'
    assert all(abs(got - want) < 40 for got, want in zip(image.getpixel((32, 24)), COLOURS[1])), 'the frame at 1.5 s'
    row = artifact_records.get(store, seen['artifact_id'])
    assert row['kind'] == 'image' and row['scope_key'] == 'scene:g1' and row['source_ids'] == ['frame:%s:1500' % ref]
    assert row['sha256'] == seen['sha256'] == hashlib.sha256(data).hexdigest()
    # The same moment again reads that row back: no second copy, no second download.
    assert cut(store, 'g1', ref, 1.5, 'outside')['artifact_id'] == seen['artifact_id'] and len(pulls) == 1
    # Another moment is another frame; the video is pulled again for it (its bytes are never kept).
    assert cut(store, 'g1', ref, 2.5, 'outside')['artifact_id'] != seen['artifact_id'] and len(pulls) == 2
    # Home cutting the group's video keeps the frame in its own conversation, not in the group's.
    at_home = cut(store, LOCAL, ref, 1.5, 'home')
    assert artifact_records.get(store, at_home['artifact_id'])['scope_key'] == 'scene:' + LOCAL
    assert len(frames(store)) == 3


def test_a_moment_past_the_end_and_at_on_a_picture_are_answered_in_words(videos):
    store, pulls = videos
    ref = a_video_line(store, 'g1', 'v2')
    with pytest.raises(ValueError) as past:
        cut(store, 'g1', ref, 3.5, 'outside')
    assert str(past.value).startswith('VIDEO_FRAME_OUT_OF_RANGE: ') and '约 3 秒' in str(past.value)
    with pytest.raises(ValueError, match='^INVALID_READ_IMAGE_AT: '):
        cut(store, 'g1', ref, -1, 'outside')
    assert len(pulls) == 1, 'a negative moment is refused before the video is pulled'
    picture = a_line_with_a_picture(store, 'g1', 'p2')
    stored = BlobStore(store).put(PNG, 'scene:g1', 'image', media_type='image/png', source_ids=['in-x'])['artifact_id']
    for not_a_video in (picture, stored):
        with pytest.raises(ValueError) as caught:
            cut(store, 'g1', not_a_video, 1.0, 'outside')
        assert str(caught.value) == vision.AT_NOT_VIDEO
    assert len(pulls) == 1 and frames(store) == []


def test_outside_a_video_of_another_conversation_answers_as_a_missing_one(videos):
    store, pulls = videos
    theirs = a_video_line(store, 'g2', 'v3')
    by = {'turn': 'ep-outside', 'scope': 'scene:g1'}

    def refused(ref):
        with pytest.raises(ValueError) as caught:
            cut(store, 'g1', ref, 1.0, 'outside', by)
        return str(caught.value)
    assert refused(theirs).replace(theirs, '<ref>') == refused('att-ffffffffffff').replace('att-ffffffffffff', '<ref>')
    assert [row['resource'] for row in denied_rows(store)] == ['all_files']
    # Storing a frame is this conversation's own files: where the owner narrowed them, the table refuses the cut.
    store.config['access'] = {'own_files': 'home'}
    with pytest.raises(Exception) as narrowed:
        cut(store, LOCAL, theirs, 1.0, 'home_from_outside', {'task': 'task-x', 'scope': 'scene:' + LOCAL})
    assert str(narrowed.value) == access.refusal('home_from_outside', 'own_files')
    assert denied_rows(store)[-1]['resource'] == 'own_files'
    assert pulls == [] and frames(store) == []


def test_a_sent_frame_is_kept_and_an_unsent_one_goes_after_seven_days(videos):
    store, _ = videos
    ref = a_video_line(store, 'g1', 'v4')
    sent, unsent, fresh = (cut(store, 'g1', ref, at, 'outside')['artifact_id'] for at in (0.5, 1.5, 2.5))
    for old in (sent, unsent):
        store.collection('artifacts').update({'_id': old}, Set({'created_at': OLD}))
    store.put('messages', {'_id': 'out-v4', 'direction': 'outbound', 'scene_id': 'g1', 'delivery_state': 'DELIVERED',
                           'attachment': {'artifact_id': sent}})
    assert media_life.POLICY[vision.FRAME_SOURCE] == media_life.PULLED
    media_life.sweep(store)
    assert artifact_records.get(store, unsent) is None
    assert artifact_records.get(store, sent)['storage'] == artifact_records.get(store, fresh)['storage'] \
        == artifact_records.STORED
