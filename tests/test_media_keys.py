"""QQ picture links are signed again with the platform's current key before they are fetched (ADR-035): the adapter
reads NapCat's keys and posts them, the host keeps them in memory only, a link that just arrived is the fallback, and
a refusal says which of three it is."""
import sys

import pytest

from asuna import channel_kinds, media_keys
from asuna.vision import _fetch_failed
from conftest import QQ_CHANNEL, ROOT

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import media_keys as adapter_keys                  # noqa: E402

GROUP = 'https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=EhQ-abc_DEF&spec=0&rkey=OLD_GROUP_KEY'
PRIVATE = 'https://multimedia.nt.qq.com.cn/download?appid=1406&fileid=EhQ-xyz&rkey=OLD_PRIVATE_KEY&spec=0'
PLAIN = 'https://gchat.qpic.cn/gchatpic_new/1/2-3-ABCDEF/0'


@pytest.fixture(autouse=True)
def qq_kind():
    channel_kinds.load([QQ_CHANNEL])          # another test may have registered a stand-in 'qq' kind
    media_keys.forget()
    yield
    media_keys.forget()


def test_the_adapter_reads_every_shape_napcat_answers_in():
    now = 1_000_000.0
    listed = [{'type': 'private', 'rkey': '&rkey=PRIV', 'created_at': now - 600, 'ttl': 3600},
              {'type': 'group', 'rkey': 'GRP', 'created_at': now - 3590, 'ttl': 3600}]        # ten seconds left
    assert adapter_keys.parse(listed, now) == [{'name': 'qq-private', 'key': 'PRIV', 'seconds': 3000}]
    raw = [{'type': 20, 'rkey': '&rkey=G2', 'time': str(int(now)), 'ttl': '1800'}, {'type': 10, 'rkey': '&rkey=P2'}]
    assert adapter_keys.parse(raw, now) == [{'name': 'qq-group', 'key': 'G2', 'seconds': 1800},
                                           {'name': 'qq-private', 'key': 'P2', 'seconds': adapter_keys.DEFAULT_SECONDS}]
    server = {'group_rkey': '&rkey=G3', 'private_rkey': '&rkey=P3', 'expired_time': now + 900, 'name': 'NapCat 4'}
    assert [row['name'] for row in adapter_keys.parse(server, now)] == ['qq-group', 'qq-private']
    assert adapter_keys.parse([{'type': 'group', 'rkey': 'a&b'}], now) == [], 'a key that would break the link is dropped'


def test_the_adapter_falls_back_through_the_actions_and_never_logs_a_key():
    class OneBot:
        def __init__(self):
            self.asked = []

        def api_call(self, action, params, timeout, meta):
            self.asked.append(action)
            if action == 'get_rkey':
                return {'retcode': 1404, 'status': 'failed'}
            return {'retcode': 0, 'data': [{'type': 20, 'rkey': '&rkey=SECRET_G', 'time': 0, 'ttl': 0}]
                                           if action == 'nc_get_rkey' else None}

    class Host:
        posted = None

        def post_media_keys(self, body):
            Host.posted = body
            return type('R', (), {'kind': 'accepted', 'code': 200, 'obj': {'status': 'stored'}})()

    class Counters:
        def inc(self, *args):
            pass
    lines, onebot = [], OneBot()
    keys = adapter_keys.MediaKeys(onebot, Host(), Counters(), log=lines.append, clock=lambda: 0.0)
    assert keys.run() is False, 'a key whose time is up is not posted'
    onebot.asked.clear()
    keys.clock = lambda: -1000.0            # the same key, 1000 s before its end
    assert keys.run() is True and onebot.asked == ['get_rkey', 'nc_get_rkey']
    assert Host.posted == {'keys': [{'name': 'qq-group', 'key': 'SECRET_G', 'seconds': 1000}]}
    assert lines[-1] == 'MEDIA_KEYS posted=qq-group action=nc_get_rkey seconds=1000'
    assert not any('SECRET' in line for line in lines)


def test_the_qq_kind_signs_only_its_signed_links_with_the_key_of_their_kind():
    assert channel_kinds.media_key_name(GROUP) == 'qq-group'
    assert channel_kinds.media_key_name(PRIVATE) == 'qq-private'
    assert channel_kinds.media_key_name(PLAIN) is None
    assert channel_kinds.media_key_in(GROUP) == ('qq-group', 'OLD_GROUP_KEY')
    assert channel_kinds.sign_media(PRIVATE, 'NEW') == PRIVATE.replace('OLD_PRIVATE_KEY', 'NEW'), 'nothing else changes'
    detail = '{"retcode":-5503007,"retmsg":"download url has expired"}'
    assert channel_kinds.media_refusal(GROUP, 400, detail) == 'expired'
    assert channel_kinds.media_refusal(GROUP, 404, '') == 'gone'
    assert channel_kinds.media_refusal(GROUP, 400, 'other') is None


def test_the_host_holds_declared_keys_and_a_fresh_link_is_the_fallback():
    assert media_keys.sign(GROUP) == (GROUP, 'unavailable')
    assert media_keys.sign(PLAIN) == (PLAIN, None)
    with pytest.raises(ValueError, match='MEDIA_KEY_NAME_DENIED'):
        media_keys.receive('qq', {'keys': [{'name': 'other-key', 'key': 'K', 'seconds': 600}]})
    with pytest.raises(ValueError, match='MEDIA_KEY_INVALID'):
        media_keys.receive('qq', {'keys': [{'name': 'qq-group', 'key': 'a&rkey=b', 'seconds': 600}]})
    answer = media_keys.receive('qq', {'keys': [{'name': 'qq-group', 'key': 'CURRENT', 'seconds': 600}]})
    assert answer == {'status': 'stored', 'names': ['qq-group']} and 'CURRENT' not in str(answer)
    assert media_keys.sign(GROUP) == (GROUP.replace('OLD_GROUP_KEY', 'CURRENT'), 'renewed')

    def arrived(url):
        media_keys.saw({'raw': {'asuna_media': {'items': [{'type': 'image', 'url': url}]}}})
    arrived(GROUP.replace('OLD_GROUP_KEY', 'FROM_LINK'))
    assert media_keys.current('qq-group') == 'CURRENT', "a link's key does not displace the adapter's"
    arrived(PRIVATE.replace('OLD_PRIVATE_KEY', 'FROM_PRIVATE_LINK'))
    assert media_keys.sign(PRIVATE)[0].endswith('rkey=FROM_PRIVATE_LINK&spec=0')
    with pytest.raises(ValueError, match='MEDIA_KEYS_INVALID'):
        media_keys.receive('qq', {'keys': []})


def test_a_refused_signed_link_says_which_of_three_it_is():
    expired = '{"retcode":-5503007,"retmsg":"download url has expired"}'
    assert str(_fetch_failed(400, expired, GROUP, 'renewed')).startswith('IMAGE_LINK_EXPIRED: ')
    assert str(_fetch_failed(400, expired, GROUP, 'unavailable')).startswith('IMAGE_SIGNATURE_UNAVAILABLE: ')
    assert '过一会儿再试一次' in str(_fetch_failed(400, expired, GROUP, 'unavailable')), 'worth waiting for'
    assert str(_fetch_failed(404, '', GROUP, 'renewed')).startswith('IMAGE_GONE: ')
    assert str(_fetch_failed(400, expired, PLAIN, None)).startswith('IMAGE_FETCH_FAILED: '), 'an unsigned link as before'
