"""Who is in a group (owner 2026-10-08, her design): the adapter posts each admitted group's member list when it
changed; the host keeps it apart from her roster; a group turn names a slice in words; find_member reaches the rest
and gives a label to whom it finds."""
import sys
import time
from types import SimpleNamespace


from asuna.config import ROOT

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter.journal import Counters                             # noqa: E402
from qqadapter.members import Members                              # noqa: E402

NOW = int(time.time())


def member(n, role='member', ago_hours=None, card=''):
    out = {'user_id': str(20000 + n), 'nickname': '人%d' % n, 'card': card, 'role': role}
    if ago_hours is not None:
        out['last_sent_time'] = NOW - int(ago_hours * 3600)
    return out


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
    cfg = SimpleNamespace()
    core = SimpleNamespace(ask_many=lambda groups: [SimpleNamespace(admitted=g == ('group', '111111'), known=g == ('group', '111111'))
                                                    for g in groups])
    posted = []
    host = SimpleNamespace(post_members=lambda body: posted.append(body) or SimpleNamespace(kind='accepted'))
    platform = Platform(['111111', '222222'], [{'user_id': 30001, 'nickname': 'a', 'qq_level': 0, 'role': 'member'}])
    job = Members(cfg, str(tmp_path), platform, host, Counters(), core, log=lambda _m: None)
    assert job.run() == {'groups': 1, 'posted': 1, 'same': 0, 'failed': 0}
    assert posted[0]['group_id'] == '111111' and posted[0]['members'] == [{'user_id': 30001, 'nickname': 'a', 'role': 'member'}]
    again = Members(cfg, str(tmp_path), platform, host, Counters(), core, log=lambda _m: None)
    assert again.run()['same'] == 1 and len(posted) == 1                          # unchanged: not posted again


def test_a_round_that_cannot_list_the_groups_is_tried_again_soon_and_posts_nothing(tmp_path):
    from qqadapter.admission import AdmissionAway

    class Away:
        def ask_many(self, groups):
            raise AdmissionAway()
    posted = []
    host = SimpleNamespace(post_members=lambda body: posted.append(body))
    job = Members(SimpleNamespace(), str(tmp_path), Platform(['111111'], []), host, Counters(), Away(), log=lambda _m: None)
    assert job.run() == {'groups': 0, 'posted': 0, 'same': 0, 'failed': 0} and job.retry_soon and posted == []
