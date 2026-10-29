"""ADR-056: fixed text once, in her system prompt; times in blocks are fields on the local clock; the ids she may
cite include the memories and tasks shown in their own blocks."""
from asuna import block_guide
from asuna.context import refs


def test_a_block_saying_what_the_guide_says_arrives_without_it_and_another_note_stays():
    context = {'notes_from_program': {'items': [], 'note': block_guide.notes()['notes_from_program'][0]},
               'members_from_program': {'items': [], 'note': '这一回合特有的话'}, 'event': {'text': 'x'}}
    stripped = block_guide.strip(context)
    assert stripped['notes_from_program'] == {'items': []}
    assert stripped['members_from_program']['note'] == '这一回合特有的话'


def test_a_memory_or_task_id_shown_in_its_block_counts_as_a_ref():
    context = {'event': {'event_id': 'e1'}, 'ref_index': ['in-e1'], 'doc_refs_from_program': ['doc:persona#a1'], 'memories': [{'_id': 'chunk-9'}],
               'task_state_from_program': [{'_id': 'task-3'}]}
    assert set(refs(context)) == {'e1', 'in-e1', 'doc:persona#a1', 'chunk-9', 'task-3'}


