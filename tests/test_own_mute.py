"""Her own mute in a group is a state she reads, not a notice she misses (ADR-064 item 3, built ahead as a bug fix).

She was muted in a group for weeks and never knew: the adapter dropped every notice, and a send refused for the mute
came back as a bare "没发出去". The adapter now reports a mute about her, a refused send says why, a look at start
finds a mute that began while nothing was listening, and every turn in that group says so before she speaks."""
import sys
from types import SimpleNamespace


from asuna.config import ROOT

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import fixtures, mutes as adapter_mutes            # noqa: E402
from qqadapter.journal import Counters                            # noqa: E402
from qqadapter.outbound import Outbound, send_outcome             # noqa: E402

# NapCat's answer to a send while muted, as the live receipt stored it (QQ result 120).
MUTED_ANSWER = {'status': 'failed', 'retcode': 1200, 'data': None,
                'message': 'EventChecker Failed: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg '
                           'ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate EventRet:\n{\n    "result": 120,\n'
                           '    "errMsg": ""\n}\n'}
CFG = fixtures.load_config()
ACCOUNT, ROUTED = fixtures.ACCOUNT, fixtures.GROUPS[0]


def ban(user, sub='ban', duration=600, group=ROUTED, operator='900000101', at=1_800_000_000):
    return {'post_type': 'notice', 'notice_type': 'group_ban', 'sub_type': sub, 'self_id': int(ACCOUNT),
            'group_id': int(group), 'user_id': int(user), 'operator_id': int(operator), 'duration': duration, 'time': at}


# ---- the adapter --------------------------------------------------------------------------------------------------
def test_a_mute_notice_about_her_or_the_whole_group_becomes_a_state_report_and_others_stay_dropped():
    assert adapter_mutes.notice_body(ban(ACCOUNT), CFG) == {
        'group_id': ROUTED, 'source': 'notice', 'muted': True, 'whole_group': False, 'operator_id': '900000101',
        'at': 1_800_000_000, 'until': 1_800_000_600}
    lift = adapter_mutes.notice_body(ban(ACCOUNT, 'lift_ban', 0), CFG)
    assert lift['muted'] is False and 'until' not in lift
    whole = adapter_mutes.notice_body(ban(0, duration=-1), CFG)
    assert whole['whole_group'] is True and whole['muted'] is True and 'until' not in whole
    assert adapter_mutes.notice_body(ban('900000102'), CFG) is None, "someone else's mute is not hers"
    assert adapter_mutes.notice_body(ban(ACCOUNT, group=fixtures.UNKNOWN_GROUP), CFG) is None, 'not an admitted group'
    assert adapter_mutes.notice_body({**ban(ACCOUNT), 'notice_type': 'group_recall'}, CFG) is None


def test_the_adapter_posts_her_mute_from_its_own_thread_and_never_spools_it_as_a_turn(tmp_path):
    from qqadapter.service import Adapter
    adapter = Adapter(CFG, str(tmp_path))
    adapter.on_event(ban(ACCOUNT))
    adapter.on_event({**ban('900000102')})                           # another member's mute: still dropped
    assert adapter.journal.spool_list('inbound') == []
    assert adapter.mutes.jobs.get_nowait()[:2] == ('post', adapter_mutes.notice_body(ban(ACCOUNT), CFG))
    assert adapter.mutes.jobs.empty()
    assert adapter.counters.snapshot()['inbound_nonmessage'] == 1


