"""Her place in a group and what she may do as an admin (group_admin.py), and the adapter's side of it."""
import json
import sys

import pytest

from asuna import group_admin
from asuna.channels import kept_raw
from asuna.config import ROOT
from asuna.people import People
from asuna.state import Denied
from test_people import BOT, GROUP, SCENE, row, setup as people_setup

ADAPTER = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
sys.path[:0] = [str(ADAPTER), str(ADAPTER / 'vendor')]          # as adapter.py sets it up
from qqadapter.outbound import Outbound            # noqa: E402
from qqadapter.selfrole import SelfRoles           # noqa: E402


def setup(store, her_role='admin', admin_actions=True):
    for name in ('scenes', 'scene_people', 'messages', 'artifacts'):        # a test may set the group up twice
        store.db[name].delete_many({'scene_id': SCENE} if name != 'scenes' else {'_id': SCENE})
    scene = people_setup(store)
    members = ['qq:20001', 'qq:20002', 'qq:20003', 'qq:20004']
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'members': members, 'channel_id': 'qq'}})
    store.config['character_id'] = 'demo'
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': 'x' * 24, 'routes': {'g': {
        'scene_id': SCENE, 'target': {'type': 'group', 'id': GROUP}, 'members': {},
        **({} if admin_actions else {'admin_actions': False})}}}}
    scene = {**scene, 'members': members, 'channel_id': 'qq'}
    people = People(store)
    for number, card, role in ((20001, '小林', 'member'), (20002, '阿杰', 'member'), (20003, '老王', 'admin')):
        item = row(number, 'hi', card=card, role=role, rid='in-%d' % number)
        if her_role:
            item['event']['raw']['asuna_self'] = {'role': her_role}
        store.put('messages', {**item, 'event': {**item['event'], 'channel': {**item['event']['channel'],
                                                                              'platform_event_id': '7%d' % number}}})
        people.transcript(scene, item)
    return scene


def episode(store, source='in-20002'):
    return {'_id': source.replace('in-', ''), 'scene_id': SCENE, 'person_id': 'qq:20002', 'persona': 'demo'}


def test_only_her_own_role_in_a_group_is_kept_from_raw():
    group = {'person_id': 'qq:20002', 'channel': {'sender_id': '20002', 'target': {'type': 'group', 'id': GROUP}}}
    assert kept_raw(group, {'asuna_self': {'role': 'admin', 'extra': 1}})['asuna_self'] == {'role': 'admin'}
    assert 'asuna_self' not in kept_raw(group, {'asuna_self': {'role': 'god'}})
    dm = {'person_id': 'qq:20002', 'channel': {'sender_id': '20002', 'target': {'type': 'dm', 'id': '20002'}}}
    assert 'asuna_self' not in kept_raw(dm, {'asuna_self': {'role': 'admin'}})


def test_her_place_says_her_role_and_what_she_may_do(store):
    scene = setup(store, 'admin')
    people = People(store)
    assert people.self_role(scene) == 'admin'
    place = group_admin.place(people, scene)
    assert place['role'] == '你在这个群是管理员' and 'group_action' in place['admin']['how']
    member = setup(store, 'member')
    assert group_admin.place(People(store), member) == {'role': '你在这个群是普通成员'}
    off = setup(store, 'admin', admin_actions=False)
    assert 'admin' not in group_admin.place(People(store), off)
    assert 'qq:' not in json.dumps(place, ensure_ascii=False) and GROUP not in json.dumps(place, ensure_ascii=False)


def test_an_admin_action_is_checked_then_queued_without_numbers_in_her_words(store):
    setup(store, 'admin')
    result = group_admin.queue(store, episode(store), 0, {'kind': 'mute', 'who': '#2', 'duration': '10分钟', 'reason': '刷屏'})
    assert result == {'index': 0, 'action': '禁言', 'who': '[阿杰 #2]', 'duration': '10分钟', 'state': '已交给平台，等确认'}
    action = store.db.artifacts.find_one({'kind': 'group_action'})
    assert action['admin'] == {'kind': 'mute', 'account': '20002', 'seconds': 600} and action['state'] == 'QUEUED'
    recall = group_admin.queue(store, episode(store), 1, {'kind': 'recall', 'who': '[阿杰 #2]', 'which': '这条', 'reason': '广告'})
    assert recall['action'] == '撤回'
    assert store.db.artifacts.find_one({'admin.kind': 'recall'})['admin'] == {'kind': 'recall', 'message_id': '720002'}


