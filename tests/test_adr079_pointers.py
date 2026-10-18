"""ADR-079 step 1: lines that point at other lines read the same whoever made them.

Where the channel's adapter declares quotes (`quote` or `quote_in` on its claims), every line shows its number; a
quote, anyone's, reads `> 回复 〔n〕 <speaker>：<first words>` (her own lines as 你); a quote of a line the program has no
record of says so; a line that only quotes says it has no words; a private chat's quote reaches her like a group's;
the `speak` result gives each sent line's number; and a number written into her words is refused."""
import re

import pytest

from asuna import capabilities
from asuna.people import People
from asuna.role_tools import LINE_NUMBER, NUMBER_NOT_WORDS, reply_receipt
from test_notices import bridge
from test_people import BOT, GROUP, SCENE, row, setup

POINTERS = ['image', 'sticker', 'react', 'poke', 'quote', 'quote_in', 'react_in', 'recall']


@pytest.fixture(autouse=True)
def fresh_capabilities():
    capabilities.forget()
    yield
    capabilities.forget()


def numbered_scene(store):
    scene = setup(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'channel_id': 'qq'}})
    capabilities.declared(store, 'qq', POINTERS)
    return store.db.scenes.find_one({'_id': SCENE})


def test_a_declaration_is_kept_across_a_restart_and_an_undeclared_channel_shows_no_numbers(store):
    scene = numbered_scene(store)
    capabilities.forget()                                   # a Host restart before the adapter's first claim
    assert capabilities.numbered(store, scene)
    assert not capabilities.numbered(store, {'channel_id': 'agent'}), 'not declared = not carried'
    capabilities.declared(store, 'qq', ['image'])
    assert not capabilities.numbered(store, scene), 'the last declaration counts'


def test_every_line_shows_its_number_and_a_quote_between_two_others_reads_like_any(store):
    scene = numbered_scene(store)
    first = {**row(20002, '今晚谁拼外卖', card='阿杰', rid='in-a'), 'scene_seq': 301}
    store.put('messages', first)
    reply = {**row(20003, '我要', card='小周', reply='in-a', at='2026-10-04T01:05:00+00:00'), 'scene_seq': 302}
    reply['event']['group_context']['reply_to'] = 'p-a'
    text = People(store).transcript(scene, reply)
    head, quoted = text.split('\n')[:2]
    assert head.endswith(' 〔302〕') and head.startswith('[小周 #')
    assert re.fullmatch(r'  > 回复 〔301〕 \[阿杰 #\d+\]：今晚谁拼外卖', quoted)


def test_a_quote_of_her_line_names_her_as_you_and_an_unknown_one_says_so(store):
    scene = numbered_scene(store)
    store.put('messages', {'_id': 'out-1', 'scene_id': SCENE, 'direction': 'outbound', 'author': 'demo',
                           'text': '那部电影结尾是开放的', 'delivery_state': 'DELIVERED', 'scene_seq': 300,
                           'policy_epoch': 1, 'scope_key': 'scene:' + SCENE})
    asked = {**row(20002, '你是说主角没死？', card='阿杰', reply='out-1'), 'scene_seq': 301}
    asked['event']['group_context']['reply_to'] = 'p-out'
    assert '  > 回复 〔300〕 你：那部电影结尾是开放的' in People(store).transcript(scene, asked)
    lost = {**row(20002, '对吧', card='阿杰', at='2026-10-04T01:06:00+00:00'), 'scene_seq': 302}
    lost['event']['group_context']['reply_to'] = 'p-gone'
    assert '  > 回复了一条更早的消息' in People(store).transcript(scene, lost)


def test_a_line_that_only_quotes_says_it_has_no_words(store):
    scene = numbered_scene(store)
    store.put('messages', {**row(20002, '这个', card='阿杰', rid='in-b'), 'scene_seq': 300})
    bare = {**row(20003, '[回复消息（无文字）]', card='小周', reply='in-b'), 'scene_seq': 301}
    bare['event']['group_context']['reply_to'] = 'p-b'
    bare['event']['raw']['asuna_reply_only'] = True
    text = People(store).transcript(scene, bare)
    assert text.endswith('  （只引用了这条，没写字）') and '[回复消息' not in text


def test_lines_show_no_numbers_where_the_channel_declares_no_quotes(store):
    scene = setup(store)
    text = People(store).transcript(scene, {**row(20002, 'hi', card='阿杰'), 'scene_seq': 5})
    assert '〔' not in text


def test_a_private_chat_quote_reaches_her_like_a_groups(store):
    setup(store)
    dm = 'qq:%s:dm:20002' % BOT
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': 'x' * 24, 'routes': {'d': {
        'scene_id': dm, 'sender_id': '20002', 'person_id': 'qq:20002', 'target': {'type': 'dm', 'id': '20002'}}}}}
    store.put('scenes', {'_id': dm, 'kind': 'dm', 'scope_key': 'scene:dm', 'policy_epoch': 1, 'sequence': 0,
                         'channel_id': 'qq', 'channel_account_id': BOT, 'members': ['qq:20002']})
    store.put('messages', {'_id': 'mine', 'scene_id': dm, 'direction': 'outbound', 'author': 'demo', 'text': '明早八点',
                           'delivery_state': 'DELIVERED', 'platform_message_id': '77', 'scene_seq': 4,
                           'receipt_at': '2026-10-04T01:00:00+00:00', 'policy_epoch': 1, 'scope_key': 'scene:dm'})
    channels, received, _ = bridge(store)
    body = {'route_id': 'd', 'account_id': BOT, 'sender_id': '20002', 'event_id': '78', 'text': '几点来着',
            'reply_to': '77', 'occurred_at': '2026-10-04T01:05:00+00:00'}
    assert channels.receive('qq', body) == {'status': 'accepted'}
    [event] = received
    assert event['reply'] == {'reply_to': '77', 'reply_message_id': 'mine'} and 'group_context' not in event
    capabilities.declared(store, 'qq', POINTERS)
    scene = store.db.scenes.find_one({'_id': dm})
    text = People(store).transcript(scene, {'_id': 'in-78', 'scene_id': dm, 'author': 'qq:20002', 'direction': 'inbound',
                                            'text': '几点来着', 'received_at': '2026-10-04T01:05:00+00:00',
                                            'scene_seq': 5, 'event': event})
    assert '  > 回复 〔4〕 你：明早八点' in text


def test_the_speak_result_gives_each_sent_lines_number_and_a_number_in_her_words_is_refused():
    queued = [{'number': 1, 'shown': 'text', 'state': 'READY', 'seq': 320},
              {'number': 2, 'shown': 'text', 'state': 'READY', 'seq': 321}]
    assert '1 text 〔320〕；2 text 〔321〕' in reply_receipt(queued, numbered=True)
    assert '〔' not in reply_receipt(queued)
    assert LINE_NUMBER.search('你看〔318〕那句') and not LINE_NUMBER.search('今天 3 点')
    assert NUMBER_NOT_WORDS == '编号是挑引用用的，不写进你说的话里。'


def test_her_thought_under_a_quote_of_her_line_is_an_anchor_cut_at_a_sentence_end():
    from asuna.people import anchor
    thought = '他说得对，我先认下。' + '后面这段是我当时对整件事的长判断' * 6
    short = anchor(thought)
    assert short == '他说得对，我先认下。…（截断，原文 %d 字）' % len(thought)
    assert anchor('一句短的。') == '一句短的。'
    no_end = '没有句号的一整段' * 12
    assert anchor(no_end).startswith(no_end[:60] + '…（截断')