def test_a_send_refused_for_a_mute_is_failed_with_the_reason_and_her_group_is_looked_at():
    status, pmid, tag, response = send_outcome(MUTED_ANSWER)
    assert (status, pmid, tag, response['reason']) == ('failed', None, 'platform_muted', 'muted')
    timeout = {**MUTED_ANSWER, 'message': 'Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg'}
    assert send_outcome(timeout)[0] == 'unknown', 'a slow send is still unknown, not muted'
    assert 'reason' not in send_outcome({**MUTED_ANSWER, 'message': '"result": 1201 sendMsg'})[3]
    reported, looked = [], []
    host = SimpleNamespace(post_receipt=lambda pub, payload: reported.append(payload) or SimpleNamespace(kind='ok', code=200))
    journal = SimpleNamespace(append=lambda *a: None)
    out = Outbound(CFG, host, None, journal, Counters(), log=lambda _m: None, verify=False)
    out.on_muted = looked.append
    out.settle('pub-1', 'att-1', MUTED_ANSWER, {'target_type': 'group', 'target_id': ROUTED, 'segments': ['text']})
    assert reported[0]['status'] == 'failed' and reported[0]['response']['reason'] == 'muted'
    assert looked == [ROUTED]


class Platform:
    def __init__(self, ends=0, all_shut=0):
        self.ends, self.all_shut, self.calls = ends, all_shut, []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append((action, params))
        if action == 'get_group_member_info':
            return {'retcode': 0, 'data': {'user_id': params['user_id'], 'shut_up_timestamp': self.ends}}
        return {'retcode': 0, 'data': {'group_id': params['group_id'], 'group_all_shut': self.all_shut}}


def mutes_job(tmp_path, platform, groups, clock, posted, pauses):
    host = SimpleNamespace(post_own_mute=lambda body: posted.append(body) or SimpleNamespace(
        kind='accepted', code=200, obj={'status': 'muted' if body['muted'] else 'cleared'}))
    return adapter_mutes.Mutes(CFG, str(tmp_path), platform, host, Counters(), lambda: groups, log=lambda _m: None,
                               clock=clock, sleep=pauses.append)


def test_a_look_at_start_reads_her_mute_read_only_and_a_group_looked_at_lately_is_not_asked_again(tmp_path):
    now = [1_800_000_000.0]
    platform, posted, pauses = Platform(ends=1_800_086_400), [], []
    groups = list(fixtures.GROUPS[:3])
    job = mutes_job(tmp_path, platform, groups, lambda: now[0], posted, pauses)
    totals = job.sweep_now('startup')
    assert totals == {'groups': 3, 'looked': 3, 'skipped': 0, 'muted': 3, 'failed': 0}
    assert {action for action, _ in platform.calls} == {'get_group_member_info', 'get_group_info'}, 'read-only calls'
    assert all(params['no_cache'] is True for _, params in platform.calls)
    assert posted[0] == {'group_id': groups[0], 'source': 'lookup', 'muted': True, 'whole_group': False,
                         'until': 1_800_086_400}
    assert pauses == [adapter_mutes.GROUP_PAUSE] * 2, 'a pause between groups, none before the first'
    # A restart an hour later asks nobody again; the record survives the restart.
    now[0] += 3600
    platform.calls.clear()
    again = mutes_job(tmp_path, platform, groups, lambda: now[0], posted, pauses)
    assert again.sweep_now('startup')['skipped'] == 3 and platform.calls == []
    # A refused send looks at once, whatever the record says.
    assert again.look(groups[0]) == 'muted' and len(platform.calls) == 2
    # Past the interval, every group is looked at again.
    now[0] += adapter_mutes.CHECK_EVERY_SECONDS
    assert again.sweep_now('reconnect')['looked'] == 3


def test_a_look_tells_a_whole_group_mute_and_no_mute_apart():
    assert adapter_mutes.look_body('1', {'retcode': 0, 'data': {'shut_up_timestamp': 0}},
                                   {'retcode': 0, 'data': {'group_all_shut': -1}}, 100) == \
        {'group_id': '1', 'source': 'lookup', 'muted': True, 'whole_group': True}
    assert adapter_mutes.look_body('1', {'retcode': 0, 'data': {'shut_up_timestamp': 50}},
                                   {'retcode': 0, 'data': {'group_all_shut': 0}}, 100)['muted'] is False
    assert adapter_mutes.look_body('1', {'retcode': 1404}, {'retcode': 0, 'data': {}}, 100) is None


