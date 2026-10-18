"""Platform notices as one-off lines (ADR-064 phase 1): the adapter projects every kind and counts it, posts the kinds
of her first batch; the host passes a line on as the program's, through the same gates as a message, holds a group
notice that starts no turn for that group's next turn only, and brings requests and news about her own account to
her home, where group_action answers a request."""
import re
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from asuna import attend, notices
from asuna.channels import Channels
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.people import People
from asuna.state import Denied, now
from test_people import BOT, GROUP, SCENE, row, setup as people_setup

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import fixtures, inbound, notices as adapter_notices   # noqa: E402
from qqadapter.outbound import Outbound                                # noqa: E402
from reply_parts import said

CFG = fixtures.load_config()
OWN, G1 = fixtures.ACCOUNT, fixtures.GROUPS[0]
MEMBER, OTHER = '900000101', '900000102'          # members of G1 in the fixtures
AT = 1_800_000_000
STAMP = r' \d{1,2}/\d{1,2} \d{2}:\d{2}'              # a pointed-at line's time, as its label line has it


def notice(notice_type, sub_type=None, group=G1, **fields):
    event = {'post_type': 'notice', 'notice_type': notice_type, 'self_id': int(OWN), 'time': AT, **fields}
    if sub_type:
        event['sub_type'] = sub_type
    if group:
        event['group_id'] = int(group)
    return event


def request(request_type, sub_type=None, **fields):
    return {'post_type': 'request', 'request_type': request_type, 'self_id': int(OWN), 'time': AT, 'flag': 'f-1',
            **({'sub_type': sub_type} if sub_type else {}), **fields}


EVERY_KIND = [
    notice('group_recall', user_id=int(MEMBER), operator_id=int(MEMBER), message_id=5),
    notice('friend_recall', group=None, user_id=int(MEMBER), message_id=5),
    notice('notify', 'poke', user_id=int(MEMBER), target_id=int(OWN)),
    notice('notify', 'poke', user_id=int(MEMBER), target_id=int(OTHER)),
    notice('group_msg_emoji_like', user_id=int(MEMBER), message_id=5, likes=[{'emoji_id': '76', 'count': 1}]),
    notice('group_increase', 'approve', user_id=int(MEMBER), operator_id=int(OTHER)),
    notice('group_decrease', 'leave', user_id=int(MEMBER), operator_id=int(MEMBER)),
    notice('group_decrease', 'kick', user_id=int(MEMBER), operator_id=int(OTHER)),
    notice('group_decrease', 'kick_me', user_id=int(OWN), operator_id=int(OTHER)),
    notice('group_decrease', 'disband', user_id=int(OWN), operator_id=int(OTHER)),
    notice('group_ban', 'ban', user_id=int(MEMBER), operator_id=int(OTHER), duration=600),
    notice('group_ban', 'lift_ban', user_id=int(MEMBER), operator_id=int(OTHER), duration=0),
    notice('group_admin', 'set', user_id=int(MEMBER)),
    notice('group_admin', 'set', user_id=int(OWN)),
    notice('group_card', user_id=int(MEMBER), card_new='新', card_old='旧'),
    notice('notify', 'title', user_id=int(MEMBER), title='大佬'),
    notice('notify', 'group_name', user_id=int(MEMBER), name_new='新群名'),
    notice('essence', 'add', sender_id=int(MEMBER), operator_id=int(OTHER), message_id=5),
    notice('group_upload', user_id=int(MEMBER), file={'name': 'a.pdf', 'size': 1}),
    notice('notify', 'profile_like', group=None, operator_id=int(MEMBER), times=1),
    notice('notify', 'gray_tip', user_id=int(MEMBER), content='提示'),
    notice('friend_add', group=None, user_id=int(MEMBER)),
    notice('bot_offline', group=None, user_id=int(OWN)),
    request('friend', user_id=int(MEMBER), comment='你好'),
    request('group', 'add', group_id=int(G1), user_id=int(MEMBER), comment='想进'),
    request('group', 'invite', group_id=int('900000088'), user_id=int(MEMBER)),
]


