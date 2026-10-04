"""ADR-009 P3 MongoDB tests: affect commit gates, leak, append-only, appraiser, import."""
import json
import threading


from asuna.affect import AffectLedger
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.render import action_values
from conftest import FIXTURES
from test_adr009_p2 import owner, decide
from test_engineering_m1 import event

MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))


def setup(store):
    owner(store)
    store.config['persona_model'] = {**MODEL, 'persona': {'id': 'P1', 'display_name': '示例角色'}}
    return AffectLedger(store, 'P1', store.config['persona_model'])


def ref_of(key):
    return key  # the current input's event id is always in ref_index


def test_T3_4_reasons_never_reach_public_turns_or_the_action_brain(store):
    setup(store)
    secret = {'kind': 'attachment', 'val': 30, 'arl': 30, 'ref': 'private-1', 'why': 'OWNER_SECRET_WHY',
              'who': 'OWNER_SECRET_WHO', 'cost': 'OWNER_SECRET_COST'}
    Coordinator(store, FakeLane(store, [LaneResult('想。'), decide(affect=[secret]), LaneResult('嗯。')])).ingest(event('private-1'))
    group = FakeLane(store, [LaneResult('群里。'), decide(), LaneResult('大家好。')])
    ep = Coordinator(store, group).ingest(event('group-1', scene='g1'))
    visible = json.dumps([ep['context'], group.calls], ensure_ascii=False) + action_values(store, 'P1')
    for value in ('OWNER_SECRET_WHY', 'OWNER_SECRET_WHO', 'OWNER_SECRET_COST', 'private-1', '靠近一点'):
        assert value not in visible, value
    block = ep['context']['affect_from_program']
    assert set(block) == {'label', 'policy', 'tendencies', 'commit_rules'} and block['label']
    assert all(slot['slot'] != '提要求' for slot in block['policy'])      # owner-private slot hidden


class BlockingLane:
    def __init__(self, reply):
        self.reply, self.release, self.called = reply, threading.Event(), threading.Event()

    def generate(self, binding, operation, phase, text, system):
        self.called.set()
        assert self.release.wait(20)
        return LaneResult(json.dumps(self.reply, ensure_ascii=False))


def test_T3_7_import_is_idempotent_and_events_are_immutable(store):
    ledger = setup(store)
    batch = [{'source_identity': f'old-{i}', 'ts': f'2026-01-0{i + 1}T08:00:00+13:00', 'ref': f'diary-{i}', 'why': f'旧账 {i}',
              'val': 10 + i, 'arl': 5, 'kind': 'joy', 'half': 12} for i in range(3)]
    first = ledger.import_batch('old-home', batch)
    again = ledger.import_batch('old-home', batch)
    assert (first['created'], again['created'], again['existing']) == (3, 0, 3)
    changed = [{**batch[0], 'val': 99}]
    assert ledger.import_batch('old-home', changed)['rejected'] == [{'source_identity': 'old-0', 'code': 'EVENT_IMMUTABLE'}]
    void = [{'source_identity': 'void-1', 'target_source_identity': 'old-1', 'op': 'void', 'at': '2026-01-05T00:00:00+00:00', 'why': '记错了'}]
    assert ledger.import_batch('old-home', amendments=void)['amendments_created'] == 1
    assert ledger.import_batch('old-home', amendments=void)['amendments_existing'] == 1
    assert store.db.affect_amendments.count_documents({'op': 'void'}) == 1
    bad = [{'source_identity': 'fix-1', 'target_source_identity': 'old-2', 'op': 'fix_kind', 'at': '2026-01-05T00:00:00Z', 'why': 'x'}]
    assert ledger.import_batch('old-home', amendments=bad)['rejected'][0]['code'] == 'AMENDMENT_VALUE_REQUIRED'
    naive = [{'source_identity': 'naive', 'ts': '2026-01-01T08:00:00', 'ref': 'r', 'why': 'w', 'val': 1, 'arl': 1}]
    assert ledger.import_batch('old-home', naive)['rejected'][0]['code'] == 'TIMESTAMP_REQUIRES_OFFSET'
    imported = store.db.affect_events.find_one({'source_identity': 'old-0'})
    assert imported['half'] == 12 and imported['ref_kind'] == 'external' and imported['ts_original'].endswith('+13:00')
