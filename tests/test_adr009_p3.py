"""ADR-009 P3 MongoDB tests: affect commit gates, leak, append-only, appraiser, import."""
import json
import threading


from asuna.affect import AffectLedger
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.render import action_values
from conftest import FIXTURES
from test_adr009_p2 import owner, THINK
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
    secret = {'op': 'record', 'kind': 'attachment', 'intensity': '强烈', 'arousal': '激动', 'ref': 'private-1',
              'why': 'OWNER_SECRET_WHY', 'cost': 'OWNER_SECRET_COST'}
    private = FakeLane(store, [FakeTurn([THINK, ('feel', secret)], '嗯。')])
    Coordinator(store, private).ingest(event('private-1'))
    assert private.tool_results[1][5], private.tool_results[1]
    assert store.db.affect_events.find_one({'why': 'OWNER_SECRET_WHY'})          # the private feeling was recorded
    group = FakeLane(store, [FakeTurn([THINK], '大家好。')])
    ep = Coordinator(store, group).ingest(event('group-1', scene='g1'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    visible = json.dumps([ep['context'], group.calls], ensure_ascii=False) + action_values(store, 'P1')
    for value in ('OWNER_SECRET_WHY', 'OWNER_SECRET_COST', 'private-1', '靠近一点'):
        assert value not in visible, value
    block = ep['context']['affect_from_program']
    assert {'label', 'policy', 'tendencies', 'note'} <= set(block) and block['label']
    assert ep['context']['how_to_record_from_program']['kinds']          # how to record is its own block
    assert not set(block) & {'val', 'arl', 'reasons', 'main_feelings', 'contributions'}
    assert all(slot['slot'] != '提要求' for slot in block['policy'])      # owner-private slot hidden


def test_T3_8_she_reads_and_writes_feelings_in_words_and_the_same_state_reads_the_same(store):
    """AGENTS.md: computed state reaches the model only as interpreted text; she records in words."""
    from asuna.affect import interpret
    import re
    ledger = setup(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('feel', {'op': 'record', 'kind': 'joy', 'intensity': '明显', 'arousal': '有些波动',
                                                      'ref': 'happy-1', 'why': '他夸了我', 'cost': '有点不好意思'}),
                                      ('feel', {'op': 'record', 'kind': 'joy', 'intensity': '很多很多', 'ref': 'happy-1',
                                                'why': '不在词表里'})], '嗯。')])
    ep = Coordinator(store, lane).ingest(event('happy-1'))
    assert 'feel' in lane.calls[0]['tools'] and ep['state'] == 'COMMITTED', ep.get('failure')
    stored = store.db.affect_events.find_one({'why': '他夸了我'})
    assert stored, lane.tool_results
    scale = ledger.model['scale']
    assert (stored['val'], stored['arl']) == (scale['val']['明显'], scale['arl']['有些波动'])
    _, recorded, unknown = lane.tool_results
    assert recorded[5] and recorded[4]['event_id'] == stored['_id']
    # A word outside her table is refused back to her in words; nothing is stored for it.
    assert not unknown[5] and 'AFFECT_INTENSITY_UNKNOWN' in unknown[4]
    assert not store.db.affect_events.find_one({'why': '不在词表里'})
    from datetime import datetime, timedelta
    at = (datetime.fromisoformat(stored['ts']) + timedelta(hours=1)).isoformat()   # one fixed moment
    state = ledger.projection(at)
    first, again = interpret(ledger.model, state, 'owner_private'), interpret(ledger.model, ledger.projection(at), 'owner_private')
    assert first == again and first['reasons'][0]['why'] == '他夸了我'
    numbers = re.compile(r'\d')
    text = json.dumps({k: v for k, v in first.items() if k != 'reasons'}, ensure_ascii=False) +         json.dumps([{k: v for k, v in row.items() if k not in ('event_id', 'when')} for row in first['reasons']], ensure_ascii=False)
    assert not numbers.search(text), text


class BlockingLane:
    def __init__(self, reply):
        self.reply, self.release, self.called = reply, threading.Event(), threading.Event()

    def generate(self, binding, operation, phase, text, system, **_delivery):
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