# ---- the adapter --------------------------------------------------------------------------------------------------
def test_every_kind_in_the_table_reads_in_words_and_no_platform_name_reaches_her():
    kinds = set()
    for event in EVERY_KIND:
        proj = adapter_notices.project(event, OWN)
        assert proj is not None, event
        kinds.add(proj['kind'])
        words = proj['words'].replace('{line}', '').replace('{g}', '')
        assert '{' not in words and '_' not in words and words, proj
        assert OWN not in words and str(AT) not in words
    assert {'recall', 'poke_you', 'poke', 'reaction', 'join', 'kick', 'kicked_you', 'mute', 'admin', 'admin_you',
            'card', 'request_friend', 'request_join', 'request_invite'} <= kinds
    unknown = notice('something_new', user_id=int(MEMBER))
    assert adapter_notices.kind_of(unknown) == ('notice:something_new', False)
    assert adapter_notices.project(unknown, OWN) is None, 'an unknown kind is counted, not shown'


def test_the_words_say_who_whom_how_long_and_the_lift():
    mute = adapter_notices.project(EVERY_KIND[10], OWN)
    assert (mute['actor'], mute['words'], mute['people']) == (OTHER, '禁言了 @%s 10 分钟' % MEMBER, [MEMBER])
    assert adapter_notices.project(EVERY_KIND[11], OWN)['words'] == '解除了 @%s 的禁言' % MEMBER
    assert adapter_notices.project(notice('group_ban', 'ban', user_id=0, operator_id=int(OTHER), duration=-1),
                                   OWN)['words'] == '开了全员禁言'
    assert adapter_notices.project(notice('group_ban', 'ban', user_id=int(OWN), operator_id=int(OTHER), duration=60),
                                   OWN) is None, 'her own mute is a state (mutes.py)'
    assert adapter_notices.project(EVERY_KIND[2], OWN)['words'] == '戳了戳你'
    assert adapter_notices.project(EVERY_KIND[4], OWN)['words'] == '给{line}点了「%s」' % adapter_notices.faces.BY_ID['76']
    yours = adapter_notices.project(notice('group_recall', user_id=int(OWN), operator_id=int(OTHER), message_id=9), OWN)
    assert yours['words'] == '撤回了你的{line}' and yours['actor'] == OTHER
    assert adapter_notices.project(notice('group_recall', user_id=int(MEMBER), operator_id=int(OWN), message_id=9),
                                   OWN) is None, 'her own doing'
    friend = adapter_notices.project(EVERY_KIND[23], OWN)
    assert friend['where'] == 'home' and friend['request'] == {'flag': 'f-1', 'type': 'friend'}
    assert friend['words'] == '想加你好友，附言「你好」'
    tricky = adapter_notices.project(request('friend', user_id=int(MEMBER), comment='{line}{g}'), OWN)
    assert '{' not in tricky['words'], 'a note cannot fill a slot'


class Recorder(SimpleNamespace):
    def __init__(self):
        super().__init__(posted=[])

    def post_notice(self, body):
        self.posted.append(body)
        return SimpleNamespace(kind='accepted', code=200, obj={'status': 'held'})


def adapter(tmp_path):
    from qqadapter.service import Adapter
    return Adapter(CFG, str(tmp_path))


def test_the_adapter_posts_her_batch_counts_every_kind_and_keeps_the_counts(tmp_path):
    a = adapter(tmp_path)
    a.on_event(EVERY_KIND[2])                                # a poke at her: posted as a gated line
    a.on_event(EVERY_KIND[3])                                # a poke at someone else: counted, not shown
    a.on_event(notice('something_new', user_id=int(MEMBER)))
    a.on_event(EVERY_KIND[23])                               # a friend request: to her home
    a.on_event({'post_type': 'meta_event', 'meta_event_type': 'heartbeat', 'self_id': int(OWN)})
    [path] = a.journal.spool_list('inbound')
    envelope = a.journal.read_json(path)['envelope']
    assert envelope['sender_id'] == MEMBER and envelope['group_id'] == G1 and envelope['text'] == '戳了戳你'
    assert envelope['raw'] == {'asuna_notice': {'kind': 'poke_you', 'words_version': 1, 'gate': 'poked'}}
    assert a.home_notices.jobs.qsize() == 1
    today = a.health_snapshot()['notices']['today']
    assert today['poke_you:posted'] == 1 and today['poke:not_shown'] == 1 and today['request_friend:home'] == 1
    assert today['notice:something_new:unknown'] == 1 and today['meta:not_projected'] == 1
    a.notice_counts.save()
    assert adapter(tmp_path).notice_counts.summary()['last_7_days']['poke'] == 1, 'counts survive a restart'


