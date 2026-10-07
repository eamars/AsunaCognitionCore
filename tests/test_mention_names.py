"""Someone a group message @-mentions gets their name, as a speaker does (Xiaoman's plan, 2026-10-08).

The adapter looks the mentioned people up like a sender; the host keeps only profiles bound to a mentioned
account and this group, and names their entries from them, so her @ of them is a real @ and they read by name.
"""
import sys

from asuna.channels import kept_raw
from asuna.config import ROOT
from asuna.people import People
from test_people import BOT, GROUP, row, setup

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter.peers import MENTIONED_KEY, PeerDirectory          # noqa: E402


class MemberInfo:
    """The platform's member lookup, per account; counts every call."""

    def __init__(self, people):
        self.people, self.calls = people, []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append((action, params['user_id']))
        person = self.people.get(str(params['user_id']))
        if person is None:
            return {'status': 'failed', 'retcode': 100, 'data': None}
        return {'status': 'ok', 'retcode': 0, 'data': {'group_id': int(GROUP), 'user_id': params['user_id'],
                                                       'role': 'member', 'title': '', **person}}


def envelope(mentions, sender='20001'):
    return {'route_id': 'g', 'account_id': BOT, 'sender_id': sender, 'event_id': 'e1', 'text': '@ 欢迎',
            'group_id': GROUP, 'mentioned_account_ids': list(mentions), 'raw': {}}


def test_the_adapter_looks_up_the_people_a_message_mentions(tmp_path):
    api = MemberInfo({'20003': {'nickname': '新人', 'card': ''}, '20004': {'nickname': '老王', 'card': '王工'},
                      '20005': {'nickname': 'a'}, '20006': {'nickname': 'b'}})
    peers = PeerDirectory(str(tmp_path), min_refresh=60.0)
    env = envelope(['20003', '20004', '20001', BOT, '20003'])          # the sender, herself and a repeat are skipped
    profiles = peers.observe_mentions(env, api)
    assert [(p['account_id'], p['display'], p['verified']) for p in profiles] == [('20003', '新人', True),
                                                                                 ('20004', '王工', True)]
    assert env['raw'][MENTIONED_KEY] == profiles and api.calls == [('get_group_member_info', 20003),
                                                                   ('get_group_member_info', 20004)]
    record = peers.dump()['people']['qq:20003']['scenes']['group:' + GROUP]
    assert record['messages'] == 0                                    # a mention is not a message from them
    # Within the refresh window nobody is asked again; a known profile still comes along.
    again = envelope(['20003'])
    assert peers.observe_mentions(again, api)[0]['display'] == '新人' and len(api.calls) == 2
    # At most three lookups for one message; a refused block is dropped with the sender's.
    crowd = envelope(['20005', '20006', '20007', '20008'])
    peers.observe_mentions(crowd, api)
    assert len(api.calls) == 5
    assert PeerDirectory.strip(crowd) and MENTIONED_KEY not in crowd['raw']


def test_the_host_keeps_only_bound_profiles_and_names_the_people_mentioned(store):
    scene = setup(store)
    event = {'channel': {'id': 'qq', 'sender_id': '20002', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP}}}
    good = {'person_id': 'qq:20003', 'account_id': '20003', 'scene': 'group:' + GROUP, 'group_id': GROUP,
            'display': '新人', 'nickname': '新人', 'card': '', 'role': 'member', 'verified': True, 'address': 'x'}
    raw = {MENTIONED_KEY: [good, {**good, 'account_id': '20009', 'person_id': 'qq:20009'},     # not mentioned
                           {**good, 'group_id': '70000', 'scene': 'group:70000'}]}             # another group
    kept = kept_raw(event, raw, ['20003'])
    assert [p['account_id'] for p in kept[MENTIONED_KEY]] == ['20003'] and 'address' not in kept[MENTIONED_KEY][0]
    message = row(20002, '@[还不知道名字 #2] 欢迎', card='阿杰', mentions=['20003'])
    message['event']['raw'][MENTIONED_KEY] = kept[MENTIONED_KEY]
    people = People(store)
    people.transcript(scene, message)
    entry = store.db.scene_people.find_one({'_id': scene['_id'] + '|qq:20003'})
    assert entry['nickname'] == '新人' and entry['seen_at']
    assert People(store).outbound(scene, '[新人 #%d] 欢迎' % entry['handle']) == '新人 欢迎'
    # Without a looked-up profile the mentioned person is labelled as before, nameless until they speak.
    bare = row(20002, '又来一个', mentions=['20010'], at='2026-10-04T02:00:00+00:00')
    People(store).transcript(scene, bare)
    assert store.db.scene_people.find_one({'_id': scene['_id'] + '|qq:20010'})['nickname'] == ''
