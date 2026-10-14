"""ADR-064 phase 2, stage B: a poke and a reaction as parts of her reply. Each is a row in her history in the
program's words, marked as something she did; the adapter does it only when it declared it; its receipt has no
message id; a reaction a private chat refuses is not tried there again until the Host restarts."""
from asuna import role_tools
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import THINK
from test_group_admin import BOT, GROUP, SCENE, bridge, setup


def mention(key):
    return {'event_id': key, 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': '@演示 戳我一下',
            'group_context': {'wake_reason': 'mentioned_account', 'topic_id': key, 'mentioned_account_ids': [BOT]},
            'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                        'sender_id': '20002', 'platform_event_id': 'pe-' + key}}


def world(store):
    """The admin tests' group, where 20002 may be answered (the route lists them as a member)."""
    setup(store, 'member')
    store.config['channels']['qq']['routes']['g']['members'] = {'20002': {'person_id': 'qq:20002'}}


def turn(store, key, parts):
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': parts})])])
    ep = Coordinator(store, lane).ingest(mention(key), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    rows = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}).sort('scene_seq', 1))
    return ep, result, ok, rows


def test_a_poke_and_a_reaction_are_rows_in_her_words_marked_as_what_she_did(store):
    world(store)
    ep, result, ok, rows = turn(store, 'act-1', [{'kind': 'text', 'text': '来了'},
                                                 {'kind': 'poke', 'who': '阿杰'},
                                                 {'kind': 'react', 'who': '阿杰', 'line': '这条', 'face': '赞'}])
    assert ok and result['note'].startswith('发出 3 条，都排上了：1 text；2 poke [阿杰 #2]；3 react「赞」给 [阿杰 #2]'), result
    texts = [row['text'] for row in rows]
    assert texts[0] == '来了'
    assert texts[1] == '戳了戳 [阿杰 #2]' + role_tools.ACTION_MARK
    assert texts[2].startswith("给 [阿杰 #2] ") and texts[2].endswith('那句点了「赞」' + role_tools.ACTION_MARK)
    assert rows[1]['action'] == {'kind': 'poke', 'account': '20002'}
    assert rows[2]['action'] == {'kind': 'react', 'message_id': 'pe-act-1', 'emoji_id': '76'}


def test_the_adapter_does_only_what_it_declared_and_a_done_action_needs_no_message_id(store):
    world(store)
    _, _, ok, rows = turn(store, 'act-2', [{'kind': 'poke', 'who': '阿杰'}, {'kind': 'poke', 'who': '老王'}])
    assert ok
    channels = bridge(store)
    store.db.messages.update_many({'_id': {'$in': [row['_id'] for row in rows]}}, {'$unset': {'not_before': ''}})
    [item] = channels.claim('qq', supports=['image', 'sticker', 'poke'])['items']
    assert item['action'] == {'kind': 'poke', 'account': '20002'} and item['text'] == ''
    done = channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                                                           'response': {'retcode': 0}})
    assert done == {'status': 'DELIVERED'}
    assert channels.claim('qq', supports=['image', 'sticker'])['items'] == []
    row = store.db.messages.find_one({'_id': rows[1]['_id']})
    assert row['delivery_state'] == 'FAILED' and row['failure'] == 'CHANNEL_DOES_NOT_DECLARE_POKE'


def test_a_part_leaves_while_her_turn_still_runs(store):
    world(store)
    ep, _, ok, [row] = turn(store, 'act-mid', [{'kind': 'text', 'text': '在呢'}])
    assert ok
    store.db.episodes.update_one({'_id': ep['_id']}, {'$set': {'state': 'TURN'}})   # she is still thinking after reply
    store.db.messages.update_one({'_id': row['_id']}, {'$unset': {'not_before': ''}})
    channels = bridge(store)
    [item] = channels.claim('qq', supports=['image', 'sticker'])['items']
    assert item['publication_id'] == row['_id'] and item['text'] == '在呢'
    done = channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                                                           'platform_message_id': '7', 'response': {'retcode': 0}})
    assert done == {'status': 'DELIVERED'}


