"""Who is in a group (owner 2026-10-08, her design): the adapter posts each admitted group's member list when it
changed; the host keeps it apart from her roster; a group turn names a slice in words; find_member reaches the rest."""
import sys
import time
from types import SimpleNamespace

import pytest

from asuna import group_members
from asuna.config import ROOT
from asuna.people import People
from test_people import BOT, GROUP, row, setup

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter.journal import Counters                             # noqa: E402
from qqadapter.members import Members                              # noqa: E402

NOW = int(time.time())


def channel(store):
    store.config['channels'] = {'qq': {'account_id': BOT, 'routes': {
        'g': {'scene_id': 'qq:%s:group:%s' % (BOT, GROUP), 'target': {'type': 'group', 'id': GROUP}}}}}


def member(n, role='member', ago_hours=None, card=''):
    out = {'user_id': str(20000 + n), 'nickname': '人%d' % n, 'card': card, 'role': role}
    if ago_hours is not None:
        out['last_sent_time'] = NOW - int(ago_hours * 3600)
    return out


def test_the_host_keeps_an_admitted_groups_list_and_refuses_others(store):
    setup(store)
    channel(store)
    assert group_members.receive(store, 'qq', {'group_id': GROUP, 'members': [member(1), {'user_id': 'x'}]}) == \
        {'status': 'stored', 'count': 1}
    with pytest.raises(PermissionError, match='MEMBERS_GROUP_NOT_ROUTED: 群 99999'):
        group_members.receive(store, 'qq', {'group_id': '99999', 'members': [member(1)]})
    with pytest.raises(ValueError, match='MEMBERS_INVALID'):
        group_members.receive(store, 'qq', {'group_id': GROUP, 'members': []})


def test_a_turn_names_who_she_knows_the_recently_active_and_the_mentioned(store):
    scene = setup(store)
    channel(store)
    People(store).entry(scene, 'qq:20002', row(20002, 'hi', card='阿杰'))         # someone she knows here
    members = [member(1, 'owner', 1), member(2, ago_hours=500)] + [member(n, ago_hours=n) for n in range(3, 70)]
    group_members.receive(store, 'qq', {'group_id': GROUP, 'members': members})
    block = group_members.block(store, scene, 'demo')
    whos = [item['who'] for item in block['items']]
    assert block['count'] == '群里一共 69 人' and block['leaders'] == ['人1（群主）']
    assert any(who.startswith('[阿杰 #') for who in whos), 'a known person reads as her label'
    assert '人3' in whos and '人69' not in whos and len(whos) == 51            # top 50 active + the known one
    assert block['not_shown'] == '另有 18 人没列出' and '最近说话是' in block['items'][0]['active']
    found = group_members.find(store, scene, 'demo', '人6')
    assert found['count'] == 11 and len(found['found']) == 10 and found['found'][0]['who'] == '人6'


class Platform:
    def __init__(self, groups, members):
        self.groups, self.members, self.calls = groups, members, []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append(action)
        if action == 'get_group_list':
            return {'retcode': 0, 'data': [{'group_id': int(g)} for g in self.groups]}
        return {'retcode': 0, 'data': self.members}


def test_the_adapter_posts_admitted_groups_only_when_they_changed(tmp_path, monkeypatch):
    import qqadapter.members as module
    monkeypatch.setattr(module, 'GROUP_PAUSE', 0)
    cfg = SimpleNamespace(route_for_group=lambda g: object() if g == '111111' else None)
    posted = []
    host = SimpleNamespace(post_members=lambda body: posted.append(body) or SimpleNamespace(kind='accepted'))
    platform = Platform(['111111', '222222'], [{'user_id': 30001, 'nickname': 'a', 'qq_level': 0, 'role': 'member'}])
    job = Members(cfg, str(tmp_path), platform, host, Counters(), log=lambda _m: None)
    assert job.run() == {'groups': 1, 'posted': 1, 'same': 0, 'failed': 0}
    assert posted[0]['group_id'] == '111111' and posted[0]['members'] == [{'user_id': 30001, 'nickname': 'a', 'role': 'member'}]
    again = Members(cfg, str(tmp_path), platform, host, Counters(), log=lambda _m: None)
    assert again.run()['same'] == 1 and len(posted) == 1                          # unchanged: not posted again