@pytest.mark.parametrize('item, code', [
    ({'kind': 'kick', 'who': '[小林 #1]', 'reason': 'x'}, 'GROUP_ACTION_TARGET_PROTECTED'),      # the owner
    ({'kind': 'mute', 'who': '#3', 'duration': '1天', 'reason': 'x'}, 'GROUP_ACTION_TARGET_IS_ADMIN'),
    ({'kind': 'mute', 'who': '#2', 'reason': 'x'}, 'GROUP_ACTION_DURATION_REQUIRED'),
    ({'kind': 'kick', 'who': '没这个人', 'reason': 'x'}, 'GROUP_ACTION_TARGET_NOT_FOUND'),
])
def test_refusals_are_named(store, item, code):
    setup(store, 'admin')
    store.config['canonical_persons'] = {'qq:20001': 'local-user'}
    with pytest.raises(Denied, match=code):
        group_admin.queue(store, episode(store), 0, item)


def test_a_member_cannot_act_and_an_hour_has_a_cap(store):
    setup(store, 'member')
    with pytest.raises(Denied, match='GROUP_ACTION_NOT_AN_ADMIN'):
        group_admin.queue(store, episode(store), 0, {'kind': 'unmute', 'who': '#2', 'reason': 'x'})
    setup(store, 'owner')
    for index in range(group_admin.PER_HOUR):
        group_admin.queue(store, {**episode(store), '_id': 'e%d' % index}, 0, {'kind': 'unmute', 'who': '#2', 'reason': 'x'})
    with pytest.raises(Denied, match='GROUP_ACTION_HOURLY_LIMIT'):
        group_admin.queue(store, episode(store), 0, {'kind': 'unmute', 'who': '#2', 'reason': 'x'})


def test_the_outbox_hands_an_action_over_and_takes_the_platform_answer(store):
    setup(store, 'admin')
    group_admin.queue(store, episode(store), 0, {'kind': 'kick', 'who': '#2', 'reason': '骗子'})
    item = group_admin.claim(store, 'qq')
    assert item['admin'] == {'kind': 'kick', 'account': '20002'} and item['target'] == {'type': 'group', 'id': GROUP}
    assert group_admin.claim(store, 'qq') is None
    body = {'attempt_id': item['attempt_id'], 'status': 'platform_accepted', 'response': {'retcode': 0}}
    assert group_admin.receipt(store, 'qq', item['publication_id'], body) == {'status': 'DONE'}
    with pytest.raises(Denied, match='PUBLICATION_ATTEMPT_MISMATCH'):
        group_admin.receipt(store, 'qq', item['publication_id'], {**body, 'attempt_id': 'other'})


def test_her_group_notes_are_this_groups_own_document(store):
    from asuna.documents import DocumentStore
    scene = setup(store, 'member')
    docs = DocumentStore(store, 'demo')
    revision, block = group_admin.notes_block(docs, scene)
    assert revision is None and block['note'].startswith('你还没写过这个群的笔记')
    slug = group_admin.notes_slug(SCENE)
    assert GROUP not in slug and slug.startswith('group:')
    docs.apply(slug, {'doc': slug, 'op': 'append_section', 'heading': '群里的人', 'reason': '记下',
                      'visibility': 'public', 'inject': 'always'}, '#3 是管理员，说话直接。',
               base_revision_id=None, author='character', mutation_id='m1')
    _, block = group_admin.notes_block(docs, scene)
    assert block['sections'][0]['body'] == '#3 是管理员，说话直接。'


