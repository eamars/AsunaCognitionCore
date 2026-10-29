"""ADR-097 D3/D4 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): by default only her own
lines leave a group and never her thoughts; a place set to never gives nothing, checked again at the fetch; a
mention crosses as someone."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from asuna import crossing, memory_pilot, memory_tiers
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.evidence import canonical, sha
from asuna.lanes import FakeLane, FakeTurn

from turn_parts import Retrieval, Route, event, owner

pytestmark = pytest.mark.world                # `store` is the fixture world

AT = datetime.now(timezone.utc) - timedelta(days=2)

THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


@pytest.fixture(autouse=True)
def fresh_words():
    """What the segmenter learned belongs to a process: each test starts and ends with nothing learned."""
    from asuna import key_words
    key_words.learn([])
    crossing._loaded.clear()
    yield
    key_words.learn([])
    crossing._loaded.clear()


def unit_id(scene, n):
    """A line's chunk id as the indexer makes it (memory.chunk): opaque, no place in it."""
    return 'chunk-' + sha(canonical(['m-%s-%d' % (scene, n), 2, 0]))


def line(store, n, text, mine, *, scene='g2', kind='chat_chunk', reply_to=None):
    me = store.config['character_id']
    when = (AT + timedelta(minutes=n)).isoformat()
    if kind == 'chat_chunk':                # a thought is no line of the conversation, only a unit of hers
        store.raw.messages.insert_one({'_id': 'm-%s-%d' % (scene, n), 'schema_version': 1, 'scene_id': scene,
                                      'policy_epoch': 1, 'scene_seq': n, 'direction': 'outbound' if mine else 'inbound',
                                      'author': me if mine else 'B', 'text': text, 'received_at': when,
                                      'memory_chunk_version': 2,
                                      **({'delivery_state': 'DELIVERED'} if mine else {}),
                                      **({'event': {'group_context': {'reply_message_id': reply_to}}} if reply_to else {})})
    store.raw.memory_units.insert_one({'_id': unit_id(scene, n) if kind == 'chat_chunk' else 'mono-%s-%d' % (scene, n),
                                      'schema_version': 1,
                                      'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'character_id': me,
                                      'kind': kind, 'body_markdown': text, 'status': 'active',
                                      'epistemic_type': 'public_statement' if mine else 'reported_speech',
                                      'speaker': me if mine else 'B', 'scene_seq': n, 'occurred_at': when,
                                      'source_event_ids': ['m-%s-%d' % (scene, n)], 'formed_at': when})


@pytest.fixture
def places(store, monkeypatch, tmp_path):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    monkeypatch.setattr(crossing, 'PATH', tmp_path / 'memory-crossing.json')
    owner(store)
    line(store, 1, '大家早', False)
    line(store, 2, '1017就是十月十七日发的那一版模型', False)
    line(store, 3, '1017我看过模型卡了', True)
    line(store, 4, '那就好', False)
    line(store, 5, '我在想1017的事', True, kind='monologue')
    pilot = memory_pilot.Pilot(store, 'P1', Route())
    builder = ContextBuilder(store, Retrieval())
    builder.pilot = pilot
    return store, builder, tmp_path / 'memory-crossing.json'


def rules(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def recall(store, builder, args, scene='g1', key='r'):
    lane = FakeLane(store, [FakeTurn([THINK, ('recall', args)], '好。')])
    ep = Coordinator(store, lane, context=builder).ingest(event('e-%s-%s' % (key, args.get('query')), scene=scene))
    return next(call['result'] for call in ep['tool_calls'].values() if call['tool'] == 'recall')


def test_by_default_only_her_own_lines_leave_a_group_and_never_her_thoughts(places):
    store, builder, path = places
    found = recall(store, builder, {'query': '1017是什么'})
    assert [e['line'] for e in found['elsewhere']] == ['你在别处说过：1017我看过模型卡了']
    assert found['elsewhere'][0]['ref'] == unit_id('g2', 3) and 'kind' not in found['elsewhere'][0]
    assert found['elsewhere_how'] == crossing.HOW
    assert 'g2' not in json.dumps(found['elsewhere'], ensure_ascii=False), 'no place in what crosses'
    assert '在想' not in json.dumps(found, ensure_ascii=False), 'a thought never crosses'


def test_a_place_set_to_never_gives_nothing_and_its_rule_is_checked_again_at_the_fetch(places):
    store, builder, path = places
    rules(path, {'places': {'g2': 'all'}})
    ref = recall(store, builder, {'query': '1017'})['elsewhere'][0]['ref']
    around = recall(store, builder, {'sections': [{'doc': 'elsewhere', 'sid': ref}]}, key='f1')
    [section] = around['documents']
    assert [(l['who'], l['text']) for l in section['lines']] == [('别人', '大家早'), ('别人', '1017就是十月十七日发的那一版模型'),
                                                                ('你', '1017我看过模型卡了'), ('别人', '那就好')], \
        'the lines around it, speakers only as 你 or 别人'
    rules(path, {'places': {'g2': 'own_lines'}})
    mine = recall(store, builder, {'sections': [{'doc': 'elsewhere', 'sid': ref}]}, key='f2')['documents'][0]
    assert [l['who'] for l in mine['lines']] == ['你'] and mine['left_out'] == crossing.LEFT_OUT
    rules(path, {'places': {'g2': 'never'}})
    assert 'elsewhere' not in recall(store, builder, {'query': '1017'}, key='n')
    refused = recall(store, builder, {'sections': [{'doc': 'elsewhere', 'sid': ref}]}, key='f3')
    assert refused['not_read'] == [crossing.MISSING['never'] % ('elsewhere', ref)]
    here = recall(store, builder, {'sections': [{'doc': 'elsewhere', 'sid': ref}]}, scene='g2', key='f4')
    assert here['not_read'] == [crossing.MISSING['here'] % ('elsewhere', ref)]


def test_a_mention_crosses_as_someone(places, monkeypatch):
    store, builder, path = places
    import re

    class Platform:
        INBOUND_MENTION = re.compile(r'@(\d{5,12})')
    from asuna import channel_kinds
    monkeypatch.setattr(channel_kinds, 'of', lambda scene_id: Platform)
    assert crossing._clean(store, 'g2', '@123456 1017呢') == '@某人 1017呢'


