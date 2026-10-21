"""Her own line taken back (her ask, the owner's yes, 2026-10-18): `speak`'s `recall` part names her line by its
number with a reason. Still queued, it is cancelled and never leaves; delivered within the platform's window, the
adapter recalls it; later, it is refused with what she can do instead; what came of it is in her history either way."""
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

from asuna import role_tools
from asuna.config import ROOT, character_id
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import THINK
from test_group_admin import SCENE, bridge
from test_reply_actions import mention, world


def her_line(store, seq, text='周六三点集合', state='DELIVERED', ago=30, pmid='pm-1'):
    sent = (datetime.now(timezone.utc) - timedelta(seconds=ago)).isoformat()
    store.put('messages', {'_id': 'mine-%d' % seq, 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                           'direction': 'outbound', 'author': character_id(store.config),
                           'phase': 'SPEAK', 'text': text, 'scene_seq': seq, 'delivery_state': state,
                           'episode_id': 'ep-old', 'receipt_at': sent,
                           **({'platform_message_id': pmid} if state == 'DELIVERED' else {})})
    store.db.scenes.update_one({'_id': SCENE}, {'$max': {'sequence': seq}})


def speak(store, key, parts):
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': parts})])])
    ep = Coordinator(store, lane).ingest(mention(key), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    rows = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}).sort('scene_seq', 1))
    return result, ok, rows


@pytest.fixture
def group(store):
    world(store)
    return store


def test_a_delivered_line_within_the_window_is_recalled_with_her_reason(group):
    her_line(group, 50, ago=30, pmid='pm-50')
    result, ok, [row] = speak(group, 'r-1', [{'kind': 'recall', 'line': '〔50〕', 'why': '时间说错了，是两点'}])
    assert ok, result
    assert row['action'] == {'kind': 'recall', 'message_id': 'pm-50', 'line': 'mine-50'}
    assert re.fullmatch(r'撤回 〔50〕 你 \d+/\d+ \d\d:\d\d：周六三点集合（为什么：时间说错了，是两点）' + re.escape(role_tools.ACTION_MARK),
                        row['text'])
    assert result['recall'] == role_tools.RECALL_QUEUED % 50 and '还没确认' in result['recall']


def test_a_line_still_queued_is_cancelled_and_never_leaves(group):
    her_line(group, 51, state='QUEUED_EXTERNAL')
    from asuna.context import ContextBuilder
    _, context, _ = ContextBuilder(group).prepare(mention('r-2a'))
    [shown] = [r for r in context.get('undelivered_outbound_not_public') or [] if r.get('_id') == 'mine-51']
    assert shown['delivery_state'] == '排着队，还没发出去', 'it reads as not sent, as recall takes it'
    result, ok, rows = speak(group, 'r-2', [{'kind': 'recall', 'line': '51', 'why': '发错群了'}])
    assert ok and rows == [], 'a cancel is no outbox row'
    row = group.db.messages.find_one({'_id': 'mine-51'})
    assert row['delivery_state'] == role_tools.CANCELLED_BY_HER and row['cancelled']['why'] == '发错群了'
    assert result['recall'] == role_tools.RECALL_CANCELLED % 51 and result['note'] == '这次没发新的。'
    assert bridge(group).claim('qq', supports=['recall'])['items'] == [], 'nothing of it is claimed'


def test_past_the_window_it_is_refused_with_what_she_can_do(group):
    her_line(group, 52, ago=600)
    result, ok, rows = speak(group, 'r-3', [{'kind': 'recall', 'line': '52', 'why': '说错了'}])
    assert not ok and rows == []
    assert '超过 2 分钟' in str(result) and '补一句，或者引它改口' in str(result)


def test_only_her_own_and_a_reason_within_its_limit(group):
    group.put('messages', {'_id': 'theirs', 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                           'direction': 'inbound', 'author': 'qq:20002', 'text': '广告', 'scene_seq': 53,
                           'event': {'channel': {'platform_event_id': 'pe-53'}}})
    result, ok, _ = speak(group, 'r-4', [{'kind': 'recall', 'line': '53', 'why': 'x'}])
    assert not ok and role_tools.RECALL_NOT_YOURS in str(result)
    her_line(group, 54)
    result, ok, _ = speak(group, 'r-5', [{'kind': 'recall', 'line': '54'}])
    assert not ok and '要写 why' in str(result)
    result, ok, _ = speak(group, 'r-6', [{'kind': 'recall', 'line': '54', 'why': '长' * 101}])
    assert not ok and 'why 太长了：101 字，要求 80 字以内，超了 21 字' in str(result)


def test_what_came_of_it_is_in_her_history_either_way(group):
    her_line(group, 55, pmid='pm-55')
    _, ok, [row] = speak(group, 'r-7', [{'kind': 'recall', 'line': '55', 'why': '说错了'}])
    assert ok
    channels = bridge(group)
    group.db.messages.update_one({'_id': row['_id']}, {'$unset': {'not_before': ''}})
    [item] = channels.claim('qq', supports=['recall'])['items']
    assert item['action']['kind'] == 'recall' and item['action']['message_id'] == 'pm-55'
    channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                                                    'response': {'retcode': 0}})
    assert group.db.messages.find_one({'_id': 'mine-55'}).get('recalled_at'), 'the line says it was taken back'
    her_line(group, 56, pmid='pm-56')
    _, ok, [row] = speak(group, 'r-8', [{'kind': 'recall', 'line': '56', 'why': '说错了'}])
    group.db.messages.update_one({'_id': row['_id']}, {'$unset': {'not_before': ''}})
    [item] = channels.claim('qq', supports=['recall'])['items']
    channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'failed',
                                                    'response': {'retcode': 1200, 'reason': 'too late'}})
    from asuna.context import ContextBuilder
    _, context, _ = ContextBuilder(group).prepare(mention('r-9'))
    [shown] = [r for r in context.get('undelivered_outbound_not_public') or [] if r.get('_id') == row['_id']] or [None]
    assert shown and shown['delivery_state'].startswith('撤回没成：平台没执行'), context.keys()


def test_napcat_takes_back_her_own_message_with_delete_msg():
    adapter = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
    sys.path[:0] = [str(adapter), str(adapter / 'vendor')]
    from qqadapter.outbound import Outbound
    call = Outbound.action_call({'target': {'type': 'group', 'id': '80000'},
                                 'action': {'kind': 'recall', 'message_id': '12345', 'line': 'mine-1'}})
    assert call == ('delete_msg', {'message_id': 12345})
