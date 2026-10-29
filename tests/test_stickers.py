"""ADR-016: QQ faces and her sticker shelf -- the adapter's segments, keeping, saying, sending, the weekly look."""
import sys
from types import SimpleNamespace

from asuna.config import ROOT
from test_people import BOT, GROUP

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import faces                                 # noqa: E402
from qqadapter.inbound import _media_item                   # noqa: E402
from qqadapter.outbound import Outbound, build_send_params, verify_payload   # noqa: E402

STICKER_URL = 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=sticker'
PHOTO_URL = 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=photo'
MARKET = {'emoji_id': 'a' * 32, 'emoji_package_id': '237184', 'key': 'k' * 16}


# ── the adapter ─────────────────────────────────────────────────────
def test_the_adapter_names_faces_and_tells_stickers_from_photos():
    face = _media_item('face', {'id': '277', 'raw': {'faceText': '/汪汪', 'faceType': 2}})
    assert face['placeholder'] == '[表情:狗头]' and face['face_id'] == '277'   # NapCat still says `/汪汪` there; the alias shows the current name
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
    _, params = build_send_params('group', GROUP, '笑死[表情:狗头] @qq:20002 [表情:没这个]', quote='9')
    assert [seg['type'] for seg in params['message']] == ['reply', 'text', 'face', 'text', 'at', 'text']
    assert params['message'][2]['data'] == {'id': '277'} and params['message'][-1]['data']['text'] == ' [表情:没这个]'
    _, params = build_send_params('dm', '20001', '[表情:微笑]好')
    assert [seg['type'] for seg in params['message']] == ['face', 'text']
    _, params = build_send_params('dm', '20001', '只有字')
    assert params['message'] == [{'type': 'text', 'data': {'text': '只有字'}}]     # unchanged without a face
    _, params = build_send_params('group', GROUP, '', quote='9', image_b64='QUJD', sticker={'kind': 'custom'})
    assert params['message'] == [{'type': 'image', 'data': {'file': 'base64://QUJD', 'sub_type': 1,
                                                            'summary': '[动画表情]'}}]
    _, params = build_send_params('group', GROUP, '', sticker={'kind': 'market', **MARKET, 'summary': '[臭]'})
    assert params['message'] == [{'type': 'mface', 'data': {**MARKET, 'summary': '[臭]'}}]
    assert faces.BY_NAME['干饭'] == '475' and faces.BY_ID['344'] == '大怨种'


def test_a_store_sticker_goes_out_with_no_words_and_reads_back_as_a_picture():
    sent, receipts = [], []
    outbound = Outbound(
        cfg=SimpleNamespace(napcat={'account_id': BOT}),
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


def test_napcats_send_timeout_is_an_unknown_send_not_a_failed_one():
    """Owner 2026-10-06: every picture NapCat reported as a sendMsg timeout had reached the group; she resent them."""
    from qqadapter.outbound import platform_send_timed_out
    receipts = []
    napcat_said = {'status': 'failed', 'retcode': 1200, 'data': None, 'wording': '',
               'message': 'Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate EventRet:\n{}\n'}
    outbound = Outbound(
        cfg=SimpleNamespace(napcat={'account_id': BOT}),
        host=SimpleNamespace(post_receipt=lambda pub, payload: receipts.append(payload) or SimpleNamespace(kind='ok', code=200)),
        onebot=SimpleNamespace(api_call=lambda action, params, timeout=None, meta=None: napcat_said),
        journal=SimpleNamespace(append=lambda *a, **k: None), counters=SimpleNamespace(inc=lambda *a: None),
        log=lambda *a: None, verify=False)
    outbound.handle_item({'publication_id': 'p1', 'attempt_id': 'a1', 'target': {'type': 'group', 'id': GROUP}, 'text': '看图'})
    assert receipts[-1]['status'] == 'unknown' and receipts[-1]['response']['reason'] == 'platform_send_timeout', receipts
    assert not platform_send_timed_out({'retcode': 1200, 'message': 'group not found'})     # a real 1200 still fails


