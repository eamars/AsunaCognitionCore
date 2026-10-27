"""Stored pictures live by their kind (media_life.POLICY); a video becomes its contact sheet when pulled and its bytes
are never stored."""
import io
import re
from datetime import datetime, timedelta, timezone

import pytest

from asuna import animated, media_life, vision
from asuna.blobs import BlobStore
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


def test_the_sweep_drops_old_pulled_copies_and_unlisted_candidates_and_keeps_the_rest(store):
    blobs = BlobStore(store)
    scope = store.db.scenes.find_one()['scope_key']
    put = lambda source: blobs.put(b'\x89PNG' + source.encode(), scope, 'image', source_ids=[source])['artifact_id']
    old_copy, new_copy, sent_copy = put('in-ep-old'), put('in-ep-new'), put('in-ep-sent')
    loose, listed, kept, made = put('sticker-pool:in-ep-a'), put('sticker-pool:in-ep-b'), put('sticker:in-ep-c'), \
        put('integration:image:x')
    long_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    store.db.artifacts.update_many({'_id': {'$ne': new_copy}}, {'$set': {'created_at': long_ago}})
    store.db.sticker_pool.insert_one({'_id': 'cand-b', 'schema_version': 1, 'artifact_id': listed})
    store.db.messages.insert_one({'_id': 'out-1', 'schema_version': 1, 'direction': 'outbound',
                                  'attachment': {'artifact_id': sent_copy}})
    removed = media_life.sweep(store)
    left = {row['_id'] for row in store.db.artifacts.find()}
    assert removed['pulled'] == 1 and removed['listed'] == 1 and removed['bytes'] > 0
    assert old_copy not in left and loose not in left
    assert {new_copy, sent_copy, listed, kept, made} <= left
    assert store.db['artifact_blobs.files'].count_documents({'filename': {'$in': [old_copy, loose]}}) == 0


def test_one_bad_row_is_counted_and_the_rows_after_it_still_go(store, monkeypatch):
    """A row the sweep cannot handle is counted as failed; it never stops the rows after it, so expired copies do not
    pile up behind one bad row (Xiaoman's review of ADR-102, 10-27). A size that is not a number is reported as 0."""
    blobs = BlobStore(store)
    scope = store.db.scenes.find_one()['scope_key']
    put = lambda source: blobs.put(b'\x89PNG' + source.encode(), scope, 'image', source_ids=[source])['artifact_id']
    first, bad, last, shelf = put('in-ep-1'), put('in-ep-2'), put('in-ep-3'), put('sticker:in-ep-k')
    long_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    store.db.artifacts.update_many({}, {'$set': {'created_at': long_ago}})
    store.db.artifacts.update_many({'_id': {'$in': [last, shelf]}}, {'$set': {'size': 'many'}})
    real = media_life.life

    def life(row):
        if row['_id'] == bad:
            raise ValueError('a row the sweep cannot read')
        return real(row)

    monkeypatch.setattr(media_life, 'life', life)
    removed = media_life.sweep(store)
    left = {row['_id'] for row in store.db.artifacts.find()}
    assert removed['failed'] == 1 and removed['pulled'] == 2
    assert bad in left and first not in left and last not in left and shelf in left
    assert removed['bytes'] == len(b'\x89PNGin-ep-1'), 'the size that is not a number counts 0; a kept row is not counted'


def test_a_time_that_cannot_be_read_is_kept_and_counted_never_old(store):
    """A row whose time is missing or not a time is kept and counted in `undated`: before, the missing time compared
    as '' and fell into the deleting branch (Xiaoman's check, 10-27). A stored Date compares as a moment, not as text."""
    blobs = BlobStore(store)
    scope = store.db.scenes.find_one()['scope_key']
    put = lambda source, kind='image': blobs.put(b'\x89PNG' + source.encode(), scope, kind,
                                                 source_ids=[source])['artifact_id']
    missing, not_a_time, old_date, new_date = put('in-ep-m'), put('in-ep-n'), put('in-ep-o'), put('in-ep-r')
    unsent = put('task-file:t:/task/a.txt', 'file')
    moment = datetime.now(timezone.utc)
    store.db.artifacts.update_many({'_id': {'$in': [missing, unsent]}}, {'$unset': {'created_at': ''}})
    store.db.artifacts.update_one({'_id': not_a_time}, {'$set': {'created_at': 'yesterday-ish'}})
    store.db.artifacts.update_one({'_id': old_date}, {'$set': {'created_at': moment - timedelta(days=8)}})
    store.db.artifacts.update_one({'_id': new_date}, {'$set': {'created_at': moment - timedelta(hours=1)}})
    removed = media_life.sweep(store, moment)
    left = {row['_id'] for row in store.db.artifacts.find()}
    assert {missing, not_a_time, new_date} <= left and old_date not in left
    assert store.db.artifacts.find_one({'_id': unsent})['storage'] == 'gridfs', 'a file with no time keeps its bytes'
    assert removed['undated'] == 3 and removed['pulled'] == 1 and removed['failed'] == 0


