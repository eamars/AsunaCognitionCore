"""ADR-011: one character turn per episode, her mind's tools, and her work with the action brain."""
import json

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.tasks import TaskService


def event(key='e', scene='dm-a', person='A', text='我回来了。', **extra):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, **extra}


THINK = ('think', {'thought': '他回来了，我挺高兴，简单回一句。'})


def run(store, *turns):
    lane = FakeLane(store, list(turns))
    return Coordinator(store, lane), lane


def published(store, ep):
    return [row['text'] for row in store.db.messages.find({'episode_id': ep['_id'], 'direction': 'outbound'}).sort('scene_seq', 1)]


def test_think_then_speak_is_one_turn_and_the_thought_is_kept(store):
    coordinator, lane = run(store, FakeTurn([THINK], '回来了。'))
    ep = coordinator.ingest(event())
    assert ep['state'] == 'COMMITTED'
    assert [call['phase'] for call in lane.calls] == ['TURN']
    assert 'think' in lane.calls[0]['tools'] and 'stay_silent' in lane.calls[0]['tools']
    assert published(store, ep) == ['回来了。']
    thought = store.db.memory_units.find_one({'_id': ep['monologue_refs'][0]})
    assert thought['kind'] == 'monologue' and thought['body_markdown'].startswith('他回来了')
    assert thought['episode_id'] == ep['_id']


def test_the_last_thoughts_carry_into_the_next_turn(store):
    coordinator, _ = run(store, FakeTurn([THINK], '回来了。'), FakeTurn([('think', {'thought': '第二次'})], '嗯。'))
    coordinator.ingest(event('e1'))
    second = coordinator.ingest(event('e2', text='在吗'))
    items = second['context']['recent_thoughts_from_program']['items']
    assert items[-1]['thought'].startswith('他回来了') and items[-1]['when']


def test_stay_silent_ends_the_turn_without_publishing(store):
    coordinator, _ = run(store, FakeTurn([THINK, ('stay_silent', {'reason': '不用回'})], '不该发出去'))
    ep = coordinator.ingest(event())
    assert ep['state'] == 'COMMITTED' and ep['silent_reason'] == '不用回'
    assert published(store, ep) == []


def test_think_comes_first_and_a_refusal_goes_back_to_her(store):
    coordinator, lane = run(store, FakeTurn([('recall', {'query': '他是谁'}), THINK, ('recall', {'query': '他是谁'})], '想起来了。'))
    ep = coordinator.ingest(event())
    first, _, third = lane.tool_results
    assert not first[5] and '先用 think' in first[4]
    assert third[5] and third[4]['query'] == '他是谁'
    assert ep['state'] == 'COMMITTED' and ep['recall_count'] == 1


def test_a_long_thought_is_sent_back_to_be_shortened(store):
    coordinator, lane = run(store, FakeTurn([('think', {'thought': '很' * 400}), THINK], '好。'))
    ep = coordinator.ingest(event())
    assert '精简到 300 字以内' in lane.tool_results[0][4] and lane.tool_results[1][5]
    assert ep['state'] == 'COMMITTED' and len(ep['monologue_refs']) == 1


def test_json_or_program_talk_as_the_last_text_is_repaired_in_the_same_turn(store):
    coordinator, lane = run(store, FakeTurn([THINK], json.dumps({'next': 'speak'})),
                            FakeTurn([], '我调用 stay_silent 了'), FakeTurn([], '回来了就好。'))
    ep = coordinator.ingest(event())
    assert [call['phase'] for call in lane.calls] == ['TURN', 'REPAIR', 'REPAIR']
    assert 'JSON 对象' in lane.calls[1]['messages'][-1]['content']
    assert 'stay_silent' in lane.calls[2]['messages'][-1]['content']
    assert ep['state'] == 'COMMITTED' and published(store, ep) == ['回来了就好。']


def test_text_without_any_thought_fails_closed_after_repairs(store):
    coordinator, _ = run(store, *[FakeTurn([], '直接说') for _ in range(3)])
    ep = coordinator.ingest(event())
    assert ep['state'] == 'FAILED_PROTOCOL' and published(store, ep) == []


def test_a_tool_outside_this_turn_is_refused_in_words(store):
    coordinator, lane = run(store, FakeTurn([THINK], '好。'))
    ep = coordinator.ingest(event())
    # answer_action belongs to the action brain's questions only.
    assert 'answer_action' not in lane.calls[0]['tools']
    from asuna.role_tools import Refused
    import pytest
    store.put('episodes', {**store.db.episodes.find_one({'_id': ep['_id']}), 'state': 'TURN'},
              expected=store.db.episodes.find_one({'_id': ep['_id']})['revision'], stream=ep['_id'])
    with pytest.raises(Refused, match='没有 answer_action'):
        coordinator.tools.call(ep['_id'], 'x', 'answer_action', {'answer': 'a'})


