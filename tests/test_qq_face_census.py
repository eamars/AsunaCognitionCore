"""ADR-103: the census of faces, stickers and clicks counts what the stored rows hold, in a window, for one channel
kind; a gate reads its numbers, so a wrong count is a wrong decision."""
import sys
from datetime import datetime, timedelta, timezone

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import qq_face_census as census          # noqa: E402

GROUP, OTHER_KIND = 'qq:10001:group:20001', 'dm-home'


def line(key, scene, text, items=None, notice=None, days=1, count=None):
    raw = {}
    if items is not None:
        raw['asuna_media'] = {'count': count or len(items), 'items': items}
    if notice:
        raw['asuna_notice'] = {'kind': notice}
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {'_id': key, 'schema_version': 1, 'scene_id': scene, 'scene_seq': 1, 'direction': 'inbound',
            'received_at': stamp, 'text': text, 'event': {'raw': raw}}


def face(name, number):
    return {'type': 'face', 'placeholder': '[表情:%s]' % name if name else '[表情]', 'face_id': number}


def test_the_census_counts_faces_stickers_unread_types_clicks_and_look_alikes_in_the_window(store):
    store.collection('scenes').insert([{'_id': GROUP, 'schema_version': 1, 'kind': 'group'},
                                       {'_id': OTHER_KIND, 'schema_version': 1, 'kind': 'dm'}])
    store.collection('messages').insert([
        line('a', GROUP, '笑死[表情:狗头]', [face('狗头', '277')]),
        line('b', GROUP, '[表情][表情:狗头]', [face(None, '999'), face('狗头', '277')]),
        line('c', GROUP, '[表情包:赞][表情包]', [{'type': 'image', 'sticker': 'custom', 'placeholder': '[表情包:赞]'},
                                          {'type': 'image', 'sticker': 'market', 'placeholder': '[表情包]'}]),
        line('d', GROUP, '[dice消息（未解析）]', [{'type': 'dice', 'placeholder': '[dice消息（未解析）]'}]),
        line('e', GROUP, '给你的那句点了一个表情', notice='reaction'),
        line('f', GROUP, '我打的 [表情:狗头] [表情包:臭]'),                      # typed: no media items behind them
        line('g', GROUP, '[表情:狗头]' * 9, [face('狗头', '277')] * 8, count=9),   # a block cut at 8: no look-alike count
        line('h', GROUP, '[表情:狗头]', [face('狗头', '277')], days=40),           # older than the window
        line('i', OTHER_KIND, '[表情:狗头]', [face('狗头', '277')])])             # another kind's conversation
    tally, kinds, _since, cut = census.read(store, 'qq', 30, 1000)
    report = tally.report()
    assert kinds == {'group': 1} and not cut and report['lines']['read'] == 7
    assert report['faces']['items'] == 11 and report['faces']['nameless'] == 1
    assert report['faces']['nameless_ids'] == [['999', 1]] and report['faces']['names'] == [['狗头', 10]]
    assert report['stickers'] == {'items': 2, 'custom': 1, 'market': 1, 'named': 1, 'unnamed': 1}
    assert report['unread_types'] == [['dice', 1]] and report['clicks']['lines'] == 1 and report['clicks']['unnamed_emoji'] == 1
    assert report['typed_lookalikes'] == {'face_shape': 1, 'sticker_shape': 1}
    assert report['lines']['truncated_blocks'] == 1
    _, _, _, cut = census.read(store, 'qq', 30, 3)
    assert cut, 'a read that hits the cap says so'
