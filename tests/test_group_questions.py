"""ADR-061 step 2 with ADR-064 phase 2: a question in a group is a reply with wait=question. People who speak
unaddressed while it waits get her a look, once each; replies to her line, those lines and reactions to it are its
answers, kept by reference; she brings an answer home in her own words with leave_note's question, and the program
adds who answered and where the original is; ask's read at home reads the group's own words for that turn only."""
from datetime import datetime, timedelta, timezone

from asuna import notes, questions
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.people import People
from test_adr009_p2 import THINK
from test_group_admin import SCENE
from test_reply_actions import turn, world


def ask(store, patience=None):
    options = {'wait': 'question', **({'patience': patience} if patience else {})}
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '大家晚饭吃什么？'}], **options})])])
    from test_reply_actions import mention
    ep = Coordinator(store, lane).ingest(mention('q-1'), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    return ep, result, ok


def inbound(store, key, author, seq, **context):
    store.put('messages', {'_id': key, 'scene_id': SCENE, 'author': author, 'direction': 'inbound', 'text': '吃面',
                           'received_at': datetime.now(timezone.utc).isoformat(), 'policy_epoch': 1, 'scene_seq': seq,
                           'platform_event_id': 'pe-' + key,
                           'event': {'group_context': context, 'channel': {'platform_event_id': 'pe-' + key}}})


def test_a_question_in_a_group_opens_like_any_other_and_says_so(store):
    world(store)
    ep, result, ok = ask(store)
    assert ok and result['question'].startswith('这是在问这里的人：问题 q-') and '等一会儿（10 分钟）' in result['question']
    [row] = list(store.db.questions.find())
    assert row['text'] == '大家晚饭吃什么？' and row['patience'] == '一会儿'
    assert row['sources'][0]['kind'] == 'group' and row['sources'][0]['scene_id'] == SCENE
    block = questions.group_block(store, 'P1', store.db.scenes.find_one({'_id': SCENE}))
    assert block['items'][0].startswith(row['_id'] + ' 你 ') and '等着，一会儿（还剩' in block['items'][0]


def test_patience_goes_with_a_question_only(store):
    world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '嗯嗯'}], 'patience': '一天'})])])
    from test_reply_actions import mention
    Coordinator(store, lane).ingest(mention('q-bad-2'), persona='P1')
    [(said, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert not ok and 'patience 只跟 wait=question 一起用' in said


def test_who_speaks_while_it_waits_gets_her_a_look_once_and_their_line_is_an_answer(store):
    world(store)
    ask(store)
    scene = store.db.scenes.find_one({'_id': SCENE})
    assert questions.wants_look(store, scene, 'qq:20003')
    line = store.db.messages.find_one({'scene_id': SCENE, 'direction': 'outbound', 'phase': 'SPEAK'})
    inbound(store, 'in-ans-1', 'qq:20003', line['scene_seq'] + 1, wake_reason='question_wait')
    assert not questions.wants_look(store, scene, 'qq:20003'), 'one look per person'
    assert questions.wants_look(store, scene, 'qq:20001')
    later = datetime.now(timezone.utc) + timedelta(minutes=questions.LOOK_MINUTES + 1)
    assert not questions.wants_look(store, scene, 'qq:20001', later), 'looks only within ten minutes'
    inbound(store, 'in-ans-2', 'qq:20001', line['scene_seq'] + 2, reply_message_id=line['_id'])
    row = questions.refresh(store, store.db.questions.find_one())
    answers = row['sources'][0]['answers']
    assert row['sources'][0]['state'] == 'answered' and [a['line'] for a in answers] == ['in-ans-1', 'in-ans-2']
    assert all('text' not in a for a in answers), 'answers are kept by reference'
    block = questions.group_block(store, 'P1', scene)
    assert '；回了：' in block['items'][0] and row['state'] == 'open', 'answered, but more may answer within its patience'
    # Past its patience the program closes it, and the group is told once what it closed as (her choice 2026-10-15).
    after = datetime.now(timezone.utc) + timedelta(minutes=11)
    told = questions.group_block(store, 'P1', scene, after)
    [item] = told['items']
    assert item.startswith(row['_id'] + ' 你 ') and item.endswith('问的：程序收的：都有了结果，有回答')
    assert questions.group_block(store, 'P1', scene, after) is None, 'told once'


def test_she_brings_the_answer_home_in_her_words_and_reads_the_original_there(store):
    world(store)
    ask(store)
    qid = store.db.questions.find_one()['_id']
    line = store.db.messages.find_one({'scene_id': SCENE, 'direction': 'outbound', 'phase': 'SPEAK'})
    inbound(store, 'in-ans-3', 'qq:20003', line['scene_seq'] + 1, reply_message_id=line['_id'])
    draft = {'_id': 'note-x', 'persona': 'P1', 'from_scene': SCENE, 'answers': qid}
    tail = notes.answers_tail(store, 'P1', draft)
    who = People(store, 'P1').speaker(store.db.scenes.find_one({'_id': SCENE}), 'qq:20003', {})
    assert tail.startswith('回答的是 ' + who) and tail.endswith('原话家里不存，随时用 ask do=read id=%s 读' % qid)
    read = questions.read(store, 'P1', qid)
    [answer] = read['to'][0]['answers']
    assert answer['text'] == '吃面' and answer['where'].startswith(read['to'][0]['to']) and '家里不存' in answer['where']
    store.db.messages.delete_one({'_id': 'in-ans-3'})
    [answer] = questions.read(store, 'P1', qid)['to'][0]['answers']
    assert answer['text'] == questions.GONE, 'never an empty answer'


def test_leave_note_takes_only_a_question_asked_here(store):
    world(store)
    ask(store)
    qid = store.db.questions.find_one()['_id']
    ep = store.db.episodes.find_one()
    tools = Coordinator(store, FakeLane(store, [])).tools
    import pytest
    from asuna.role_tools import Refused
    with pytest.raises(Refused, match='不是你在这里问的问题'):
        tools.tool_leave_note(ep, 'c1', {'to': '家里', 'text': '他们说吃面', 'question': 'q-00000000'})
    assert qid.startswith('q-')


def test_a_question_line_is_waited_on_by_the_question_not_listed_again(store):
    from asuna import waiting
    from test_reply_actions import mention
    world(store)
    now = datetime.now(timezone.utc)
    for key, options in (('q-at', {'wait': 'question'}), ('plain-at', {})):
        lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '@[阿杰 #2] 你来吗？'}],
                                                             **options})])])
        ep = Coordinator(store, lane).ingest(mention(key), persona='P1')
        store.db.messages.update_many({'episode_id': ep['_id'], 'phase': 'SPEAK'},
                                      {'$set': {'delivery_state': 'DELIVERED', 'receipt_at': now.isoformat()}})
        listed = waiting.pending(store, [SCENE], now + timedelta(minutes=1), 'P1')
        assert (listed == []) if key == 'q-at' else (len(listed) == 1), (key, listed)
