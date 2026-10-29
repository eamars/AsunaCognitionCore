"""Platform notices as one-off lines (ADR-064 phase 1): the adapter projects every kind and counts it, posts the kinds
of her first batch; the host passes a line on as the program's, through the same gates as a message, holds a group
notice that starts no turn for that group's next turn only, and brings requests and news about her own account to
her home, where group_action answers a request."""
import json
import sys
from types import SimpleNamespace

import pytest

from asuna import notices
from asuna.config import ROOT

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter import fixtures, inbound, notices as adapter_notices   # noqa: E402
from qqadapter.outbound import Outbound                                # noqa: E402

CFG = fixtures.load_config()
OWN, G1 = fixtures.ACCOUNT, fixtures.GROUPS[0]
MEMBER, OTHER = '900000101', '900000102'          # members of G1 in the fixtures
AT = 1_800_000_000


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


def test_the_words_that_teach_a_call_use_the_names_she_is_shown():
    """What the program tells her to write must be what the tool takes (ADR-077 fact check: two of them taught
    retired names, so following them was refused)."""
    from asuna import context, notices, role_tools
    shown = role_tools.TOOLS['group_action']['parameters']
    assert 'do 写 accept' in notices.ANSWER_HINT and 'do' in shown and 'kind' not in shown
    assert '[表情包:' not in context.CHAIN_NOTE and 'kind=sticker' in context.CHAIN_NOTE
    import inspect
    assert 'affect_adopt' not in inspect.getsource(context) and 'affect_adopt' not in role_tools.TOOLS
    assert "visibility 写成 private" not in inspect.getsource(role_tools)
    assert 'owner_private' in role_tools.TOOLS['promote_memory']['parameters']['visibility']['enum']