def test_a_notice_passes_the_gates_of_a_message():
    seen = inbound.SeenLRU(64)
    poke = adapter_notices.project(EVERY_KIND[2], OWN)
    assert adapter_notices.envelope(poke, EVERY_KIND[2], CFG, seen)[0] is not None
    assert adapter_notices.envelope(poke, EVERY_KIND[2], CFG, seen) == (None, 'duplicate_local')
    outsider = adapter_notices.project(notice('notify', 'poke', user_id=int(fixtures.OUTSIDER), target_id=int(OWN)), OWN)
    assert adapter_notices.envelope(outsider, EVERY_KIND[2], CFG, seen)[1] == 'unauthorized_group_member'
    stranger = adapter_notices.project(notice('notify', 'poke', group=fixtures.UNKNOWN_GROUP, user_id=int(MEMBER),
                                              target_id=int(OWN)), OWN)
    assert adapter_notices.envelope(stranger, EVERY_KIND[2], CFG, seen)[1] == 'group_not_allowed'


def test_the_home_poster_names_people_and_groups_by_read_only_calls():
    calls = []

    class Api:
        def api_call(self, action, params, timeout, meta):
            calls.append(action)
            return {'retcode': 0, 'data': {'nickname': '小{明}', 'group_name': '新群'}}
    host = Recorder()
    poster = adapter_notices.HomePoster(CFG, Api(), host, SimpleNamespace(inc=lambda *a: None), log=lambda _m: None)
    poster.post(adapter_notices.project(EVERY_KIND[25], OWN), AT)
    assert calls == ['get_stranger_info', 'get_group_info']
    assert host.posted[0] == {'kind': 'request_invite', 'words': '邀请你进群{g}', 'actor_name': '小｛明｝',
                              'group_id': '900000088', 'group_name': '新群', 'at': AT,
                              'request': {'flag': 'f-1', 'type': 'group', 'sub_type': 'invite'}}


def test_the_adapter_answers_a_request_by_its_flag_only():
    item = {'target': {'type': 'request', 'id': 'friend'}, 'admin': {'kind': 'accept', 'flag': 'f-1', 'request': 'friend'}}
    assert Outbound.admin_call(item, OWN) == ('set_friend_add_request', {'flag': 'f-1', 'approve': True})
    group = {'target': {'type': 'request', 'id': 'group'},
             'admin': {'kind': 'decline', 'flag': 'f-2', 'request': 'group', 'sub_type': 'invite'}}
    assert Outbound.admin_call(group, OWN) == ('set_group_add_request', {'flag': 'f-2', 'sub_type': 'invite', 'approve': False})
    assert Outbound.admin_call({**item, 'admin': {'kind': 'kick', 'flag': 'f'}}, OWN) == (None, 'bad_request_answer')


# ---- the host -----------------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean():
    notices.forget()
    yield
    notices.forget()


MEMBERS = {'20002': 'qq:20002', '20003': 'qq:20003', '20004': 'qq:20004'}


def world(store, her_role='member'):
    scene = people_setup(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'members': list(MEMBERS.values()), 'channel_id': 'qq'}})
    store.config['character_id'] = 'demo'
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': 'x' * 24, 'routes': {'g': {
        'scene_id': SCENE, 'target': {'type': 'group', 'id': GROUP},
        'members': {sender: {'person_id': person} for sender, person in MEMBERS.items()}}}}}
    people = People(store)
    for number, card in ((20002, '阿杰'), (20003, '老王')):
        item = row(number, '大家好呀', card=card, rid='in-%d' % number)
        item['event']['raw']['asuna_self'] = {'role': her_role}
        store.put('messages', {**item, 'scene_seq': number - 20000, 'event': {**item['event'], 'channel': {
            **item['event']['channel'], 'platform_event_id': '7%d' % number}}})
        people.transcript(scene, item)
    return {**scene, 'members': list(MEMBERS.values()), 'channel_id': 'qq'}


