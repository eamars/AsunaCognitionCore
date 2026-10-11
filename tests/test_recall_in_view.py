"""A recalled record says when it was said, on her history's clock face; a recall says what it held back because she
still sees it, and where that is (ADR-043)."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import schedule_rules
from asuna.context import ContextBuilder
from asuna.evidence import Evidence
from asuna.retrieval import Retrieval


@pytest.fixture
def retrieval(store, tmp_path):
    value = Retrieval(store, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def at(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def chunk(store, unit_id, seq, body, source, **extra):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.db.memory_units.insert_one({'_id': unit_id, 'schema_version': 1, 'scope_key': scene['scope_key'],
                                      'policy_epoch': scene['policy_epoch'], 'character_id': 'demo', 'status': 'active',
                                      'kind': 'chat_chunk', 'epistemic_type': 'reported_speech', 'scene_seq': seq,
                                      'body_markdown': body, 'source_event_ids': [source], **extra})


def test_a_recall_counts_what_she_still_sees_only_when_it_would_have_made_the_cut(store, retrieval):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    chunk(store, 'seen', 901, '蓝莓松饼周六烤', 'm-seen', occurred_at=at(1))
    chunk(store, 'older', 902, '蓝莓松饼上次烤糊了', 'm-older', occurred_at=at(30))
    memories, manifest = retrieval.search(scene['scope_key'], scene['policy_epoch'], '蓝莓松饼', exclude_sources=['m-seen'],
                                          automatic=False)
    ids = [m['_id'] for m in memories]
    assert ids[0] == 'older' and 'seen' not in ids and len(ids) < 6
    assert manifest['in_view'] == ['seen'], 'fewer than six came back: everything held back for being in view counts'


def test_a_record_is_dated_by_the_line_it_came_from(store):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    zone = schedule_rules.scene_timezone(store.config, scene)
    sent = at(4)
    store.db.messages.insert_many([
        {'_id': 'm-out', 'schema_version': 1, 'scene_id': 'dm-a', 'scene_seq': 950, 'direction': 'outbound',
         'receipt_at': sent},
        {'_id': 'm-in', 'schema_version': 1, 'scene_id': 'dm-a', 'scene_seq': 960, 'direction': 'inbound',
         'received_at': at(26)}])
    builder = ContextBuilder(store)
    moment = datetime.now(timezone.utc)
    said = {'kind': 'chat_chunk', 'scope_key': scene['scope_key'], 'scene_seq': 950, 'formed_at': at(3)}
    summary = {'kind': 'dialogue_summary', 'scope_key': scene['scope_key'], 'source_window': [940, 960], 'generated_at': at(1)}
    thought = {'kind': 'monologue', 'scope_key': scene['scope_key'], 'formed_at': at(2)}
    assert builder.when(said, zone, moment) == schedule_rules.line_stamp(zone, sent) + '（4 小时前）', \
        'her own line is dated by its receipt, not by when it was indexed'
    assert builder.when(summary, zone, moment).endswith('（26 小时前）'), 'a summary by the last line it covers'
    assert builder.when(thought, zone, moment).endswith('（2 小时前）')
    assert builder.when({'kind': 'chat_chunk', 'scope_key': 'global-safe'}, zone, moment) is None


def test_a_recall_that_held_records_back_says_they_are_in_front_of_her(store):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    chunk(store, 'seen', 901, '蓝莓松饼周六烤', 'm-seen')
    store.db.messages.insert_one({'_id': 'm-seen', 'schema_version': 1, 'scene_id': 'dm-a', 'scene_seq': 901,
                                  'direction': 'inbound', 'received_at': '2026-10-11T06:16:00+00:00'})

    class InView:
        def search(self, *args, **kwargs):
            return [], {'path': 'stub', 'coverage': 'insufficient', 'in_view': ['seen']}
    event = {'event_id': 'e-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '蓝莓松饼'}
    _, asked, _ = ContextBuilder(store, InView()).prepare(event, 'P1', recall=True)
    stamp = schedule_rules.line_stamp(schedule_rules.scene_timezone(store.config, scene), '2026-10-11T06:16:00+00:00')
    assert asked['held_back_from_program'] == '另有 1 条相关的没重复给：都在你眼前这段对话里（最早是 %s 那条）。' % stamp
    assert 'coverage_from_program' not in asked, 'not "you remember nothing": the rest is in front of her'
    _, turn, _ = ContextBuilder(store, InView()).prepare(event, 'P1')
    assert 'held_back_from_program' not in turn, 'only a recall she asked for says it'


def test_her_last_thoughts_are_in_view_and_an_older_one_comes_back(store, retrieval):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.db.memory_units.delete_many({'kind': 'monologue'})              # the fixture world's thoughts are dated now
    for n in range(4):
        store.db.memory_units.insert_one({'_id': 'mono-%d' % n, 'schema_version': 1, 'scope_key': scene['scope_key'],
                                          'policy_epoch': scene['policy_epoch'], 'character_id': 'demo', 'status': 'active',
                                          'kind': 'monologue', 'epistemic_type': 'character_interpretation',
                                          'body_markdown': '蓝莓松饼要不要再烤一次 %d' % n, 'formed_at': at(4 - n)})
    event = {'event_id': 'e-2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '蓝莓松饼'}
    _, asked, _ = ContextBuilder(store, retrieval).prepare(event, 'P1', recall=True)
    thoughts = [m['_id'] for m in asked['memories'] if m['kind'] == 'monologue']
    assert thoughts == ['mono-0'], 'the last three reach every turn anyway; the fourth is only in recall'
    assert asked['held_back_from_program'].startswith('另有 3 条相关的没重复给')
