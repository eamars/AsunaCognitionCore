"""ADR-117 L1: a turn whose message is program text brings memories up but counts nothing, while her own recall in it
still counts (D1); and the chunks of one long message take one of the six memory slots, joined in segment order
(D7). On the unit run's store holding the fixture world; the embedding route is never reached (lexical recall)."""
import pytest

from asuna import clock, crossing, memory_tiers
from asuna.context import ContextBuilder
from asuna.evidence import Evidence
from asuna.records import memories as memory_records
from asuna.records import scenes as scene_records
from asuna.retrieval import Retrieval
from asuna.store.words import Set

WORD = 'zephyrine'           # a tag of hers (ASCII: a key in any place), and the word the units say
PERSONA = 'P1'


@pytest.fixture
def retrieval(world, tmp_path, monkeypatch):
    value = Retrieval(world, Evidence(tmp_path / 'evidence'))

    def down(texts, purpose):
        raise RuntimeError('EMBEDDING_DOWN')
    monkeypatch.setattr(value, 'embed', down)
    yield value
    value.close()


def unit(world, memory_id, body, scene_id='dm-a', **fields):
    scene = scene_records.get(world, scene_id)
    return {'_id': memory_id, 'schema_version': 1, 'scope_key': scene['scope_key'],
            'policy_epoch': scene['policy_epoch'], 'character_id': world.config['character_id'], 'status': 'active',
            'kind': 'chat_chunk', 'epistemic_type': 'public_statement', 'body_markdown': body,
            'embedding_status': 'READY', 'occurred_at': '2026-09-20T01:00:00+00:00', **fields}


class Items:
    """The item index as a turn reads it (memory_pilot.Pilot): her items, and a queue it never scores."""

    def __init__(self, items):
        self.items = items

    def submit(self, **job):
        pass


def item(sid):
    return {'key': 'shadow:' + sid, 'store': 'self', 'doc': 'self', 'sid': sid, 'scope_key': 'global-safe',
            'visibility': 'public', 'inject': None, 'text': 'about ' + WORD, 'heading': sid, 'tags': [WORD],
            'lexical': sid + '\nabout ' + WORD}


def test_a_heartbeat_brings_memories_up_but_counts_nothing_and_her_recall_in_it_counts(world, retrieval):
    tiers = memory_tiers.Tiers(world, PERSONA)
    for sid, place in (('hand', memory_tiers.AT_HAND), ('held', memory_tiers.CARRIED)):
        row = tiers._new('self', sid, 'self', {'heading': sid, 'body': 'about ' + WORD}, place, clock.now())
        # Surfaced in another conversation before: one more conversation would be a memorable moment.
        world.collection('memory_tiers').update({'_id': row['_id']}, Set({'surfaced_in': ['elsewhere']}))
    world.collection('memory_units').insert([unit(world, 'u-word', 'she said ' + WORD, source_event_ids=['m-far'])])
    builder = ContextBuilder(world, retrieval)
    builder.pilot = Items([item('hand'), item('held')])
    before = {row['sid']: row for row in tiers.items(doc='self')}
    event = {'event_id': 'presence:beat-1', 'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'presence',
             'text': 'a heartbeat about ' + WORD}

    _, context, manifest = builder.prepare(event, PERSONA)
    assert 'doc:self#hand' in [m['_id'] for m in context['memories']], 'her item still comes up'
    assert 'u-word' in manifest['retrieval']['selected'], 'the memory still comes up'
    after = {row['sid']: row for row in tiers.items(doc='self')}
    for sid in ('hand', 'held'):
        assert after[sid].get('surfaced_in') == ['elsewhere'] and 'last_use_at' not in after[sid], sid
        assert (after[sid]['memorable_at'], after[sid]['uses']) == (before[sid]['memorable_at'], 0), \
            'no memorable moment'
    assert (manifest['carried']['brought_up'], manifest['carried']['would_surface']) == ([], []), \
        'nothing for program_score'
    assert 'salience' not in memory_records.get(world, 'u-word'), 'no rehearsal'
    assert crossing.fire_rows(world, '2000-01-01').rows() == [], 'no came-back count'

    # Her own recall inside the same heartbeat counts.
    builder.prepare({**event, 'text': WORD}, PERSONA, recall=True, turn_kind='presence')
    recalled = tiers.item('self', 'hand')
    assert recalled.get('recalled_in') == ['dm-a'] and recalled['uses'] == 1
    assert memory_records.get(world, 'u-word')['salience']['ref_count'] == 1

    # The same message from someone counts, as before: the checks above were not empty.
    _, _, said = builder.prepare({**event, 'event_id': 'ev-said', 'episode_kind': 'external'}, PERSONA)
    assert said['carried']['brought_up'] == ['doc:self#hand'] and said['carried']['would_surface'] == ['doc:self#held']
    assert sorted(tiers.item('self', 'held')['surfaced_in']) == ['dm-a', 'elsewhere']
    assert [row['kind'] for row in crossing.fire_rows(world, '2000-01-01').rows()] == ['note']
    assert memory_records.get(world, 'u-word')['salience']['ref_count'] == 2


def test_two_halves_of_one_long_message_take_one_slot_joined_in_segment_order(world, retrieval):
    halves = {'u1-second': (1, WORD + ' again at its end.'), 'u2-first': (0, 'A long line about ' + WORD + ', ')}
    singles = ['u%d-single' % n for n in range(3, 8)]
    world.collection('memory_units').insert([
        *(unit(world, key, body, segment_index=index, segment_count=2, source_event_ids=['m-long'])
          for key, (index, body) in halves.items()),
        *(unit(world, key, 'another line about ' + WORD, segment_index=0, segment_count=1,
               source_event_ids=['m-' + key]) for key in singles),
        *(unit(world, 'filler-%d' % n, 'nothing to do with it', source_event_ids=['m-filler-%d' % n])
          for n in range(10))])
    scene = scene_records.get(world, 'dm-a')

    selected, manifest = retrieval.search(scene['scope_key'], scene['policy_epoch'], WORD)
    assert len(selected) == 6
    joined = [m for m in selected if m['_id'] in halves]
    assert len(joined) == 1, 'one entry for the message'
    assert joined[0]['body_markdown'] == 'A long line about %s, %s again at its end.' % (WORD, WORD), \
        'its halves in segment order, though the second ranked first'
    assert {m['_id'] for m in selected} - set(halves) == set(singles), 'the slot it freed went to the next memory'
    assert set(manifest['selected']) == {*halves, *singles}, 'both halves stay in the manifest'

    # Segments 0 and 2 of a three-part message: the missing middle reads as '…', never as glued text.
    world.collection('memory_units').insert([
        unit(world, 'v-%d' % index, body, 'dm-b', segment_index=index, segment_count=3, source_event_ids=['m-three'])
        for index, body in ((0, 'It starts with %s' % WORD), (2, '%s at the very end.' % WORD))])
    other = scene_records.get(world, 'dm-b')
    selected, manifest = retrieval.search(other['scope_key'], other['policy_epoch'], WORD)
    assert [m['body_markdown'] for m in selected if m['_id'] in ('v-0', 'v-2')] == \
        ['It starts with %s…%s at the very end.' % (WORD, WORD)]
    assert {'v-0', 'v-2'} <= set(manifest['selected'])
