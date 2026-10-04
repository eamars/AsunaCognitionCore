"""ADR-009 P3 MongoDB tests: affect commit gates, leak, append-only, appraiser, import."""
import json
from pathlib import Path
import threading

import pytest

from asuna import affect as affect_module
from asuna.affect import AffectLedger, Appraiser, PROPOSAL_FIELDS
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.render import action_values
from asuna.state import Denied
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


def test_T3_3_committed_events_and_independent_rejections(store):
    ledger = setup(store)
    items = [{'kind': 'joy', 'val': 6, 'arl': 4, 'ref': 'gate', 'why': '记得小事', 'cost': '等了一天'},
             {'kind': 'joy', 'val': 6, 'arl': 4, 'ref': 'not-in-index', 'why': 'x', 'cost': 'c'},
             {'kind': 'joy', 'val': 6, 'arl': 4, 'ref': 'gate', 'why': '没写代价'}]
    lane = FakeLane(store, [LaneResult('高兴。'), decide(affect=items), LaneResult('谢谢。')])
    ep = Coordinator(store, lane).ingest(event('gate'))
    assert ep['state'] == 'COMMITTED'
    lane = FakeLane(store, [LaneResult('还有。'), decide(affect=[{'kind': 'joy', 'val': 50, 'arl': 1, 'ref': 'gate2', 'why': 'w', 'cost': 'c'},
                                                                  {'kind': 'rage', 'val': 1, 'arl': 1, 'ref': 'gate2', 'why': 'w', 'cost': 'c'}]),
                            LaneResult('好。')])
    second = Coordinator(store, lane).ingest(event('gate2'))
    events = ledger.events()
    assert len(events) == 1 and events[0]['origin'] == 'asuna' and events[0]['source_scope'] == 'owner-private:P1'
    assert events[0]['ts'].endswith('+00:00') and events[0]['episode_id'] == ep['_id']
    codes = [r['code'] for r in ep['rejections'] + second['rejections']]
    assert codes == ['AFFECT_REF_NOT_IN_INDEX', 'AFFECT_COST_REQUIRED', 'AFFECT_DELTA_TOO_LARGE', 'AFFECT_KIND_UNKNOWN'], codes
    assert second['state'] == 'COMMITTED'


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


def test_T3_5_append_only_and_operator_void(store):
    ledger = setup(store)
    source = Path(affect_module.__file__).read_text(encoding='utf-8')
    for verb in ('delete_one', 'delete_many', 'replace_one', 'update_one', 'update_many', 'find_one_and_', "put('affect"):
        assert verb not in source, verb
    with pytest.raises(Denied):
        store.put('affect_events', {'_id': 'x', 'persona': 'P1'})
    Coordinator(store, FakeLane(store, [LaneResult('想。'), decide(affect=[{'kind': 'calm', 'val': 3, 'arl': 1, 'ref': 'v1',
                                                                            'why': 'w', 'cost': 'c', 'open': True}]),
                                        LaneResult('好。')])).ingest(event('v1'))
    target = ledger.events()[0]['_id']
    no_why = FakeLane(store, [LaneResult('想。'), decide(affect_ops=[{'op': 'void', 'event_id': target}]), LaneResult('好。')])
    ep = Coordinator(store, no_why).ingest(event('v2'))
    assert ep['rejections'][0]['code'] == 'ITEM_INVALID'                      # schema: void requires why
    erased = ledger.operator_erase(target, '隐私擦除')
    assert erased['by'] == 'operator' and erased['op'] == 'void'
    assert ledger.projection()['val'] == 0                                   # void counts as never counted


class BlockingLane:
    def __init__(self, reply):
        self.reply, self.release, self.called = reply, threading.Event(), threading.Event()

    def generate(self, binding, operation, phase, text, system):
        self.called.set()
        assert self.release.wait(20)
        return LaneResult(json.dumps(self.reply, ensure_ascii=False))


def test_T3_6_appraiser_proposes_after_commit_and_proposals_are_adopted(store):
    ledger = setup(store)
    blocking = BlockingLane([{'kind': 'joy', 'val': 5, 'arl': 2, 'ref': 'appraise-1', 'why': '对方记得小事', 'cost': '无'}])
    coordinator = Coordinator(store, FakeLane(store, [LaneResult('想。'), decide(), LaneResult('谢谢。')]))
    coordinator.appraiser = Appraiser(store, blocking)
    ep = coordinator.ingest(event('appraise-1'))
    assert ep['state'] == 'COMMITTED' and store.db.affect_proposals.count_documents({}) == 0   # turn did not wait
    blocking.release.set()
    coordinator.appraisals[ep['_id']].join(20)
    proposal = store.db.affect_proposals.find_one({'kind_row': 'proposal'})
    assert proposal['source_scope'] == 'owner-private:P1' and 'appraise-1' in proposal['ref_index']
    assert PROPOSAL_FIELDS <= {'kind', 'val', 'arl', 'ref', 'why', 'cost', 'open', 'who', 'half', 'half_arl'}
    assert not PROPOSAL_FIELDS & {'text', 'say', 'line', 'reply', 'speech', 'message'}
    adopt = FakeLane(store, [LaneResult('看到提案。'), decide(affect_adopt=[{'proposal_id': proposal['_id'], 'decision': 'accept',
                                                                          'why': '确实如此'}]), LaneResult('嗯。')])
    second = Coordinator(store, adopt).ingest(event('appraise-2'))
    assert 'affect_proposals_from_program' in json.dumps(adopt.calls[0], ensure_ascii=False)
    assert second['delta_results']['affect_adopt'][0]['event_id']             # 'appraise-1' passed via the snapshot
    assert [e['proposal_id'] for e in ledger.events()] == [proposal['_id']]
    # An undecided proposal past its TTL is shown as expired, not silently dropped.
    stale = {**proposal, '_id': 'stale-proposal', 'created_at': '2025-01-01T00:00:00+00:00'}
    store.db.affect_proposals.insert_one(stale)
    listed = ledger.proposals('scene:dm-a', 'owner_private')
    assert {'proposal_id': 'stale-proposal', 'status': 'expired'}.items() <= next(p for p in listed if p['proposal_id'] == 'stale-proposal').items()


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