def test_a_replayed_call_id_returns_the_recorded_result(store):
    coordinator, lane = run(store, FakeTurn([THINK], '好。'))
    ep = coordinator.ingest(event())
    call_id = lane.tool_results[0][1]
    again, conclude = coordinator.tools.call(ep['_id'], call_id, 'think', THINK[1])
    assert again == lane.tool_results[0][4] and conclude is False
    assert store.db.memory_units.count_documents({'kind': 'monologue', 'episode_id': ep['_id']}) == 1


def test_delegate_creates_a_task_whose_first_message_is_her_brief(store):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查一下明天本地的天气，告诉我要不要带伞。'})],
                                            '我让行动脑去查了。'))
    ep = coordinator.ingest(event(text='明天要带伞吗'))
    assert ep['state'] == 'WAITING_TASK' and len(ep['task_ids']) == 1
    task = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    assert task['state'] == 'READY' and task['title'] == '查天气' and task['brief'].startswith('查一下明天')
    assert task['thread'] == task['_id'] and 'web_search' in task['allowed_capabilities']
    assert published(store, ep) == ['我让行动脑去查了。']


def test_message_action_continues_a_finished_task_in_the_same_session(store):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    first = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    store.put('tasks', {**first, 'state': 'RETURNED', 'feedback_state': 'DELIVERED', 'result': {'text': '明天有雨'},
                        'execution_binding': 'task:x'}, expected=first['revision'], stream=first['_id'])
    coordinator.character = FakeLane(store, [FakeTurn([THINK, ('message_action', {'task': first['_id'], 'message': '再看看后天'})], '让它接着看后天。')])
    second = coordinator.ingest(event('e2', text='那后天呢'))
    continued = store.db.tasks.find_one({'_id': second['task_ids'][0]})
    assert continued['continues_task_id'] == first['_id'] and continued['execution_binding'] == 'task:x'
    assert continued['thread'] == first['thread'] and continued['brief'] == '再看看后天'


def test_message_action_to_a_running_task_is_steered_not_a_new_task(store):
    coordinator, _ = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    steered = []
    coordinator.on_action_message = lambda task, message: steered.append((task['_id'], message['text']))
    coordinator.character = FakeLane(store, [FakeTurn([THINK, ('message_action', {'task': ep['task_ids'][0], 'message': '顺便看看风'})], '好。')])
    second = coordinator.ingest(event('e2', text='还有风'))
    assert not second.get('task_ids') and steered == [(ep['task_ids'][0], '顺便看看风')]
    row = store.db.task_messages.find_one({'task_id': ep['task_ids'][0]})
    assert row['from'] == 'character' and row['delivered'] is False


def test_stop_action_cancels_a_running_task(store):
    coordinator, _ = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    task_id = ep['task_ids'][0]
    coordinator.character = FakeLane(store, [FakeTurn([THINK, ('stop_action', {'task': task_id, 'reason': '他说不用了'})], '好，不查了。')])
    coordinator.ingest(event('e2', text='不用查了'))
    assert store.db.tasks.find_one({'_id': task_id})['state'] == 'CANCELLED'


def test_stop_action_closes_a_task_a_restart_paused(store):
    from asuna.tasks import TaskService
    coordinator, _ = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    task_id = ep['task_ids'][0]
    TaskService(store).pause_for_restart(task_id)
    coordinator.character = lane = FakeLane(store, [FakeTurn([THINK, ('stop_action', {'task': task_id, 'reason': '那件事已经收尾了'})], '关掉了。')])
    coordinator.ingest(event('e2', text='那条暂停的关掉吧'))
    assert store.db.tasks.find_one({'_id': task_id})['state'] == 'CANCELLED'


def test_a_mistyped_task_id_is_refused_with_candidates(store):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    coordinator.character = lane = FakeLane(store, [FakeTurn([THINK, ('stop_action', {'task': ep['task_ids'][0][:14] + 'zz', 'reason': 'x'})], '好。')])
    coordinator.ingest(event('e2', text='不用了'))
    refusal = lane.tool_results[1][4]
    assert '不是这个对话里的任务' in refusal and ep['task_ids'][0] in refusal


def test_consult_answers_the_action_brain_without_publishing(store):
    coordinator, _ = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})], '去查了。'))
    ep = coordinator.ingest(event())
    service = TaskService(store)
    task = service.claim(ep['task_ids'][0])
    coordinator.character = lane = FakeLane(store, [FakeTurn([('think', {'thought': '他应该是问本地。'}),
                                                              ('answer_action', {'answer': '查本地的就行。'})])])
    answer = coordinator.consult(task, 'call-1', {'question': '查哪个城市？'})
    assert answer['answer'] == '查本地的就行。' and answer['internal'] is True
    assert lane.calls[0]['tools'] == ['think', 'recall', 'answer_action']
    asked = store.db.episodes.find_one({'episode_kind': 'consult'})
    assert asked['state'] == 'COMMITTED' and published(store, asked) == []
