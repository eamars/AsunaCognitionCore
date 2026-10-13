"""ADR-056: fixed text once, in her system prompt; times in blocks are fields on the local clock; the ids she may
cite include the memories and tasks shown in their own blocks."""
from asuna import block_guide, questions
from asuna.context import refs
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event


def test_the_turn_instruction_and_the_block_guide_are_in_her_system_prompt_and_only_its_first_step_ends_each_turn(store):
    from asuna.coordinator import THINK_FIRST
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在呢。')])
    Coordinator(store, lane).ingest(event('e-guide'))
    system, notice = lane.calls[0]['messages'][0]['content'], lane.calls[0]['messages'][-1]['content']
    assert '# 这一回合' in system and '# 每回合的资料' in system and '# 记忆的来源' in system
    # Rule 1 taken back for one line (2026-10-14): the first step stays next to where she writes, last in the notice.
    assert '# 这一回合' not in notice and notice.count('第一步先调用 think') == 1
    assert notice.rstrip().endswith('}\n' + THINK_FIRST), 'a turn with nothing of its own is its context and that line'


def test_a_block_saying_what_the_guide_says_arrives_without_it_and_another_note_stays():
    context = {'notes_from_program': {'items': [], 'note': block_guide.notes()['notes_from_program'][0]},
               'members_from_program': {'items': [], 'note': '这一回合特有的话'}, 'event': {'text': 'x'}}
    stripped = block_guide.strip(context)
    assert stripped['notes_from_program'] == {'items': []}
    assert stripped['members_from_program']['note'] == '这一回合特有的话'


def test_a_block_carries_its_times_as_fields_so_it_changes_only_with_its_content(store):
    store.put('scenes', {'_id': 's', 'kind': 'dm', 'scope_key': 'scene:s', 'policy_epoch': 1, 'members': ['A']})
    ep = {'_id': 'ep-1', 'scene_id': 's', 'persona': 'P1'}
    questions.record(store, ep, 'q-a1b2c3d4', '问一下', '一小时',
                     [{'to': 'g1', 'scene_id': 's', 'kind': 'here', 'name': '这里', 'episode': 'ep-1'}])
    [item] = questions.block(store, 'P1', 's')['items']
    assert 'asked_at' in item and 'until' in item['to'][0] and 'when' not in item


def test_a_memory_or_task_id_shown_in_its_block_counts_as_a_ref():
    context = {'event': {'event_id': 'e1'}, 'ref_index': ['in-e1'], 'doc_refs_from_program': ['doc:persona#a1'], 'memories': [{'_id': 'chunk-9'}],
               'task_state_from_program': [{'_id': 'task-3'}]}
    assert set(refs(context)) == {'e1', 'in-e1', 'doc:persona#a1', 'chunk-9', 'task-3'}


def test_ref_index_holds_this_turns_ids_and_the_document_sections_have_a_block_of_their_own(store):
    """ADR-063 D8: 80% of each ref_index repeated the last one; the section refs now fold as a block."""
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在呢。')])
    ep = Coordinator(store, lane).ingest(event('e-refs'))
    context = ep['context']
    assert context['ref_index'] == ['in-' + ep['_id']], 'the event id is in the event block already'
    assert {'e-refs', 'in-' + ep['_id']} <= set(refs(context)), 'both still citable'
    assert context['doc_refs_from_program'] and all(ref.startswith('doc:') for ref in context['doc_refs_from_program'])
    assert set(context['doc_refs_from_program']) <= set(refs(context)), 'still citable'
    assert 'doc_refs_from_program' in block_guide.guide(store.config)


def test_her_rhythm_does_not_repeat_the_clock(store):
    """ADR-063 D11: rhythm.local_time said the same moment as clock.now_local on the same clock."""
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在呢。')])
    context = Coordinator(store, lane).ingest(event('e-clock'))['context']
    assert 'now_local' in context['clock_from_program']
    assert 'in_sleep_window' in context['rhythm_from_program'] and 'local_time' not in context['rhythm_from_program']