def bridge(store):
    received = []
    controller = SimpleNamespace(app=SimpleNamespace(store=store, config=store.config), stopping=threading.Event(),
                                 reconfiguring=False, ingress_lock=threading.RLock(),
                                 receive=lambda event: received.append(event) or {'status': 'accepted'},
                                 offers=[], offer_internal=lambda *args: controller.offers.append(args))
    return Channels(controller), received, controller


def posted(sender, text, kind, gate=None, line=None, event_id=None, mentions=()):
    block = {'kind': kind, 'words_version': 1, **({'gate': gate} if gate else {}), **({'line': line} if line else {})}
    return {'route_id': 'g', 'account_id': BOT, 'sender_id': sender, 'event_id': event_id or 'notice-%s-%s' % (kind, sender),
            'text': text, 'group_id': GROUP, 'mentioned_account_ids': list(mentions), 'raw': {'asuna_notice': block},
            'occurred_at': '2026-10-04T02:00:00Z'}


def test_a_poke_at_her_goes_through_the_gate_and_reads_as_the_programs_line(store):
    scene = world(store)
    channels, received, _ = bridge(store)
    assert channels.receive('qq', posted('20002', '戳了戳你', 'poke_you', 'poked')) == {'status': 'accepted'}
    [event] = received
    assert event['group_context']['wake_reason'] == 'poked' and attend.gated(scene, event)
    assert event['raw']['asuna_notice'] == {'kind': 'poke_you', 'gate': 'poked'}
    line = People(store).transcript(scene, {'_id': 'n', 'author': 'qq:20002', 'text': event['text'],
                                            'received_at': now(), 'event': event})
    assert line.split('\n')[0].endswith('（平台通知）') and line.split('\n')[1] == '  戳了戳你'
    typed = People(store).transcript(scene, row(20002, '[阿杰 #1] 02:00（平台通知）戳了戳你', card='阿杰'))
    assert '（平台通知）' not in typed.split('\n')[0], 'typed text that looks like a notice stays their words'
    assert 'poked' in attend.GATED and 'reacted' in attend.GATED


def test_a_blocked_persons_notice_reaches_her_nowhere(store):
    world(store)
    from asuna import switches
    switches.set_switch(store, {'_id': 'ep', 'persona': 'demo', 'scope_key': 'x'}, 'block', label='[阿杰 #1]',
                        person_id='qq:20002')
    channels, received, _ = bridge(store)
    assert channels.receive('qq', posted('20002', '戳了戳你', 'poke_you', 'poked')) == {'status': 'dropped'}
    assert received == []


def test_a_reaction_names_her_line_like_any_pointer_and_one_between_others_is_kept_without_a_look(store):
    world(store)
    store.put('messages', {'_id': 'out-1', 'scene_id': SCENE, 'direction': 'outbound', 'author': 'demo', 'text': '晚安',
                           'delivery_state': 'DELIVERED', 'platform_message_id': '555',
                           'receipt_at': '2026-10-04T01:30:00+00:00', 'scene_seq': 9})
    channels, received, _ = bridge(store)
    mine = posted('20003', '给{line}点了「赞」', 'reaction', 'reacted', {'message_id': '555', 'mine': True})
    # Regression (owner 2026-10-16): in a group she lets rest a reaction to her line was held, not looked at, and a
    # restart lost it; 18 of her 21 groups rest. A notice that asks for a look gets it anywhere: her gate decides.
    assert channels.receive('qq', mine) == {'status': 'accepted'}
    assert received[0]['group_context']['wake_reason'] == 'reacted'
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'focus_active': True}})
    assert channels.receive('qq', {**mine, 'event_id': 'again'}) == {'status': 'accepted'}
    # ADR-079 §9.3: the line it is on reads as every pointer does (speaker, hers as 你, and first words).
    assert received[0]['text'] == '给 你 10/4 14:30：晚安 点了「赞」'
    store.db.messages.update_one({'_id': 'in-20002'}, {'$set': {'received_at': now()}})
    other = posted('20003', '给{line}点了「赞」', 'reaction', 'reacted', {'message_id': '720002', 'mine': True},
                   event_id='notice-reaction-2')
    assert channels.receive('qq', other) == {'status': 'held'} and len(received) == 2, 'kept, asks for no look'
    [line] = notices.take(store, store.db.scenes.find_one({'_id': SCENE}))['items']
    assert line.startswith(notices.REACTIONS_HEAD) and re.search(r'给 \[阿杰 #1\]%s：' % STAMP, line) and '点了「赞」' in line