def test_the_adapter_maps_actions_to_napcat_calls_only():
    call = Outbound.admin_call
    group = {'type': 'group', 'id': '80000'}
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 600}}, '90000') == (
        'set_group_ban', {'group_id': 80000, 'user_id': 20002, 'duration': 600})
    assert call({'target': group, 'admin': {'kind': 'unmute', 'account': '20002'}}, '90000')[1]['duration'] == 0
    assert call({'target': group, 'admin': {'kind': 'kick', 'account': '20002'}}, '90000')[0] == 'set_group_kick'
    assert call({'target': group, 'admin': {'kind': 'recall', 'message_id': '7123'}}, '90000') == (
        'delete_msg', {'message_id': 7123})
    assert call({'target': group, 'admin': {'kind': 'kick', 'account': '90000'}}, '90000') == (None, 'bad_account')
    assert call({'target': group, 'admin': {'kind': 'mute', 'account': '20002', 'seconds': 5}}, '90000') == (None, 'bad_duration')
    assert call({'target': {'type': 'dm', 'id': '20002'}, 'admin': {'kind': 'kick', 'account': '20002'}}, '90000')[0] is None
    assert call({'target': group, 'admin': {'kind': 'set_group_admin', 'account': '20002'}}, '90000') == (None, 'unknown_admin_kind')


def test_the_adapter_reports_her_own_role_from_napcat():
    class Api:
        calls = 0

        def api_call(self, action, params, timeout=None):
            Api.calls += 1
            assert action == 'get_group_member_info' and params['user_id'] == 90000
            return {'retcode': 0, 'data': {'user_id': 90000, 'role': 'admin'}}
    roles = SelfRoles('90000')
    envelope = {'group_id': '80000', 'raw': {}}
    assert roles.attach(envelope, Api()) == 'admin' and envelope['raw']['asuna_self'] == {'role': 'admin'}
    roles.attach({'group_id': '80000', 'raw': {}}, Api())
    assert Api.calls == 1                                   # cached for the TTL


def test_a_turn_can_act_and_keep_notes_and_she_hears_the_result(store):
    from asuna.coordinator import Coordinator
    from asuna.documents import DocumentStore
    from asuna.lanes import FakeLane, FakeTurn
    setup(store, 'admin')
    mute = {'kind': 'mute', 'who': '#2', 'duration': '1分钟', 'reason': '连续刷屏'}
    notes = {'doc': 'group_notes', 'op': 'append_section', 'heading': '刷屏', 'reason': '记下做法',
             'body': '刷屏的先禁言一分钟。'}
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '他在刷屏，先禁言一分钟，再记下做法。'}),
                                      ('group_action', mute), ('write_document', notes)], '先禁言一分钟哦')])
    event = {'event_id': 'spam-1', 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': '@演示 刷屏',
             'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 't', 'mentioned_account_ids': [BOT]},
             'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP}, 'sender_id': '20002',
                         'platform_event_id': 'spam-1'}}
    ep = Coordinator(store, lane).ingest(event, persona='P1')
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    assert [call['phase'] for call in lane.calls] == ['TURN']           # one turn: the notes' body is in the call
    assert {'group_action', 'write_document'} <= set(lane.calls[0]['tools'])
    _, acted, wrote = lane.tool_results
    assert acted[5] and acted[4]['state'] == '已交给平台，等确认'          # she hears it is not done yet
    assert store.db.artifacts.find_one({'kind': 'group_action'})['admin'] == {'kind': 'mute', 'account': '20002', 'seconds': 60}
    assert wrote[5] and wrote[4]['doc'] == group_admin.notes_slug(SCENE), wrote
    _, written = DocumentStore(store, 'P1').read(group_admin.notes_slug(SCENE))
    assert written['sections'][0]['visibility'] == 'public' and written['sections'][0]['body'] == '刷屏的先禁言一分钟。'
    spoken = [row['text'] for row in store.db.messages.find({'episode_id': ep['_id'], 'direction': 'outbound'})]
    assert spoken == ['先禁言一分钟哦']
