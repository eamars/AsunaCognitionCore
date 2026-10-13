"""ADR-062 phase 2, what she is told: once per conversation in her system prompt (the core idea first, the absence
rule last), the new blocks explained there and not in each turn, and nothing of it while the switch is off."""
from asuna import block_guide, memory_tiers, role_tools
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import render_system
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event


def test_off_her_system_prompt_is_as_before_and_on_it_tells_her_once(store, monkeypatch):
    owner(store)
    monkeypatch.setattr(memory_tiers, 'ENABLED', False)
    off = render_system(store, 'P1')[0]
    assert memory_tiers.TOLD not in off and 'things_from_program' not in off
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    on = render_system(store, 'P1')[0]
    assert on.count(memory_tiers.TOLD) == 1
    assert memory_tiers.TOLD.startswith('不学会忘') and memory_tiers.TOLD.endswith('找了哪几层。')
    assert '- things_from_program：' + memory_tiers.THINGS_NOTE in on
    assert len(on) - len(off) == len('\n\n# 记忆放在哪\n' + memory_tiers.TOLD) + sum(
        len('\n- %s：%s' % pair) for pair in (('things_from_program', memory_tiers.THINGS_NOTE),
                                               ('night_list_from_program', memory_tiers.NIGHT_NOTE)))


def test_on_update_self_is_unlisted_but_still_runs_where_write_document_is_hers(store, monkeypatch):
    owner(store)
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    old = {'target': 'current_self', 'body': '还是一整段的自我', 'reason': '照旧'}
    lane = FakeLane(store, [FakeTurn([THINK, ('update_self', old)], '好。')])
    ep = Coordinator(store, lane).ingest(event('e-old-name'))
    assert 'update_self' not in lane.calls[0]['tools'] and 'write_document' in lane.calls[0]['tools']
    call = next(c for c in ep['tool_calls'].values() if c['tool'] == 'update_self')
    assert 'refused' not in call, call
    assert store.db.state_heads.find_one({'_id': 'current_self:P1|global-safe'}), 'before she has self items, as before'


def test_a_block_explained_in_the_guide_arrives_without_its_note(monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    stripped = block_guide.strip({'things_from_program': {'places': {}, 'note': memory_tiers.THINGS_NOTE}})
    assert stripped['things_from_program'] == {'places': {}}
