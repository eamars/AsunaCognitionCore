"""ADR-016: QQ faces and her sticker shelf -- the adapter's segments, keeping, saying, sending, the weekly look."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from asuna import outbound_media, stickers, vision
from asuna.blobs import BlobStore
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_engineering_m1 import THINK
from test_group_admin import BOT, GROUP, SCENE, setup as group_setup
from test_outbound_image import PNG, bridge

from qqadapter import faces                                 # noqa: E402  (test_group_admin set the path)
from qqadapter.inbound import _media_item                   # noqa: E402
from qqadapter.outbound import Outbound, build_send_params, verify_payload   # noqa: E402

STICKER_URL = 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=sticker'
PHOTO_URL = 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=photo'
MARKET = {'emoji_id': 'a' * 32, 'emoji_package_id': '237184', 'key': 'k' * 16}


# ── the adapter ─────────────────────────────────────────────────────
def test_the_adapter_names_faces_and_tells_stickers_from_photos():
    face = _media_item('face', {'id': '277', 'raw': {'faceText': '/汪汪', 'faceType': 2}})
    assert face['placeholder'] == '[表情:汪汪]' and face['face_id'] == '277'
    classic = _media_item('face', {'id': '14', 'raw': {'faceType': 1}})      # no name from NapCat: the table's
    assert classic['placeholder'] == '[表情:微笑]'
    custom = _media_item('image', {'file': 'A' * 32 + '.jpg', 'url': STICKER_URL, 'sub_type': '1', 'summary': '[动画表情]'})
    assert custom['placeholder'] == '[表情包]' and custom['sticker'] == 'custom'
    named = _media_item('image', {'file': 'B' * 32 + '.png', 'sub_type': '7', 'summary': '[赞]'})
    assert named['placeholder'] == '[表情包:赞]' and named['sticker'] == 'custom'
    market = _media_item('image', {'url': 'https://gxh.vip.qq.com/club/item/parcel/item/aa/%s/raw300.gif' % ('a' * 32),
                                   'summary': '[臭]', **MARKET})
    assert market['placeholder'] == '[表情包:臭]' and market['sticker'] == 'market'
    assert {k: market[k] for k in MARKET} == MARKET
    photo = _media_item('image', {'file': 'C' * 32 + '.jpg', 'url': PHOTO_URL, 'sub_type': '0'})
    assert photo['placeholder'] == '[图片（未解析）]' and 'sticker' not in photo


def test_the_adapter_sends_faces_in_the_words_and_a_sticker_alone():
    _, params = build_send_params('group', GROUP, '笑死[表情:汪汪] @qq:20002 [表情:没这个]', reply_to='9')
    assert [seg['type'] for seg in params['message']] == ['reply', 'text', 'face', 'text', 'at', 'text']
    assert params['message'][2]['data'] == {'id': '277'} and params['message'][-1]['data']['text'] == ' [表情:没这个]'
    _, params = build_send_params('dm', '20001', '[表情:微笑]好')
    assert [seg['type'] for seg in params['message']] == ['face', 'text']
    _, params = build_send_params('dm', '20001', '只有字')
    assert params['message'] == [{'type': 'text', 'data': {'text': '只有字'}}]     # unchanged without a face
    _, params = build_send_params('group', GROUP, '', reply_to='9', image_b64='QUJD', sticker={'kind': 'custom'})
    assert params['message'] == [{'type': 'image', 'data': {'file': 'base64://QUJD', 'sub_type': 1,
                                                            'summary': '[动画表情]'}}]
    _, params = build_send_params('group', GROUP, '', sticker={'kind': 'market', **MARKET, 'summary': '[臭]'})
    assert params['message'] == [{'type': 'mface', 'data': {**MARKET, 'summary': '[臭]'}}]
    assert faces.BY_NAME['干饭'] == '475' and faces.BY_ID['344'] == '大怨种'


def test_a_store_sticker_goes_out_with_no_words_and_reads_back_as_a_picture():
    sent, receipts = [], []
    outbound = Outbound(
        cfg=SimpleNamespace(route_for_target=lambda ttype, tid: {'id': 'g'}, napcat={'account_id': BOT}),
        host=SimpleNamespace(post_receipt=lambda pub, payload: receipts.append(payload) or SimpleNamespace(kind='ok', code=200)),
        onebot=SimpleNamespace(api_call=lambda action, params, timeout=None, meta=None:
                               sent.append((action, params)) or {'retcode': 0, 'data': {'message_id': 77}}),
        journal=SimpleNamespace(append=lambda *a, **k: None), counters=SimpleNamespace(inc=lambda *a: None),
        log=lambda *a: None, verify=False)
    outbound.handle_item({'publication_id': 'p1', 'attempt_id': 'a1', 'target': {'type': 'group', 'id': GROUP},
                          'text': '', 'sticker': {'kind': 'market', **MARKET, 'summary': '[臭]'}})
    assert sent == [('send_group_msg', {'group_id': int(GROUP), 'message': [{'type': 'mface', 'data': {**MARKET, 'summary': '[臭]'}}]})]
    assert receipts[-1]['status'] == 'platform_accepted'
    outbound.handle_item({'publication_id': 'p2', 'attempt_id': 'a2', 'target': {'type': 'group', 'id': GROUP}, 'text': ''})
    assert receipts[-1]['response']['reason'] == 'empty_text'          # words still required without a sticker
    outbound.handle_item({'publication_id': 'p3', 'attempt_id': 'a3', 'target': {'type': 'group', 'id': GROUP},
                          'text': '', 'sticker': {'kind': 'custom'}})
    assert receipts[-1]['response']['reason'] == 'sticker_picture_missing'
    read = {'retcode': 0, 'data': {'message_type': 'group', 'group_id': int(GROUP), 'message': [{'type': 'image'}],
                                   'sender': {'user_id': int(BOT)}}}
    meta = {'segments': ['mface'], 'target_type': 'group', 'target_id': GROUP, 'account_id': BOT}
    assert verify_payload(read, '77', meta)['result'] == 'verified'


# ── the core ────────────────────────────────────────────────────────
def media_line(store, rid, text, item, seq):
    store.put('messages', {'_id': rid, 'scene_id': SCENE, 'author': 'qq:20002', 'direction': 'inbound', 'text': text,
                           'received_at': '2026-10-06T01:%02d:00+00:00' % seq, 'policy_epoch': 1, 'scene_seq': 100 + seq,
                           'event': {'channel': {'id': 'qq', 'sender_id': '20002', 'account_id': BOT,
                                                 'target': {'type': 'group', 'id': GROUP}, 'platform_event_id': 'pe-' + rid},
                                     'raw': {'asuna_media': {'count': 1, 'items': [{'type': 'image', 'placeholder': text, **item}]}}}})
    return vision.ref_of(rid, 0)


def group_world(store, monkeypatch):
    group_setup(store, 'member')
    store.config['channels']['qq']['routes']['g']['members'] = {'20002': {'person_id': 'qq:20002'}}
    store.config['vision'] = {'image_hosts': ['multimedia.nt.qq.com.cn', 'gxh.vip.qq.com']}
    store.config.setdefault('character', {})['input_modalities'] = ['text', 'image']
    # each sticker its own bytes (the same picture sent twice is the same bytes)
    monkeypatch.setattr(vision, 'pull_bytes', lambda entry, config, max_bytes=None:
                        (PNG + entry['url'].encode(), 'image/png', 'url', {}))
    refs = {'custom': media_line(store, 'in-sticker', '[表情包]', {'file': 'A' * 32 + '.png', 'url': STICKER_URL,
                                                                    'sub_type': '1', 'sticker': 'custom'}, 1),
            'old': media_line(store, 'in-old', '[图片:动画表情（未解析）]', {'file': 'D' * 32 + '.jpg',
                                                                       'url': STICKER_URL + '2', 'sub_type': '1'}, 2),
            'market': media_line(store, 'in-market', '[表情包:臭]', {'url': 'https://gxh.vip.qq.com/x/raw300.gif',
                                                                     'summary': '[臭]', 'sticker': 'market', **MARKET}, 3),
            'photo': media_line(store, 'in-photo', '[图片（未解析）]', {'file': 'C' * 32 + '.jpg', 'url': PHOTO_URL,
                                                                     'sub_type': '0'}, 4)}
    store.put('messages', {'_id': 'in-faces', 'scene_id': SCENE, 'author': 'qq:20003', 'direction': 'inbound',
                           'text': '哈哈[表情:汪汪][表情:汪汪][表情:大怨种]', 'received_at': '2026-10-06T01:05:00+00:00',
                           'policy_epoch': 1, 'scene_seq': 105})
    return refs


def mention(key, text='@演示 收一下'):
    return {'event_id': key, 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': text,
            'group_context': {'wake_reason': 'mentioned_account', 'topic_id': key, 'mentioned_account_ids': [BOT]},
            'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                        'sender_id': '20002', 'platform_event_id': key}}


def test_she_keeps_stickers_from_the_group_and_sends_one_as_its_own_message(store, monkeypatch):
    refs = group_world(store, monkeypatch)
    lines = {rid: vision.line_refs(store.db.messages.find_one({'_id': rid}), store.config)
             for rid in ('in-sticker', 'in-old', 'in-market', 'in-photo')}
    assert lines['in-sticker'] == '（表情包 ref：%s）' % refs['custom'] and refs['old'] in lines['in-old']
    assert lines['in-photo'] == '（图 ref：%s）' % refs['photo'] and '表情包' in lines['in-market']
    keep = lambda ref, name: ('sticker', {'op': 'keep', 'ref': ref, 'name': name, 'when': '有人摸鱼的时候'})
    lane = FakeLane(store, [FakeTurn([THINK, keep(refs['custom'], '摸鱼'), keep(refs['market'], '臭'),
                                      keep(refs['old'], '老图'), keep(refs['photo'], '照片'),
                                      keep(refs['custom'], '又一个')], '收了[表情包:摸鱼]')])
    ep = Coordinator(store, lane).ingest(mention('keep-1'), persona='P1')
    assert ep['state'] in ('COMMITTED', 'WAITING_TASK'), ep.get('failure')
    assert 'sticker' in lane.calls[0]['tools']
    assert ep['context']['stickers_from_program']['shelf'] == '0 个，宽裕'
    assert ep['context']['faces_from_program']['seen_here'] == ['汪汪', '大怨种']
    results = [row for row in lane.tool_results if row[2] == 'sticker']
    assert [row[5] for row in results] == [True, True, True, False, False], results
    assert 'STICKER_IS_A_PHOTO' in results[3][4] and 'STICKER_ALREADY_KEPT' in results[4][4]
    shelf = {row['name']: row for row in stickers.shelf(store, 'P1')}
    assert set(shelf) == {'摸鱼', '臭', '老图'} and shelf['臭']['kind'] == 'market' and 'artifact_id' not in shelf['臭']
    kept = store.db.artifacts.find_one({'_id': shelf['摸鱼']['artifact_id']})
    assert kept['scope_key'] == 'global-safe' and kept['source_ids'] == ['sticker:in-sticker']
    rows = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}).sort('scene_seq', 1))
    assert [row['text'] for row in rows] == ['收了', '[表情包:摸鱼]']
    assert rows[1]['sticker'] == {'kind': 'custom', 'name': '摸鱼'} and rows[1]['attachment']['artifact_id'] == kept['_id']
    assert stickers.find(store, 'P1', '摸鱼')['sent'] == 1
    # The channel: words first, then the sticker alone, its picture served to the group because it is on her shelf.
    store.db.messages.update_many({'episode_id': ep['_id']}, {'$unset': {'not_before': ''}})
    store.db.messages.update_one({'_id': rows[0]['_id']}, {'$set': {'delivery_state': 'DELIVERED'}})
    [item] = bridge(store).claim('qq', supports=['image', 'sticker'])['items']
    assert item['publication_id'] == rows[1]['_id'] and item['text'] == '' and item['sticker'] == {'kind': 'custom'}
    claimed = store.db.messages.find_one({'_id': rows[1]['_id']})
    data, media = outbound_media.serve(store, BlobStore(store), claimed, outbound_media.declared(claimed))[:2]
    assert data == PNG + STICKER_URL.encode() and media == 'image/png'


def test_an_adapter_that_cannot_send_stickers_sends_none(store, monkeypatch):
    refs = group_world(store, monkeypatch)
    lane = FakeLane(store, [FakeTurn([THINK, ('sticker', {'op': 'keep', 'ref': refs['market'], 'name': '臭', 'when': '嫌弃'})],
                                     '[表情包:臭]')])
    ep = Coordinator(store, lane).ingest(mention('keep-2'), persona='P1')
    [row] = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}))
    assert row['sticker']['kind'] == 'market' and row['sticker']['emoji_id'] == MARKET['emoji_id']
    assert bridge(store).claim('qq', supports=['image'])['items'] == []
    row = store.db.messages.find_one({'_id': row['_id']})
    assert row['delivery_state'] == 'FAILED' and row['failure'] == 'CHANNEL_DOES_NOT_DECLARE_STICKER'


def test_what_she_says_is_checked_for_stickers_and_faces(store, monkeypatch):
    group_world(store, monkeypatch)
    ep = {'scene_id': SCENE, 'persona': 'P1'}
    assert stickers.speech_problem(store, ep, '好[表情:汪汪]') is None
    assert '架子上没有' in stickers.speech_problem(store, ep, '[表情包:不存在]')
    assert '不是 QQ 的小黄脸' in stickers.speech_problem(store, ep, '[表情:乱编的]')
    store.put('stickers', {'_id': 'stk-a', 'persona': 'P1', 'name': 'a', 'identity': 'x:a'})
    store.put('stickers', {'_id': 'stk-b', 'persona': 'P1', 'name': 'b', 'identity': 'x:b'})
    assert '最多发一个' in stickers.speech_problem(store, ep, '[表情包:a][表情包:b]')
    assert '发不出' in stickers.speech_problem(store, {'scene_id': 'dm-a', 'persona': 'P1'}, '[表情包:a]')
    assert stickers.split(['哈[表情包:a]哈', '嗯']) == ['哈', '[表情包:a]', '哈', '嗯']


def test_the_shelf_has_a_limit_and_rotating_it_is_hers(store, monkeypatch):
    refs = group_world(store, monkeypatch)
    monkeypatch.setattr(stickers, 'STICKER_SHELF', 2)
    blobs, ep = BlobStore(store), {'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1}
    keep = lambda ref, name: stickers.keep(store, blobs, ep, 'P1', {'ref': ref, 'name': name, 'when': '随手'}, store.config)
    assert keep(refs['custom'], '一')['shelf'] == '1 个，用了一大半'
    keep(refs['market'], '二')
    with pytest.raises(Exception, match='STICKER_SHELF_FULL'):
        keep(refs['old'], '三')
    assert stickers.rename(store, 'P1', '一', new_name='摸鱼', when='摸鱼时') == {'renamed': '一', 'name': '摸鱼', 'when': '摸鱼时'}
    stickers.drop(store, 'P1', '二')
    keep(refs['old'], '三')
    # The weekly look: kept two weeks ago and never sent; offered once, then not again within the week.
    long_ago = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    store.db.stickers.update_many({}, {'$set': {'kept_at': long_ago}})
    moment = datetime.now(timezone.utc)
    review = stickers.review_block(store, 'P1', moment)
    assert {item['sticker'] for item in review['items']} == {'摸鱼', '三'} and review['items'][0]['why'] == '收了以后还没发过'
    monkeypatch.setattr(stickers, 'STICKER_SHELF', 60)                 # not full: the week decides
    assert stickers.review_block(store, 'P1', moment + timedelta(days=1)) is None
    assert stickers.block(store, 'P1', {'_id': 'dm-a'}, at_home=True)['note'] == stickers.HOME_NOTE


def test_napcats_send_timeout_is_an_unknown_send_not_a_failed_one():
    """Owner 2026-10-06: every picture NapCat reported as a sendMsg timeout had reached the group; she resent them."""
    from qqadapter.outbound import platform_send_timed_out
    receipts = []
    napcat_said = {'status': 'failed', 'retcode': 1200, 'data': None, 'wording': '',
               'message': 'Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate EventRet:\n{}\n'}
    outbound = Outbound(
        cfg=SimpleNamespace(route_for_target=lambda ttype, tid: {'id': 'g'}, napcat={'account_id': BOT}),
        host=SimpleNamespace(post_receipt=lambda pub, payload: receipts.append(payload) or SimpleNamespace(kind='ok', code=200)),
        onebot=SimpleNamespace(api_call=lambda action, params, timeout=None, meta=None: napcat_said),
        journal=SimpleNamespace(append=lambda *a, **k: None), counters=SimpleNamespace(inc=lambda *a: None),
        log=lambda *a: None, verify=False)
    outbound.handle_item({'publication_id': 'p1', 'attempt_id': 'a1', 'target': {'type': 'group', 'id': GROUP}, 'text': '看图'})
    assert receipts[-1]['status'] == 'unknown' and receipts[-1]['response']['reason'] == 'platform_send_timeout', receipts
    assert not platform_send_timed_out({'retcode': 1200, 'message': 'group not found'})     # a real 1200 still fails
