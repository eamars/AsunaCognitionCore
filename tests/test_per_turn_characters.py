"""ADR-056: fixed text once, in her system prompt; times in blocks are fields on the local clock; the ids she may
cite include the memories and tasks shown in their own blocks."""
from asuna import block_guide, developer_inbox
from asuna.context import refs
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event


def test_the_turn_instruction_and_the_block_guide_are_in_her_system_prompt_not_in_each_turn(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在呢。')])
    Coordinator(store, lane).ingest(event('e-guide'))
    system, notice = lane.calls[0]['messages'][0]['content'], lane.calls[0]['messages'][-1]['content']
    assert '# 这一回合' in system and '# 每回合的资料' in system and '# 记忆的来源' in system
    assert '# 这一回合' not in notice and '第一步先调用 think' not in notice
    assert notice.rstrip().endswith('}'), 'a turn with nothing of its own is its context alone'


def test_a_block_saying_what_the_guide_says_arrives_without_it_and_another_note_stays():
    context = {'notes_from_program': {'items': [], 'note': block_guide.notes()['notes_from_program'][0]},
               'members_from_program': {'items': [], 'note': '这一回合特有的话'}, 'event': {'text': 'x'}}
    stripped = block_guide.strip(context)
    assert stripped['notes_from_program'] == {'items': []}
    assert stripped['members_from_program']['note'] == '这一回合特有的话'


def test_a_block_carries_its_times_as_fields_so_it_changes_only_with_its_content(store):
    developer_inbox.leave(store, 'P1', developer_inbox.NOTE, '写给开发者', key=['k'], source={'scene_id': 's'})
    [item] = developer_inbox.block(store, 'P1')['items']
    assert 'at' in item and 'when' not in item


def test_a_memory_or_task_id_shown_in_its_block_counts_as_a_ref():
    context = {'ref_index': ['e1', 'in-e1', 'doc:persona#a1'], 'memories': [{'_id': 'chunk-9'}],
               'task_state_from_program': [{'_id': 'task-3'}]}
    assert set(refs(context)) == {'e1', 'in-e1', 'doc:persona#a1', 'chunk-9', 'task-3'}