def test_reactions_between_others_fold_into_one_line_with_the_older_ones_counted(store):
    scene = world(store)
    channels, received, _ = bridge(store)
    for index in range(7):
        store.put('messages', {'_id': 'r%d' % index, 'scene_id': SCENE, 'direction': 'inbound', 'author': 'qq:20004',
                               'text': '第%d句' % index, 'received_at': now(), 'scene_seq': 200 + index,
                               'event': {'channel': {'platform_event_id': 'z%d' % index}}})
        channels.receive('qq', posted('20003', '给{line}点了「赞」', 'reaction', 'reacted',
                                      {'message_id': 'z%d' % index, 'mine': True}, event_id='rz%d' % index))
    assert received == [], 'none of them asks for a look'
    [line] = notices.take(store, scene)['items']
    assert line.startswith(notices.REACTIONS_HEAD) and line.count('点了「赞」') == notices.REACTIONS_MAX
    assert '第6句' in line and '第0句' not in line and '另有 2 条较早的' in line


def test_a_recall_in_a_group_is_kept_across_a_restart_and_shown_once_naming_the_line(store):
    scene = world(store)
    channels, received, _ = bridge(store)
    long_line = '这是一句很长很长的话' * 6
    store.db.messages.update_one({'_id': 'in-20002'}, {'$set': {'text': long_line, 'received_at': now()}})
    before = store.db.messages.count_documents({})
    recall = posted('20002', '撤回了{line}', 'recall', line={'message_id': '720002', 'mine': False})
    assert channels.receive('qq', recall) == {'status': 'held'}
    assert received == [] and store.db.messages.count_documents({}) == before, 'not a line of the conversation'
    notices.forget()                                   # a Host restart: what was not shown yet is kept (ADR-079)
    shown = notices.take(store, scene)
    [item] = shown['items']
    assert item.startswith('[阿杰 #1] ') and re.search(r'（平台通知）撤回了 \[阿杰 #1\]%s：%s…' % (STAMP, long_line[:40]), item)
    assert notices.take(store, scene) is None, 'once'
    assert not store.db.artifacts.find_one({'kind': notices.HELD_KIND}), 'shown, it is gone'
    gone = posted('20003', '撤回了{line}', 'recall', line={'message_id': '999', 'mine': False}, event_id='r2')
    channels.receive('qq', gone)
    assert notices.take(store, scene)['items'][0].endswith('（平台通知）撤回了一条消息')


def test_held_lines_of_one_kind_fold_and_the_cap_counts_after_folding(store):
    scene = world(store)
    channels, _, _ = bridge(store)
    for sender in ('20002', '20003'):
        channels.receive('qq', posted(sender, '撤回了{line}', 'recall', line={'message_id': '1', 'mine': False},
                                      event_id='r-' + sender))
    [folded] = notices.take(store, scene)['items']
    assert folded.startswith('[阿杰 #1]、[老王 #2] ') and folded.endswith('（平台通知）撤回了一条消息')
    for index in range(12):
        store.put('messages', {'_id': 'q%d' % index, 'scene_id': SCENE, 'direction': 'inbound', 'author': 'qq:20004',
                               'text': '第%d句' % index, 'received_at': now(), 'scene_seq': 100 + index,
                               'event': {'channel': {'platform_event_id': 'x%d' % index}}})
        channels.receive('qq', posted('20004', '撤回了{line}', 'recall',
                                      line={'message_id': 'x%d' % index, 'mine': False}, event_id='y%d' % index))
    shown = notices.take(store, scene)
    assert shown['items'][-1].endswith('：第11句')
    assert len(shown['items']) == notices.HELD_MAX and shown['more'] == '还有 2 条较早的通知没列出'