def test_a_time_without_an_offset_is_read_as_utc_not_as_undated(store):
    """A naive Date or a string with no offset is read as UTC, as the writers' state.now() gives it: an old one is swept,
    and it is never counted as undated (Xiaoman's check of e9cb565f)."""
    blobs = BlobStore(store)
    scope = store.db.scenes.find_one()['scope_key']
    put = lambda source: blobs.put(b'\x89PNG' + source.encode(), scope, 'image', source_ids=[source])['artifact_id']
    naive_date, naive_text, recent_text = put('in-ep-d'), put('in-ep-t'), put('in-ep-u')
    moment = datetime.now(timezone.utc)
    old = (moment - timedelta(days=8)).replace(tzinfo=None)
    store.db.artifacts.update_one({'_id': naive_date}, {'$set': {'created_at': old}})
    store.db.artifacts.update_one({'_id': naive_text}, {'$set': {'created_at': old.isoformat()}})
    store.db.artifacts.update_one({'_id': recent_text},
                                  {'$set': {'created_at': (moment - timedelta(hours=1)).replace(tzinfo=None).isoformat()}})
    removed = media_life.sweep(store, moment)
    left = {row['_id'] for row in store.db.artifacts.find()}
    assert naive_date not in left and naive_text not in left and recent_text in left
    assert removed['undated'] == 0 and removed['pulled'] == 2


def test_a_range_query_on_an_iso_string_never_matches_a_missing_or_date_time(store):
    """The other expiry queries (audit, vision, notices, crossing) compare in MongoDB against an ISO string. A row whose
    time is missing or stored as a Date is never matched by them, in either direction: it is not selected, never read
    as old. This pins the BSON type order those queries rely on (Xiaoman's reading, run here, not inferred)."""
    moment = datetime.now(timezone.utc)
    rows = [{'_id': 'missing', 'schema_version': 1},
            {'_id': 'date', 'schema_version': 1, 'created_at': moment - timedelta(days=30)},
            {'_id': 'text-old', 'schema_version': 1, 'created_at': (moment - timedelta(days=30)).isoformat()},
            {'_id': 'text-new', 'schema_version': 1, 'created_at': moment.isoformat()}]
    store.db.time_probe.insert_many(rows)
    try:
        cutoff = (moment - timedelta(days=7)).isoformat()
        older = {row['_id'] for row in store.db.time_probe.find({'created_at': {'$lt': cutoff}})}
        newer = {row['_id'] for row in store.db.time_probe.find({'created_at': {'$gte': cutoff}})}
        assert older == {'text-old'} and newer == {'text-new'}
    finally:
        store.db.time_probe.drop()


def test_within_one_day_times_compare_as_moments_never_as_text(store):
    """The cutoff falls at 06:00 of one day; rows of that day at 02:00 go and at 13:00 stay, each stored once as an ISO
    string and once as a Date. Compared as text, '... 13:00:00' sorts before '...T06:00:00' (a space before T) and the
    13:00 row would go (Xiaoman's check of 8d96a489: every earlier case was days apart and could not see it)."""
    blobs = BlobStore(store)
    scope = store.db.scenes.find_one()['scope_key']
    put = lambda source: blobs.put(b'\x89PNG' + source.encode(), scope, 'image', source_ids=[source])['artifact_id']
    day = datetime(2026, 10, 20, tzinfo=timezone.utc)
    early_text, late_text, early_date, late_date = put('in-ep-1a'), put('in-ep-1b'), put('in-ep-1c'), put('in-ep-1d')
    store.db.artifacts.update_one({'_id': early_text}, {'$set': {'created_at': (day + timedelta(hours=2)).isoformat()}})
    store.db.artifacts.update_one({'_id': late_text}, {'$set': {'created_at': (day + timedelta(hours=13)).isoformat()}})
    store.db.artifacts.update_one({'_id': early_date}, {'$set': {'created_at': day + timedelta(hours=2)}})
    store.db.artifacts.update_one({'_id': late_date}, {'$set': {'created_at': day + timedelta(hours=13)}})
    moment = day + timedelta(days=media_life.PULLED_DAYS, hours=6)
    removed = media_life.sweep(store, moment)
    left = {row['_id'] for row in store.db.artifacts.find()}
    assert early_text not in left and early_date not in left and late_text in left and late_date in left
    assert removed['pulled'] == 2 and removed['undated'] == 0


def test_a_sweep_is_recorded_when_anything_was_removed_failed_or_kept_undated(store):
    """The worker records `media.swept` by media_life.worth_recording: each count a real sweep returns is enough alone,
    bytes alone are not, and a sweep with nothing to report leaves no record."""
    quiet = media_life.sweep(store)
    assert not any(quiet.values()) and not media_life.worth_recording(quiet)
    assert set(media_life.RECORDED) == set(quiet) - {'bytes'}, 'every count the sweep returns is one that is recorded'
    for key in quiet:
        assert media_life.worth_recording(dict(quiet, **{key: 1})) == (key != 'bytes'), key
