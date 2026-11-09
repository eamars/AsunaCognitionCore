"""ADR-062 phase 2, what she is told: once per conversation in her system prompt (the core idea first, the absence
rule last), and the new blocks explained there and not in each turn."""
from asuna import block_guide, memory_tiers


def test_a_block_explained_in_the_guide_arrives_without_its_note():
    stripped = block_guide.strip({'things_from_program': {'places': {}, 'note': memory_tiers.THINGS_NOTE}})
    assert stripped['things_from_program'] == {'places': {}}
