"""ADR-079 step 2: she chooses the line her line points at, by its number or 这条, in every tool.

`speak.quote` takes a number or 这条 (left out: no quote; the program never chooses one); the quote rides on her
first text or picture part, comes back in the result in the one form every pointer has, and reaches the adapter as
`quote`, apart from `reply_to` (the line her words answer); a reaction and a recall name their line the same way."""
import pytest

from asuna import capabilities, group_admin
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import Denied
from test_adr009_p2 import THINK
from test_group_admin import BOT, GROUP, SCENE, bridge
from test_reply_actions import mention, world

POINTERS = ['image', 'sticker', 'react', 'poke', 'quote', 'quote_in', 'react_in', 'recall']


@pytest.fixture(autouse=True)
def fresh_capabilities():
    capabilities.forget()
    yield
    capabilities.forget()


def numbered_world(store):
    world(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'channel_id': 'qq'}})
    capabilities.declared(store, 'qq', POINTERS)


def earlier_line(store, seq, text, author='qq:20002', platform='pe-old'):
    store.put('messages', {'_id': 'line-%d' % seq, 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                           'direction': 'inbound', 'author': author, 'text': text, 'scene_seq': seq,
                           'received_at': '2026-10-18T01:00:00+00:00',
                           'event': {'channel': {'platform_event_id': platform}}})
    store.db.scenes.update_one({'_id': SCENE}, {'$max': {'sequence': seq}})


def speak(store, key, args):
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', args)])])
    ep = Coordinator(store, lane).ingest(mention(key), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    rows = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}).sort('scene_seq', 1))
    return ep, result, ok, rows


def test_she_quotes_the_line_she_chose_by_its_number_and_the_result_says_which(store):
    numbered_world(store)
    earlier_line(store, 40, '那家火锅叫老码头', platform='pe-40')
    _, result, ok, [row] = speak(store, 'q-1', {'parts': [{'kind': 'text', 'text': '对，就那家'}], 'quote': '〔40〕'})
    assert ok, result
    assert row['quote_line'] == 'line-40'
    assert result['quoted'].startswith('引的是 〔40〕 ') and result['quoted'].endswith('：那家火锅叫老码头')
    assert row['platform_reply_to'] == 'pe-40' and row['platform_answers'] == 'pe-q-1'


def test_left_out_there_is_no_quote_even_when_others_spoke_since(store):
    numbered_world(store)
    _, result, ok, [row] = speak(store, 'q-2', {'parts': [{'kind': 'text', 'text': '在呢'}]})
    assert ok and 'quoted' not in result
    assert row.get('platform_reply_to') is None and row['platform_answers'] == 'pe-q-2', 'the program never chooses'


def test_the_adapter_gets_what_she_quotes_apart_from_what_she_answers(store):
    numbered_world(store)
    earlier_line(store, 41, '这周末去哪', platform='pe-41')
    _, _, ok, [row] = speak(store, 'q-3', {'parts': [{'kind': 'text', 'text': '爬山'}], 'quote': '41'})
    assert ok
    store.db.messages.update_one({'_id': row['_id']}, {'$unset': {'not_before': ''}})
    [item] = bridge(store).claim('qq', supports=POINTERS)['items']
    assert item['quote'] == 'pe-41' and item['reply_to'] == 'pe-q-3'


def test_a_number_that_is_no_line_here_is_refused_with_the_recent_lines(store):
    numbered_world(store)
    earlier_line(store, 42, '早')
    _, result, ok, rows = speak(store, 'q-4', {'parts': [{'kind': 'text', 'text': '嗯'}], 'quote': '?'})
    assert not ok and rows == []
    assert '写编号（只写数字，在每行末尾的〔〕里）或「这条」' in str(result) and '〔42〕' in str(result)
    _, result, ok, _ = speak(store, 'q-5', {'parts': [{'kind': 'text', 'text': '嗯'}], 'quote': '9999'})
    assert not ok and '〔9999〕 不是这里的一行' in str(result)


def test_this_one_is_the_line_that_called_her_and_a_sticker_alone_cannot_carry_a_quote(store):
    numbered_world(store)
    _, result, ok, [row] = speak(store, 'q-6', {'parts': [{'kind': 'text', 'text': '来了'}], 'quote': '这条'})
    assert ok and row['quote_line'] == 'in-' + row['episode_id'] and row['platform_reply_to'] == 'pe-q-6'
    _, result, ok, _ = speak(store, 'q-7', {'parts': [{'kind': 'poke', 'who': '阿杰'}], 'quote': '这条'})
    assert not ok and 'quote 要跟一条 text 或 picture 一起发' in str(result)


def test_a_reaction_names_its_line_by_number(store):
    numbered_world(store)
    earlier_line(store, 43, '我考过了！', platform='pe-43')
    _, result, ok, [row] = speak(store, 'q-8', {'parts': [{'kind': 'react', 'line': '43', 'face': '赞'}]})
    assert ok, result
    assert row['action'] == {'kind': 'react', 'message_id': 'pe-43', 'emoji_id': '76'}
    assert row['text'].startswith('给 〔43〕 ')


def test_a_recall_names_its_line_by_number_and_whose_it_is_follows(store):
    numbered_world(store)
    group_admin_world(store)
    earlier_line(store, 44, '加我领会员', platform='pe-44')
    ep = {'_id': 'ep-r', 'scene_id': SCENE, 'person_id': 'qq:20002', 'persona': 'P1'}
    out = group_admin.queue(store, ep, 0, {'kind': 'recall', 'line': '44', 'reason': '广告'}, key='k1')
    row = store.db.artifacts.find_one({'kind': 'group_action', 'episode_id': 'ep-r'})
    assert row['admin'] == {'kind': 'recall', 'message_id': 'pe-44'} and out['who'].startswith('[阿杰')
    with pytest.raises(Denied, match='GROUP_ACTION_LINE'):
        group_admin.queue(store, ep, 0, {'kind': 'recall', 'line': '9999', 'reason': 'x'}, key='k2')


def group_admin_world(store):
    from test_group_admin import setup
    setup(store, 'admin')
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'channel_id': 'qq'}})


def test_an_ambiguous_turn_lists_the_new_lines_numbers_and_no_other_turn_does(store):
    from asuna.context import AMBIGUOUS
    numbered_world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '嗯'}]})])])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(mention('q-9'), persona='P1')
    assert 'quote' not in ep['context']['speak_from_program'], 'nobody spoke after the line that called her'
    from asuna.context import ContextBuilder
    source = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    earlier_line(store, source['scene_seq'] + 1, '我也想问')
    earlier_line(store, source['scene_seq'] + 2, '加一')
    _, context, _ = ContextBuilder(store).prepare(mention('q-9'))
    seqs = (source['scene_seq'] + 1, source['scene_seq'] + 2)
    assert context['speak_from_program']['quote'] == AMBIGUOUS % (2, '〔%d〕、〔%d〕' % seqs)