def test_the_gate_shows_held_notices_once_and_a_quiet_answer_ends_them(store):
    scene = world(store)
    channels, received, _ = bridge(store)
    channels.receive('qq', posted('20003', '撤回了{line}', 'recall', line={'message_id': '1', 'mine': False}))
    channels.receive('qq', posted('20002', '戳了戳你', 'poke_you', 'poked'))
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.attend = FakeLane(store, [LaneResult('不理：没什么事')])
    ep = coordinator.ingest(received[-1], persona='P1')
    asked = coordinator.attend.calls[0]['messages'][-1]['content']
    assert ep['attend']['choice'] == 'quiet' and '撤回了一条消息' in asked and attend.GATED['poked'] in asked
    assert notices.take(store, scene) is None, 'seen once at the gate'


def test_a_turn_shows_the_held_notice_once_without_repeating_a_line(store):
    scene = world(store)
    channels, received, _ = bridge(store)
    store.db.messages.update_one({'_id': 'in-20002'}, {'$set': {'received_at': now()}})
    channels.receive('qq', posted('20003', '撤回了{line}', 'recall', line={'message_id': '720002', 'mine': False}))
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '有人叫我。'}), said('在的')])])
    event = {'event_id': 'at-1', 'scene_id': SCENE, 'person_id': 'qq:20004', 'text': '@演示 在吗',
             'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 't', 'mentioned_account_ids': [BOT]},
             'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP}, 'sender_id': '20004',
                         'platform_event_id': 'at-1'}}
    ep = Coordinator(store, lane).ingest(event, persona='P1')
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    [item] = ep['context']['notices_from_program']['items']
    assert re.search(r'（平台通知）撤回了 \[阿杰 #1\]%s：大家好呀' % STAMP, item)
    sent = lane.calls[0]['messages'][-1]['content']
    assert sent.count('撤回了 [阿杰 #1]') == 1, 'the notice once, in its own block'
    assert notices.take(store, scene) is None


def test_a_poke_in_a_private_chat_wakes_her_and_is_her_turns_input(store):
    people_setup(store)
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': 'x' * 24, 'routes': {'d': {
        'scene_id': 'qq:%s:dm:20002' % BOT, 'sender_id': '20002', 'person_id': 'qq:20002',
        'target': {'type': 'dm', 'id': '20002'}}}}}
    store.put('scenes', {'_id': 'qq:%s:dm:20002' % BOT, 'kind': 'dm', 'scope_key': 'scene:dm', 'policy_epoch': 1,
                         'sequence': 0, 'channel_id': 'qq', 'members': ['qq:20002']})
    channels, received, _ = bridge(store)
    body = {'route_id': 'd', 'account_id': BOT, 'sender_id': '20002', 'event_id': 'notice-poke_you-x', 'text': '戳了戳你',
            'raw': {'asuna_notice': {'kind': 'poke_you'}}}
    assert channels.receive('qq', body) == {'status': 'accepted'}
    assert received[0]['text'] == '戳了戳你' and 'group_context' not in received[0]


# ---- her home: requests and her own account ------------------------------------------------------------------------
def home_world(store):
    world(store, 'admin')
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': 'dm-a', 'person_id': 'local-user'}


def test_requests_and_news_about_her_reach_her_home_in_one_event_a_minute(store):
    home_world(store)
    channels, _, controller = bridge(store)
    assert notices.home(store, controller, 'qq', {'kind': 'request_friend', 'words': '想加你好友，附言「你好」',
                                                  'actor_name': '小明', 'request': {'flag': 'f-1', 'type': 'friend'},
                                                  'at': AT}, delay=3600) == {'status': 'held'}
    notices.home(store, controller, 'qq', {'kind': 'kicked_you', 'words': '把你移出了群{g}', 'actor_name': '[老王 #2]',
                                           'group_id': GROUP}, delay=3600)
    assert controller.offers == [], 'held for the minute'
    event_id = notices._send_home(store, controller)
    [(kind, sent_id, scene_id, person, text)] = controller.offers
    assert (kind, sent_id, scene_id, person) == ('presence', event_id, 'dm-a', 'local-user')
    assert text.startswith(notices.HOME_HEAD) and '「小明」想加你好友，附言「你好」（请求1' in text
    assert '「老王 2」把你移出了群' in text and '[老王' not in text, 'a name shaped like a label reads as text'
    with pytest.raises(PermissionError, match='NOTICE_FIELD_DENIED'):
        notices.home(store, controller, 'qq', {'kind': 'x', 'words': 'y', 'text': 'z'})


