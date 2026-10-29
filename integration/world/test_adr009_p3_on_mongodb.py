"""ADR-009 P3 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): her reasons never reach a
public turn or the action brain."""
from pathlib import Path
import json

import pytest

from asuna.affect import AffectLedger
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import action_values

from turn_parts import event, owner

THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})

pytestmark = pytest.mark.world                # `store` is the fixture world
FIXTURES = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures'

MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))


def setup(store):
    owner(store)
    store.config['persona_model'] = {**MODEL, 'persona': {'id': 'P1', 'display_name': '示例角色'}}
    return AffectLedger(store, 'P1', store.config['persona_model'])


def test_T3_4_reasons_never_reach_public_turns_or_the_action_brain(store):
    setup(store)
    secret = {'do': 'record', 'feeling': 'attachment', 'intensity': '强烈', 'arousal': '激动', 'ref': 'private-1',
              'why': 'OWNER_SECRET_WHY', 'cost': 'OWNER_SECRET_COST'}
    private = FakeLane(store, [FakeTurn([THINK, ('feel', secret)], '嗯。')])
    Coordinator(store, private).ingest(event('private-1'))
    assert private.tool_results[1][5], private.tool_results[1]
    assert store.raw.affect_events.find_one({'why': 'OWNER_SECRET_WHY'})          # the private feeling was recorded
    group = FakeLane(store, [FakeTurn([THINK], '大家好。')])
    ep = Coordinator(store, group).ingest(event('group-1', scene='g1'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    visible = json.dumps([ep['context'], group.calls], ensure_ascii=False) + action_values(store, 'P1')
    for value in ('OWNER_SECRET_WHY', 'OWNER_SECRET_COST', 'private-1', '靠近一点'):
        assert value not in visible, value
    block = ep['context']['affect_from_program']
    # ADR-086 D4: outside home the mood is one paragraph: the state and its pull, never a number, a reason recorded
    # elsewhere, a slot rule or an owner-private tendency.
    assert set(block) == {'心情'} and block['心情']
    assert ep['context']['how_to_record_from_program']['kinds']          # how to record is its own block
    assert '提要求' not in block['心情'] and '可以提' not in block['心情']  # owner-private slot and tendency hidden


