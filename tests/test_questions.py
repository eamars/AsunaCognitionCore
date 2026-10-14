"""ADR-061 step 1: her questions to her home places and the action brain -- asked with `ask`, answered by the next line
there (or a line naming the question, or the task's report), lapsing past their patience, closed by her or once by the
program, and shown at home once per change without repeating a text in the same notice."""
import json
from datetime import datetime, timedelta, timezone

from asuna import notes, places, questions, role_tools, visibility
from asuna.channels import kept_raw
from asuna.ingress import persist_input
from test_notes import OWNER_DM, delivered, results, turn, world
from test_engineering_m1 import THINK

HOME = {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'}


def owner_says(store, service, key, text, calls=(), speech='嗯'):
    return turn(store, service, {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': text}, list(calls), speech)


def asked(store, lane):
    [(said, ok)] = results(lane, 'ask')
    assert ok, said
    return store_row(store, said['id'])


def store_row(store, qid):
    return store.db.questions.find_one({'_id': qid})


def item_of(context, qid):
    return next(item for item in context['questions_from_program']['items'] if item['id'] == qid)


def test_ask_is_listed_at_home_where_message_developer_was_and_the_old_name_still_runs(store):
    home = {'_id': 'ep-x', 'scene_id': 'dm-a', 'persona': 'P1', 'context': {},
            'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    world(store)
    listed = role_tools.abilities(store, home)
    assert {'ask.ask', 'ask.read', 'ask.close'} <= set(listed) and 'message_developer' not in listed
    public = {**home, 'scene_id': 'dm-b', 'manifest': {'session_class': visibility.PUBLIC}}
    assert not any(name.startswith('ask') for name in role_tools.abilities(store, public))
    assert role_tools.aliases()['message_developer'] == 'ask'
    assert 'message_developer' in [spec['name'] for spec in role_tools.all_specs()], 'registered, never listed'
    assert role_tools.infer_op('ask', {'id': 'q-1'}) == 'read' and role_tools.infer_op('ask', {'took': 'x'}) == 'close'


def test_a_question_here_is_her_reply_and_the_next_line_answers_it(store):
    service = world(store)
    ep, lane = turn(store, service, HOME, [('ask', {'question': '晚饭吃什么好？', 'to': ['这里'], 'patience': '一会儿'})],
                    '主人，晚饭吃什么好？')
    row = asked(store, lane)
    assert [source['kind'] for source in row['sources']] == ['here'] and row['patience'] == '一会儿'
    assert store.db.audit_events.find_one({'type': 'question.asked', 'payload.question': row['_id']})
    back, _ = owner_says(store, service, 'ask-2', '吃面吧')
    item = item_of(back['context'], row['_id'])
    assert item['state'] == '有回答' and item['to'][0]['state'] == '答了' and item['question'] == '晚饭吃什么好？'
    assert store.db.audit_events.find_one({'type': 'question.answered', 'payload.question': row['_id']})
    read_ep, read_lane = owner_says(store, service, 'ask-3', '嗯', calls=[('ask', {'op': 'read', 'id': row['_id']})])
    [(found, ok)] = results(read_lane, 'ask')
    assert ok and found['to'][0]['answers'][0]['text'] == '吃面吧' and found['to'][0]['answers'][0]['line']
    _, close_lane = owner_says(store, service, 'ask-4', '嗯', calls=[('ask', {'id': row['_id'], 'took': '吃面'})])
    [(closed, ok)] = results(close_lane, 'ask')
    assert ok and closed['closed'].startswith('答你的有：') and store_row(store, row['_id'])['state'] == 'closed'
    after, _ = owner_says(store, service, 'ask-5', '好')
    assert 'questions_from_program' not in after['context'], 'a question she closed leaves the block'
    _, history_lane = owner_says(store, service, 'ask-6', '嗯', calls=[('ask', {'op': 'read', 'to': ['这里']})])
    [(history, ok)] = results(history_lane, 'ask')
    assert ok and history['items'][0]['took'] == '吃面' and history['items'][0]['state'] == '答了'


def test_a_question_to_another_home_place_wakes_it_with_a_note_and_its_text_goes_once(store):
    service = world(store)
    ep, lane = turn(store, service, HOME, [('ask', {'question': '周末去哪玩？', 'to': [OWNER_DM]})], '我去私聊里问主人。')
    row = asked(store, lane)
    [source] = row['sources']
    note = store.db.notes.find_one({'_id': source['note']})
    assert note['question'] == row['_id'] and note['to_scene'] == 'dm-o' and service.controller.offers[-1][0] == 'note'
    assert row['sources'][0]['until'], 'an hour by default'
    # In the turn the note opened, the question's text is in the note only; the block names the question by its id.
    there, _ = turn(store, service, delivered(service), [], '主人，周末去哪玩？')
    assert '周末去哪玩？' in there['context']['note_from_program']['text']
    item = item_of(there['context'], row['_id'])
    assert 'question' not in item and item['to'][0]['state'] == '还没问出来'
    assert json.dumps(there['context'], ensure_ascii=False).count('周末去哪玩') == 1
    # Neither list of notes repeats it: the questions block says what came of it.
    home_again, _ = owner_says(store, service, 'ask-2', '嗯')
    assert 'notes_sent_from_program' not in home_again['context']
    assert json.dumps(home_again['context'], ensure_ascii=False).count('周末去哪玩') == 1
    # His next line there answers it.
    persist_input(store, {'event_id': 'dm-o-1', 'scene_id': 'dm-o', 'person_id': 'A', 'text': '去爬山'})
    answered = questions.refresh(store, store_row(store, row['_id']))
    assert answered['sources'][0]['state'] == 'answered'


def test_unspoken_is_not_asked_unanswered_lapses_and_the_program_closes_it_once_per_conversation(store):
    service = world(store)
    _, lane = turn(store, service, HOME, [('ask', {'question': '要不要去？', 'to': ['这里']}),
                                          ('stay_silent', {'reason': '算了'})])
    silent = asked(store, lane)
    assert questions.refresh(store, silent)['sources'][0]['state'] == 'not_asked'
    _, lane = owner_says(store, service, 'ask-2', '嗯', calls=[('ask', {'question': '明天几点？', 'to': ['这里']})],
                         speech='明天几点？')
    waiting = asked(store, lane)
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    lapsed = questions.refresh(store, store_row(store, waiting['_id']), later)
    assert lapsed['sources'][0]['state'] == 'lapsed' and lapsed['state'] == 'open'
    assert store.db.audit_events.count_documents({'type': 'question.lapsed', 'payload.question': waiting['_id']}) == 1
    end = later + timedelta(days=2)
    shown = questions.block(store, 'P1', 'dm-a', end)
    assert {item['state'] for item in shown['items']} == {'程序关了'}
    assert questions.block(store, 'P1', 'dm-a', end) is None, 'told once in this conversation'
    assert questions.block(store, 'P1', 'dm-o', end), 'and once in each other home conversation'


def test_the_action_brain_answers_with_its_report(store):
    service = world(store)
    _, lane = turn(store, service, HOME, [('ask', {'question': '这个词是什么意思？', 'to': ['行动脑']})], '我问问。')
    row = asked(store, lane)
    task = store.db.tasks.find_one({'_id': row['sources'][0]['task']})
    assert '这个词是什么意思？' in task['brief']
    store.db.tasks.update_one({'_id': task['_id']}, {'$set': {'state': 'RETURNED', 'finished_at': task['created_at'],
                                                              'result': {'text': '意思是这样。'}}})
    found = questions.read(store, 'P1', row['_id'])
    assert found['to'][0]['state'] == '答了' and found['to'][0]['answers'][0]['text'] == '意思是这样。', 'its usual end'
    store.db.tasks.update_one({'_id': task['_id']}, {'$set': {'state': 'BLOCKED', 'result': {}}})
    assert questions.read(store, 'P1', row['_id'])['to'][0]['state'] != '答了', 'ended without a report: not done'


def test_a_place_outside_home_is_refused_in_words(store):
    service = world(store)
    _, lane = turn(store, service, HOME, [('ask', {'question': '大家觉得呢？', 'to': [places.place_id('g1')]})], '嗯')
    [(said, ok)] = results(lane, 'ask')
    assert not ok and said.startswith('ASK_PLACE_NOT_HOME') and 'pass_note' in said
    assert store.db.questions.count_documents({}) == 0 and store.db.notes.count_documents({}) == 0


def test_message_developer_runs_as_ask_to_the_developers_line(store):
    service = world(store)
    store.config['channels']['agent'] = {'account_id': 'home', 'routes': {'claude-code': {
        'scene_id': 'dm-o', 'target': {'type': 'dm', 'id': 'claude-code'}, 'person_id': 'A'}}}
    _, lane = turn(store, service, HOME, [('message_developer', {'level': 'wake', 'text': '入站断了'})], '留好了')
    [(said, ok)] = results(lane, 'message_developer')
    assert ok, said
    assert said['renamed'] == role_tools.RENAMED_NOTE % ('message_developer', 'ask', 'ask')
    row = store_row(store, said['id'])
    assert row['patience'] == '一小时' and row['sources'][0]['scene_id'] == 'dm-o'


def test_her_inbox_messages_move_into_closed_questions_and_the_programs_notes_stay(store):
    store.config['channels'] = {'agent': {'routes': {'claude-code': {'scene_id': 'agent:home:dm:claude-code'}}}}
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': 'dm-a'}
    base = {'schema_version': 1, 'level': 'note', 'state': 'answered', 'created_at': '2026-10-12T00:00:00+00:00',
            'answered_at': '2026-10-12T00:30:00+00:00', 'scope_key': 'owner-private:P1'}
    store.db.developer_inbox.insert_many([
        {**base, '_id': 'dev-1', 'persona': 'P1', 'text': '报个问题', 'source': {'scene_id': 'dm-a'}},
        {**base, '_id': 'dev-2', 'persona': 'P1', 'text': '[程序]', 'source': {'by': 'program'}}])
    assert questions.migrate(store, 'P1') == 1 and questions.migrate(store, 'P1') == 0
    [row] = store.db.questions.find({})
    assert row['state'] == 'closed' and row['sources'][0]['state'] == 'answered' and row['migrated_from'] == 'dev-1'
    assert questions.block(store, 'P1', 'dm-a') is None, 'moved rows are history, not news'
    assert store.db.developer_inbox.count_documents({}) == 2


def test_a_line_names_a_question_only_on_a_home_line(monkeypatch):
    raw = {questions.ANSWER_KEY: {'question': 'q-1a2b3c4d'}}
    from asuna import channel_kinds
    monkeypatch.setitem(channel_kinds._KINDS, 'homeline', type('HomeLine', (), {'KIND': 'homeline', 'HOME': True}))
    assert kept_raw({'scene_id': 'homeline:home:dm:x'}, raw)[questions.ANSWER_KEY] == {'question': 'q-1a2b3c4d'}
    assert questions.ANSWER_KEY not in kept_raw({'scene_id': 'qq:acct:group:1'}, raw)
    assert questions.ANSWER_KEY not in kept_raw({'scene_id': 'homeline:home:dm:x'}, {questions.ANSWER_KEY: {'question': 'x'}})


def test_a_line_naming_the_question_is_its_answer_over_the_next_line(store):
    store.put('scenes', {'_id': 'line', 'kind': 'dm', 'scope_key': 'scene:line', 'policy_epoch': 1, 'members': ['C']})
    ep = {'_id': 'ep-q', 'scene_id': 'line', 'persona': 'P1'}
    row = questions.record(store, ep, 'q-e5f6a7b8', '这个怎么修？', '一小时',
                           [{'to': 'x', 'scene_id': 'line', 'kind': 'here', 'name': '线', 'episode': 'ep-q'}])
    base = {'schema_version': 1, 'scene_id': 'line', 'policy_epoch': 1, 'scope_key': 'scene:line'}
    store.db.messages.insert_many([
        {**base, '_id': 'out-1', 'direction': 'outbound', 'phase': 'SPEAK', 'episode_id': 'ep-q', 'scene_seq': 1,
         'author': 'me', 'text': '这个怎么修？', 'delivery_state': 'DELIVERED'},
        {**base, '_id': 'in-2', 'direction': 'inbound', 'scene_seq': 2, 'author': 'C', 'text': '在看了',
         'received_at': '2026-10-13T00:01:00+00:00', 'event': {}},
        {**base, '_id': 'in-3', 'direction': 'inbound', 'scene_seq': 3, 'author': 'C', 'text': '改这一行',
         'received_at': '2026-10-13T00:05:00+00:00',
         'event': {'raw': {questions.ANSWER_KEY: {'question': 'q-e5f6a7b8'}}}}])
    answered = questions.refresh(store, row)
    assert [answer['line'] for answer in answered['sources'][0]['answers']] == ['in-3']


def test_on_an_agent_line_only_a_marked_line_of_the_agents_answers_and_the_owners_line_still_does(store):
    from asuna import channel_kinds
    channel_kinds.load([{'python': channel_kinds.Path(__file__).resolve().parents[1] / 'packages' / 'channels' / 'agent-line'
                         / 'python', 'module': 'agent_line'}])
    line = 'agent:home:dm:helper'
    store.put('scenes', {'_id': line, 'kind': 'dm', 'scope_key': 'scene:' + line, 'policy_epoch': 1, 'members': []})
    base = {'schema_version': 1, 'scene_id': line, 'policy_epoch': 1, 'scope_key': 'scene:' + line, 'event': {}}

    def ask(qid, seq):
        ep = {'_id': 'ep-' + qid, 'scene_id': line, 'persona': 'P1'}
        row = questions.record(store, ep, qid, '问一句', '一小时',
                               [{'to': 'x', 'scene_id': line, 'kind': 'here', 'name': '线', 'episode': ep['_id']}])
        store.db.messages.insert_one({**base, '_id': 'out-' + qid, 'direction': 'outbound', 'phase': 'SPEAK',
                                      'episode_id': ep['_id'], 'scene_seq': seq, 'author': 'me', 'text': '问一句',
                                      'delivery_state': 'DELIVERED'})
        return row
    first = ask('q-a1a1a1a1', 1)
    store.db.messages.insert_one({**base, '_id': 'in-2', 'direction': 'inbound', 'scene_seq': 2, 'author': 'agent:helper',
                                  'text': '说件别的事', 'received_at': '2026-10-14T00:01:00+00:00'})
    unmarked = questions.refresh(store, store_row(store, first['_id']))
    assert unmarked['sources'][0]['state'] != 'answered', "the agent's unmarked line answers nothing"
    store.db.messages.insert_one({**base, '_id': 'in-3', 'direction': 'inbound', 'scene_seq': 3, 'author': 'local-user',
                                  'text': '我来答：可以', 'received_at': '2026-10-14T00:02:00+00:00'})
    answered = questions.refresh(store, store_row(store, first['_id']))
    assert [answer['line'] for answer in answered['sources'][0]['answers']] == ['in-3'], "the owner's line, as before"
