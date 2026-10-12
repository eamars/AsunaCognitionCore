"""Each action keeps the thought it came from, and the thought comes back with what the action made (ADR-043 batch 2):
a plan firing, a task's result, a reply to her line, the night block; as she wrote it, never summarised."""
from datetime import datetime, timedelta, timezone

from asuna import night, reasons
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.schedule_rules import scene_timezone
from test_engineering_m1 import event


def thought(store, ep_id, call_id, text):
    store.db.memory_units.insert_one({'_id': 'mono-%s:%s' % (ep_id, call_id), 'schema_version': 1, 'kind': 'monologue',
                                      'episode_id': ep_id, 'body_markdown': text, 'status': 'active'})


def test_an_action_keeps_her_newest_thought_and_a_lookup_or_a_refused_call_keeps_none(store):
    turn = FakeTurn([('think', {'thought': '他嫌我回得太长'}), ('recall', {'query': '回复长短'}),
                     ('think', {'thought': '那就记一条，以后短点'}),
                     ('ideas', {'op': 'note', 'idea': '群里说话可以更短', 'why': '有人嫌长'})], '好，我记下了。')
    ep = Coordinator(store, FakeLane(store, [turn])).ingest(event('e-b2'))
    calls = sorted(ep['tool_calls'].items(), key=lambda item: item[1]['seq'])
    by_tool = {call['tool']: (call_id, call) for call_id, call in calls}
    second_thought = [call_id for call_id, call in calls if call['tool'] == 'think'][1]
    assert by_tool['ideas'][1]['reason_ref'] == 'mono-%s:%s' % (ep['_id'], second_thought)
    assert 'reason_ref' not in by_tool['recall'][1], 'a lookup has no consequences'
    audit = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'role_tool', 'payload.tool': 'ideas'})
    assert audit['payload']['reason_ref'] == by_tool['ideas'][1]['reason_ref']
    assert reasons.thought(store, audit['payload']['reason_ref']) == '那就记一条，以后短点'


def test_a_plan_or_task_brings_back_the_thought_behind_it_and_a_reply_the_thought_behind_her_line(store):
    store.db.episodes.insert_one({'_id': 'ep-p', 'schema_version': 1, 'scene_id': 'dm-a', 'tool_calls': {
        'c1': {'tool': 'think', 'seq': 0, 'result': {}},
        'c2': {'tool': 'plan', 'seq': 1, 'result': {'plan_id': 'plan-1'}, 'reason_ref': 'mono-ep-p:c1'},
        'c3': {'tool': 'delegate', 'seq': 2, 'result': {'task': 'task-1'}, 'reason_ref': 'mono-ep-p:c1'}}})
    thought(store, 'ep-p', 'c1', '答应了明早叫他，得挂个闹钟')
    assert reasons.for_call(store, 'ep-p', 'plan_id', 'plan-1') == '答应了明早叫他，得挂个闹钟'
    assert reasons.for_call(store, 'ep-p', 'task', 'task-1') == '答应了明早叫他，得挂个闹钟'
    assert reasons.for_call(store, 'ep-p', 'plan_id', 'plan-other') is None
    store.db.messages.insert_one({'_id': 'out-1', 'schema_version': 1, 'scene_id': 'dm-a', 'direction': 'outbound',
                                  'monologue_refs': ['mono-ep-p:c0', 'mono-ep-p:c1']})
    assert reasons.for_message(store, 'out-1') == '答应了明早叫他，得挂个闹钟', 'her last thought before she spoke'


def test_the_night_block_lists_every_action_and_gives_the_thought_where_she_wrote_no_reason(store):
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    store.db.episodes.insert_one({'_id': 'ep-n', 'schema_version': 1, 'scene_id': 'local', 'source_event_id': 'ep-n',
                                  'episode_kind': 'self_development'})
    thought(store, 'ep-n', 't1', '这群太吵，让它歇两天')
    store.audit('ep-n', 'role_tool', {'call_id': 'd1', 'tool': 'delegate', 'args': {'title': '查查群规', 'brief': '…'},
                                      'result': {'task': 'task-n'}, 'reason_ref': 'mono-ep-n:t1'}, 'scene:local')
    row = store.db.audit_events.find_one({'stream_id': 'ep-n', 'type': 'role_tool'})
    store.db.audit_events.update_one({'_id': row['_id']}, {'$set': {'occurred_at': (now - timedelta(hours=6)).isoformat()}})
    out = night.block(store, 'P1', scene_timezone(store.config, {'_id': 'local'}), now, 'ep-beat')
    assert out['items'][0]['what'] == '交给行动脑去做「查查群规」'
    assert out['items'][0]['your_thought_then'] == '这群太吵，让它歇两天' and 'why' not in out['items'][0]


def test_a_reply_to_her_line_comes_with_the_thought_she_said_it_with(store):
    from asuna.people import People
    from test_people import SCENE, row, setup
    scene = setup(store)
    thought(store, 'ep-said', 't1', '他问得认真，我也认真答一句')
    store.db.messages.insert_one({'_id': 'out-said', 'schema_version': 1, 'scene_id': SCENE, 'direction': 'outbound',
                                  'author': 'demo', 'text': '我觉得这样更好', 'monologue_refs': ['mono-ep-said:t1']})
    lines = People(store).transcript(scene, row(20002, '为什么呀', reply='out-said'))
    assert '  > （你说那句时心里想的：他问得认真，我也认真答一句）' in lines.split('\n')
    other = People(store).transcript(scene, row(20002, '看这个', reply=None, at='2026-10-04T01:01:00+00:00'))
    assert '心里想的' not in other


def test_a_call_recorded_before_reasons_were_gets_its_thought_by_the_same_rule(store):
    store.db.episodes.insert_one({'_id': 'ep-old', 'schema_version': 1, 'scene_id': 'dm-a', 'tool_calls': {
        'a': {'tool': 'think', 'seq': 0, 'result': {}}, 'b': {'tool': 'plan', 'seq': 1, 'result': {'plan_id': 'plan-old'}},
        'c': {'tool': 'think', 'seq': 2, 'result': {}}}})
    thought(store, 'ep-old', 'a', '先定个钟，免得忘')
    thought(store, 'ep-old', 'c', '这句是后来的')
    assert reasons.for_call(store, 'ep-old', 'plan_id', 'plan-old') == '先定个钟，免得忘', 'the thought before it, not after'
