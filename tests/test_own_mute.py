"""Her own mute in a group is a state she reads, not a notice she misses (ADR-064 item 3, built ahead as a bug fix).

She was muted in a group for weeks and never knew: the adapter dropped every notice, and a send refused for the mute
came back as a bare "没发出去". The adapter now reports a mute about her, a refused send says why, a look at start
finds a mute that began while nothing was listening, and every turn in that group says so before she speaks."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from asuna import own_mute, schedule_rules
from asuna.config import ROOT
from test_group_admin import bridge, setup as group_setup
from test_people import BOT, GROUP, SCENE

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


# ---- the host -----------------------------------------------------------------------------------------------------
def zone(store):
    return schedule_rules.scene_timezone(store.config, store.db.scenes.find_one({'_id': SCENE}))


def stamp(store, epoch):
    return schedule_rules.line_stamp(zone(store), datetime.fromtimestamp(epoch, timezone.utc).isoformat())


def test_a_ban_notice_sets_her_state_with_who_and_until_and_a_lift_clears_it(store):
    scene = group_setup(store, 'member')
    until = int(time.time()) + 29 * 86400
    body = {'group_id': GROUP, 'source': 'notice', 'muted': True, 'operator_id': '20003', 'at': until - 29 * 86400,
            'until': until}
    assert bridge(store).own_mute('qq', body) == {'status': 'muted'}
    line = own_mute.line(store, scene, zone(store))
    assert line == '你在这个群被禁言了，到 %s，[老王 #3]禁的：你说的话发不出去。' % stamp(store, until)
    assert 'qq:' not in line and '20003' not in line
    assert bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': False}) == {'status': 'cleared'}
    assert own_mute.line(store, scene, zone(store)) is None
    with pytest.raises(PermissionError, match='OWN_MUTE_GROUP_NOT_ROUTED'):
        bridge(store).own_mute('qq', {**body, 'group_id': '99999'})
    with pytest.raises(PermissionError, match='OWN_MUTE_FIELD_DENIED'):
        bridge(store).own_mute('qq', {**body, 'text': 'x'})


def test_who_did_it_is_said_to_be_unknown_rather_than_left_out(store):
    scene = group_setup(store, 'member')
    until = int(time.time()) + 3600
    bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': True, 'operator_id': '29999',
                                  'until': until})
    assert '谁禁的不知道' in own_mute.line(store, scene, zone(store)), 'an operator she has no label for'
    bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': False})
    bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'lookup', 'muted': True, 'until': until})
    assert own_mute.line(store, scene, zone(store)) == \
        '你在这个群被禁言了，到 %s，谁禁的不知道：你说的话发不出去。' % stamp(store, until), 'a look names nobody'


def test_a_mute_ends_by_itself_a_whole_group_mute_skips_an_admin_and_a_look_clears_it(store):
    scene = group_setup(store, 'admin')
    past = int(time.time()) - 60
    own_mute.apply(store, scene, muted=True, source='lookup', until=datetime.fromtimestamp(past, timezone.utc).isoformat())
    assert own_mute.active(store, SCENE) is None, 'past its end'
    assert bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': True, 'whole_group': True}) \
        == {'status': 'not_her'}, 'a whole-group mute does not hold an admin'
    member = group_setup(store, 'member')
    bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': True, 'whole_group': True,
                                  'operator_id': '20003'})
    assert own_mute.line(store, member, zone(store)) == \
        '这个群开着全员禁言，到什么时候不知道，[老王 #3]开的：你说的话发不出去。'
    assert bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'notice', 'muted': False}) == \
        {'status': 'unchanged'}, 'lifting her own mute leaves a whole-group one'
    assert bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'lookup', 'muted': False}) == {'status': 'cleared'}


def outbound_row(store, key, state='SENDING'):
    store.put('messages', {'_id': key, 'scene_id': SCENE, 'channel_id': 'qq', 'direction': 'outbound', 'author': 'demo',
                           'text': '大家好', 'delivery_state': state, 'attempt_id': 'a-' + key, 'episode_id': 'ep-' + key,
                           'policy_epoch': 1, 'scene_seq': 50, 'target': {'type': 'group', 'id': GROUP}})


def test_a_refused_send_sets_the_state_and_a_send_that_goes_out_clears_it(store):
    scene = group_setup(store, 'member')
    outbound_row(store, 'pub-muted')
    body = {'attempt_id': 'a-pub-muted', 'status': 'failed', 'response': {**MUTED_ANSWER, 'reason': 'muted'}}
    assert bridge(store).receipt('qq', 'pub-muted', body) == {'status': 'FAILED'}
    assert own_mute.line(store, scene, zone(store)) == '你在这个群被禁言了，到什么时候不知道，谁禁的不知道：你说的话发不出去。'
    until = int(time.time()) + 600
    bridge(store).own_mute('qq', {'group_id': GROUP, 'source': 'lookup', 'muted': True, 'until': until})
    assert stamp(store, until) in own_mute.line(store, scene, zone(store)), 'the look after the refused send says until when'
    outbound_row(store, 'pub-ok')
    bridge(store).receipt('qq', 'pub-ok', {'attempt_id': 'a-pub-ok', 'status': 'platform_accepted',
                                           'platform_message_id': '123', 'response': {'retcode': 0}})
    assert own_mute.active(store, SCENE) is None, 'an early lift: her line went out, so she is not muted'


# ---- what she reads -----------------------------------------------------------------------------------------------
def at_turn(store, key='at-1'):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '有人叫我。'})], '在的')])
    event = {'event_id': key, 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': '@演示 在吗',
             'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 't', 'mentioned_account_ids': [BOT]},
             'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP}, 'sender_id': '20002',
                         'platform_event_id': key}}
    return Coordinator(store, lane).ingest(event, persona='P1'), lane


def test_an_at_turn_in_a_muted_group_says_so_beside_the_trigger_and_the_refused_line_says_why(store):
    group_setup(store, 'member')
    outbound_row(store, 'pub-muted')
    bridge(store).receipt('qq', 'pub-muted', {'attempt_id': 'a-pub-muted', 'status': 'failed',
                                              'response': {**MUTED_ANSWER, 'reason': 'muted'}})
    ep, lane = at_turn(store)
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    context = ep['context']
    assert list(context)[-2:] == ['muted_here_from_program', 'event'], 'read right before the trigger'
    assert context['muted_here_from_program'].startswith('你在这个群被禁言了')
    [row] = [r for r in context['undelivered_outbound_not_public'] if r['_id'] == 'pub-muted']
    assert row['delivery_state'] == '没发出去：你在这个群被禁言了' and 'platform_receipt' not in row
    assert '你在这个群被禁言了' in lane.calls[0]['messages'][-1]['content']
    store.db.own_mutes.delete_many({})
    ep, _ = at_turn(store, 'at-2')
    assert 'muted_here_from_program' not in ep['context'], 'nothing while not muted'


def test_a_visit_turn_carries_the_line_and_her_places_mark_the_group_while_letting_her_go(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr012_visits import PLACE, group_world, home_beat, line, view
    from test_engineering_m1 import THINK
    service = group_world(store)
    line(store, 'g1', 'm-old', '周末大家都在干嘛', minutes_ago=120)
    scene = store.db.scenes.find_one({'_id': 'g1'})
    until = datetime.now(timezone.utc) + timedelta(days=29)
    own_mute.apply(store, scene, muted=True, source='lookup', until=until.isoformat())
    [row] = view(store, service)['items']
    assert row['muted_you'].startswith('你在这个群被禁言了，到 ') and '谁禁的不知道' in row['muted_you']
    assert '说话发不出去' in row['muted_you'] and row['can_visit'] == '可以去', 'reading is fine'
    home = FakeLane(store, [FakeTurn([THINK, ('visit', {'place': PLACE, 'intent': 'check_in'}),
                                      ('stay_silent', {'reason': '出门了'})], '')])
    coordinator = Coordinator(store, home)
    coordinator.scheduler = service
    assert coordinator.ingest(home_beat(store))['state'] == 'COMMITTED'
    _, event_id, scene_id, person = service.controller.offers[-1]
    visit_event = {'event_id': event_id, 'scene_id': scene_id, 'person_id': person, 'adapter_id': 'visit',
                   'episode_kind': 'visit', 'text': service.controller.texts[-1], **service.controller.envelopes[-1]}
    visit = Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'reason': '只看看'})], '')])).ingest(
        visit_event)
    assert visit['state'] in ('COMMITTED', 'WAITING_TASK'), visit.get('failure')
    assert visit['context']['muted_here_from_program'].startswith('你在这个群被禁言了')
    assert list(visit['context'])[-2:] == ['muted_here_from_program', 'event']
    assert json.dumps(visit['context'], ensure_ascii=False).count('你在这个群被禁言了') == 1
