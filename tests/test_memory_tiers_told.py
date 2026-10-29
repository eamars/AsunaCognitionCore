"""ADR-062 phase 2, what she is told: once per conversation in her system prompt (the core idea first, the absence
rule last), the new blocks explained there and not in each turn, and nothing of it while the switch is off."""
from asuna import block_guide, memory_tiers, role_tools
from asuna.documents import DocumentStore


def test_a_block_explained_in_the_guide_arrives_without_its_note(monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    stripped = block_guide.strip({'things_from_program': {'places': {}, 'note': memory_tiers.THINGS_NOTE}})
    assert stripped['things_from_program'] == {'places': {}}