def test_a_number_that_is_someone_here_is_sent_back_and_force_sends_it_as_written(store):
    world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '#2 只接单，@阿杰 #2 你说呢'}]}),
                                      ('speak', {'parts': [{'kind': 'text', 'text': 'issue #2 修好了'}], 'force': 'yes'})])])
    ep = Coordinator(store, lane).ingest(mention('num-1'), persona='P1')
    (refused, no), (_, yes) = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert not no and '「#2」是 [阿杰 #2] 的编号' in refused and '「@阿杰 #2」是 [阿杰 #2] 的编号' in refused
    assert refused.endswith('真是别的数（PR 号之类），原样加 force=yes 再调用一次。')
    assert yes, 'force sends it as written'
    assert [row['text'] for row in store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'})] == ['issue #2 修好了']


def test_the_old_name_reply_still_speaks_and_says_the_new_one(store):
    world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('reply', {'parts': [{'kind': 'text', 'text': '在'}]})])])
    ep = Coordinator(store, lane).ingest(mention('old-name'), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'reply']
    assert ok and result['renamed'] == 'reply 现在叫 speak，这次照办，下次直接用新名字。'
    assert [row['text'] for row in store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'})] == ['在']
    assert role_tools.aliases()['reply'] == 'speak' and 'reply' not in role_tools.TOOL_NAMES
    [call] = [c for c in store.db.episodes.find_one({'_id': ep['_id']})['tool_calls'].values() if c['tool'] == 'speak']
    assert call['called_as'] == 'reply', 'counted toward retiring the old name'


def test_a_call_with_an_old_parameter_name_is_counted_toward_retiring_it(store):
    world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'reason': '不接'})])])
    ep = Coordinator(store, lane).ingest(mention('old-param'), persona='P1')
    [call] = [c for c in store.db.episodes.find_one({'_id': ep['_id']})['tool_calls'].values() if c['tool'] == 'stay_silent']
    assert call['old_names'] == ['reason']
    assert store.db.audit_events.find_one({'type': 'role_tool', 'payload.tool': 'stay_silent', 'payload.old_names': 'reason'})


def test_a_whole_label_or_a_number_of_nobody_here_passes(store):
    world(store)
    _, result, ok, rows = turn(store, 'num-2', [{'kind': 'text', 'text': '[阿杰 #2] 说的对，#99 不是谁'}])
    assert ok, result
    assert [row['text'] for row in rows] == ['[阿杰 #2] 说的对，#99 不是谁']


def test_a_wrong_person_or_face_sends_nothing_and_says_why(store):
    world(store)
    _, result, ok, rows = turn(store, 'act-3', [{'kind': 'text', 'text': '嗯'}, {'kind': 'poke', 'who': '#99'},
                                                {'kind': 'react', 'who': '阿杰', 'face': '乱编的'}])
    assert not ok and rows == []
    assert '第 2 条 找不到「#99」：who 照抄标签' in result and '第 3 条 「乱编的」不是这里的表情名' in result


def test_a_private_chat_that_refuses_a_reaction_is_not_tried_again_until_restart(store, monkeypatch):
    world(store)
    monkeypatch.setattr(role_tools, 'REACT_OFF_IN_DMS', set())
    dm = 'qq:%s:dm:20002' % BOT
    store.put('scenes', {'_id': dm, 'kind': 'dm', 'scope_key': 'scene:dm', 'policy_epoch': 1, 'sequence': 0,
                         'channel_id': 'qq', 'members': ['qq:20002']})
    store.config['channels']['qq']['routes']['d'] = {'scene_id': dm, 'sender_id': '20002', 'person_id': 'qq:20002',
                                                     'target': {'type': 'dm', 'id': '20002'}}
    event = {'event_id': 'dm-react', 'scene_id': dm, 'person_id': 'qq:20002', 'text': '在吗',
             'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'dm', 'id': '20002'}, 'sender_id': '20002',
                         'platform_event_id': 'pe-dm'}}
    react = ('speak', {'parts': [{'kind': 'react', 'line': '这条', 'face': '赞'}]})       # who: the other person
    lane = FakeLane(store, [FakeTurn([THINK, react])])
    ep = Coordinator(store, lane).ingest(event, persona='P1')
    assert [r[5] for r in lane.tool_results if r[2] == 'speak'] == [True], (ep.get('failure'), lane.tool_results)
    [row] = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}))
    channels = bridge(store)
    store.db.messages.update_one({'_id': row['_id']}, {'$unset': {'not_before': ''}})
    [item] = channels.claim('qq', supports=['react'])['items']
    channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'failed',
                                                    'response': {'retcode': 1200}})
    assert 'qq' in role_tools.REACT_OFF_IN_DMS
    lane = FakeLane(store, [FakeTurn([THINK, react])])
    Coordinator(store, lane).ingest({**event, 'event_id': 'dm-react-2',
                                     'channel': {**event['channel'], 'platform_event_id': 'pe-dm-2'}}, persona='P1')
    [(result, ok)] = [(r[4], r[5]) for r in lane.tool_results if r[2] == 'speak']
    assert not ok and '私聊里点不了表情' in result and '到下次重启前' in result