def test_she_answers_a_listed_request_at_home_and_the_adapter_gets_its_flag(store):
    from asuna import group_admin
    from asuna.role_tools import abilities
    home_world(store)
    _, _, controller = bridge(store)
    notices.home(store, controller, 'qq', {'kind': 'request_friend', 'words': '想加你好友',
                                           'request': {'flag': 'f-9', 'type': 'friend'}}, delay=3600)
    ep = {'_id': 'ep-home', 'scene_id': 'dm-a', 'person_id': 'local-user', 'persona': 'demo',
          'manifest': {'session_class': 'owner_private'}}
    assert 'group_action' in abilities(store, ep), 'listed at home, the same every turn'
    with pytest.raises(Denied, match='GROUP_ACTION_REQUEST_NOT_FOUND'):
        notices.answer(store, ep, {'kind': 'accept', 'who': '请求7'}, key='k0')
    result = notices.answer(store, ep, {'kind': 'accept', 'who': '请求1', 'reason': '认识'}, key='k1')
    assert result == {'action': '接受请求', 'who': '请求1', 'state': '已交给平台，等确认'}
    item = group_admin.claim(store, 'qq')
    assert item['target'] == {'type': 'request', 'id': 'friend'}
    assert item['admin'] == {'kind': 'accept', 'flag': 'f-9', 'request': 'friend'}
    assert notices.pending(store) == {}, 'answered once'


def test_a_request_keeps_its_number_across_a_restart_and_is_listed_again_until_answered(store):
    from asuna import group_admin
    home_world(store)
    _, _, controller = bridge(store)
    for flag in ('f-1', 'f-2', 'f-1'):
        notices.home(store, controller, 'qq', {'kind': 'request_friend', 'words': '想加你好友',
                                               'request': {'flag': flag, 'type': 'friend'}}, delay=3600)
    assert sorted(notices.pending(store)) == ['请求1', '请求2'], 'the same flag again is the same request'
    notices.forget()                                                # a Host restart: memory gone, Mongo kept
    assert sorted(notices.pending(store)) == ['请求1', '请求2']
    notices.remind_open(store, controller)
    text = controller.offers[-1][4]
    assert notices.OPEN_HEAD in text and '请求1' in text and '请求2' in text
    notices.home(store, controller, 'qq', {'kind': 'request_friend', 'words': '想加你好友',
                                           'request': {'flag': 'f-3', 'type': 'friend'}}, delay=3600)
    assert '请求3' in notices.pending(store), 'numbers go on after a restart, never reused'
    ep = {'_id': 'ep-home', 'scene_id': 'dm-a', 'person_id': 'local-user', 'persona': 'demo'}
    notices.answer(store, ep, {'kind': 'accept', 'who': '请求1'}, key='a1')
    notices.answer(store, ep, {'kind': 'decline', 'who': '2'}, key='a2')
    assert sorted(notices.pending(store)) == ['请求3'], 'answered ones wait for the platform, not for her'
    for state in ('platform_accepted', 'failed'):
        item = group_admin.claim(store, 'qq')
        group_admin.receipt(store, 'qq', item['publication_id'],
                            {'attempt_id': item['attempt_id'], 'status': state, 'response': {'retcode': 0}})
    states = {row['number']: row['state'] for row in store.db.artifacts.find({'kind': notices.REQUEST_KIND})}
    assert states == {1: 'answered', 2: 'gone', 3: 'open'}
    controller.offers.clear()
    notices.answer(store, ep, {'kind': 'accept', 'who': '请求3'}, key='a3')
    assert notices.remind_open(store, controller) is None and controller.offers == [], 'nothing open: no event'
