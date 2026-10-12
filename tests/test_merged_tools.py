"""ADR-055: the action brain's follow-ups are `task` and her notebook is `ideas`, each chosen by op. The old names run
for a while as their option and say so; a call without op whose fields plainly name one option is that option."""
from asuna import role_tools
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import owner
from test_adr011_ideas import THINK, event


def test_an_old_name_runs_as_its_option_says_so_and_is_recorded_as_the_tool(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('note_idea', {'idea': '回想时先看最近的心里话', 'why': '差点忘了'})], '好。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('own-1', text='记一下'))
    result = lane.tool_results[1]
    assert result[5] and result[4]['renamed'] == 'note_idea 已并入 ideas 的 note 选项，下次直接用这个。'
    assert 'note_idea' not in lane.calls[0]['tools'] and 'ideas' in lane.calls[0]['tools'], 'listed by its new name only'
    [call] = [call for call in ep['tool_calls'].values() if call['tool'] != 'think']
    assert (call['tool'], call['op'], call['called_as']) == ('ideas', 'note', 'note_idea')
    audit = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'role_tool', 'payload.tool': 'ideas'})
    assert audit['payload']['called_as'] == 'note_idea' and audit['payload']['args']['op'] == 'note'
    # review_idea's `idea` was the idea's id: it arrives as `id`.
    idea = store.db.ideas.find_one({})
    lane.outputs = iter([FakeTurn([THINK, ('review_idea', {'idea': idea['_id'], 'decision': 'defer', 'why': '先观察'})], '嗯。')])
    coordinator.ingest(event('own-2', text='看看想法本'))
    assert lane.tool_results[-1][5] and store.db.ideas.find_one({})['state'] == 'deferred'


def test_a_call_without_op_is_the_option_its_fields_plainly_name(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('ideas', {'idea': '群里少用感叹号', 'why': '显得太吵'}),
                                      ('ideas', {'why': '只写了理由'})], '好。')])
    Coordinator(store, lane).ingest(event('own-3', text='你感叹号好多'))
    noted, unclear = lane.tool_results[1], lane.tool_results[2]
    assert noted[5] and noted[4]['op'] == '没写 op：按你写的字段当作 note 办了。' and store.db.ideas.count_documents({}) == 1
    assert not unclear[5] and unclear[4].startswith('ideas 的 op 是 note、read、review 之一')
    assert role_tools.infer_op('task', {'task': 't', 'page': 2}) == 'page'
    assert role_tools.infer_op('task', {'task': 't', 'message': 'm', 'reason': 'r'}) is None, 'two options: none'
    # DSH checks required fields before the program sees the call, so a field the program infers or defaults is
    # never required in the schema she is shown (an ideas call without op was refused 3 times in 8 on 10-12).
    shown = {spec['name']: spec['parameters'] for spec in role_tools.all_specs()}
    assert not any(shown[name]['op'].get('required') for name in role_tools.OPS)
    assert not shown['await_answer']['wait'].get('required')


def test_old_names_are_registered_never_listed(store):
    names = [spec['name'] for spec in role_tools.all_specs()]
    assert set(role_tools.RENAMED) <= set(names) and not set(role_tools.RENAMED) & set(role_tools.TOOLS)
    assert role_tools.aliases()['read_report'] == 'task' and role_tools.aliases()['read_ideas'] == 'ideas'
    unlisted = {spec['name']: spec for spec in role_tools.all_specs()}['message_action']
    assert 'op' not in unlisted['parameters'] and not any(p.get('required') for p in unlisted['parameters'].values())


def test_an_option_the_turn_may_not_use_is_refused_with_its_rule(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('task', {'op': 'answer', 'answer': '好'})], '嗯。')])
    ep = Coordinator(store, lane).ingest(event('own-4', text='在吗'))
    assert 'task.answer' not in ep['turn_tools']
    assert not lane.tool_results[1][5] and lane.tool_results[1][4] == role_tools.NOT_NOW['task.answer']
