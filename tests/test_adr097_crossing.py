"""ADR-097 D3/D4: recall with a word reaches her other groups' lines and the past versions of her notes. A place's rule
decides what leaves it (own lines by default, everything, or nothing), checked again when she reads around a line;
what crosses never names the place, the speaker or anyone mentioned; her thoughts never cross."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from asuna import crossing, memory_pilot, memory_tiers
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.evidence import canonical, sha
from asuna.group_admin import notes_slug
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory_tiers import Tiers
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event
from test_memory_pilot import Route
from test_memory_tiers_delivery import Retrieval, write

AT = datetime.now(timezone.utc) - timedelta(days=2)


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
        store.db.messages.insert_one({'_id': 'm-%s-%d' % (scene, n), 'schema_version': 1, 'scene_id': scene,
                                      'policy_epoch': 1, 'scene_seq': n, 'direction': 'outbound' if mine else 'inbound',
                                      'author': me if mine else 'B', 'text': text, 'received_at': when,
                                      'memory_chunk_version': 2,
                                      **({'delivery_state': 'DELIVERED'} if mine else {}),
                                      **({'event': {'group_context': {'reply_message_id': reply_to}}} if reply_to else {})})
    store.db.memory_units.insert_one({'_id': unit_id(scene, n) if kind == 'chat_chunk' else 'mono-%s-%d' % (scene, n),
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


def test_a_place_set_to_all_also_gives_others_lines_ranked_after_hers_explanation_first(places):
    store, builder, path = places
    rules(path, {'places': {'g2': 'all'}, 'kinds': {'g2': '技术局'}})
    found = recall(store, builder, {'query': '1017'})
    assert [e['line'] for e in found['elsewhere']] == ['你在别处说过：1017我看过模型卡了',
                                                       '别人提过：1017就是十月十七日发的那一版模型']
    assert {e['kind'] for e in found['elsewhere']} == {'技术局'}


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


def test_a_corrected_line_comes_back_marked_with_its_correction(places):
    store, builder, path = places
    rules(path, {'places': {'g2': 'all'}})
    line(store, 6, '破甲是被骗了', False)
    line(store, 7, '说错了，破甲是绕过安全锁', False, reply_to='m-g2-6')
    found = recall(store, builder, {'query': '破甲'})
    marked = [e for e in found['elsewhere'] if e['ref'] == unit_id('g2', 6)]
    assert marked and marked[0]['line'] == '已被更正·别人此前提过：破甲是被骗了'
    assert marked[0]['correction'] == '别人后来更正：说错了，破甲是绕过安全锁'


def test_a_past_version_comes_back_for_a_word_its_section_lost(places, monkeypatch):
    store, builder, path = places
    docs = DocumentStore(store, 'P1')
    slug = notes_slug('g1')
    sid = write(docs, slug, '模型的事', '1017是十月十七日那版，SnowLuma也在')
    docs.apply(slug, {'op': 'replace_section', 'sid': sid, 'reason': '写短一点'}, '版本的事记在别处了，SnowLuma',
               base_revision_id=docs.read(slug)[0], author='character', mutation_id='trim')
    Tiers(store, 'P1').sync()
    found = recall(store, builder, {'query': '1017'})
    [entry] = found['before']
    assert entry['line'].startswith('你以前记过：1017是十月十七日那版，SnowLuma也在（改于 ') and entry['line'].endswith('：写短一点）')
    assert entry['now'] == 'doc:%s#%s' % (slug, sid)
    assert 'before' not in recall(store, builder, {'query': 'SnowLuma'}, key='still'), 'the current text still has it'
    assert 'before' not in recall(store, builder, {'query': '版本'}, key='word'), 'a dictionary word never crosses'
    assert 'before' not in recall(store, builder, {'query': '1017'}, scene='g2', key='g2'), 'notes stay in their group'
    today = datetime.now(timezone.utc).astimezone(timezone.utc).date().isoformat()
    rules(path, {'history_excluded': [[today, today]]})
    monkeypatch.setattr(crossing, '_local_date', lambda value, zone: today)
    assert 'before' not in recall(store, builder, {'query': '1017'}, key='excluded'), 'an excluded day'
    rules(path, {})
    tiers = Tiers(store, 'P1')
    tiers.store.db['memory_tiers'].update_one({'_id': tiers.item(slug, sid)['_id']}, {'$set': {'from': crossing.OWN_JUDGMENT}})
    assert 'before' not in recall(store, builder, {'query': '1017'}, key='judged'), 'her marked judgment'


def test_a_sentence_crosses_only_through_its_rare_words_and_not_what_this_place_says_itself(places):
    store, builder, path = places
    assert 'elsewhere' not in recall(store, builder, {'query': '我看过的那个模型卡'}), 'dictionary words never cross'
    for n in range(3):
        line(store, 20 + n, '1017又来了', False, scene='g1')
    Tiers(store, 'P1').rerate_all()                      # the night recount: the place's tables are a day old at most
    assert 'elsewhere' not in recall(store, builder, {'query': '1017'}, key='said'),         'said three times here: its own memories cover it'


def test_the_word_index_takes_new_lines_at_recall_and_a_rebuild_keeps_one_generation(places):
    store, builder, path = places
    rules(path, {'places': {'g2': 'all'}})
    assert recall(store, builder, {'query': 'SnowLuma'}, key='before').get('elsewhere') is None
    line(store, 30, 'SnowLuma是一个框架的状态', True)
    line(store, 31, 'SnowLuma又刷屏了', False)
    line(store, 32, 'SnowLuma就是那个机器人框架', False)
    found = recall(store, builder, {'query': 'SnowLuma'}, key='after')
    assert [e['ref'] for e in found['elsewhere']] == [unit_id('g2', 30), unit_id('g2', 32)],         'a line said after the index was built is found at the next recall; at most two, hers then the explanation'
    words = crossing.build(store)
    column = store.db[crossing.WORDS]
    assert column.count_documents({'row': 'word'}) == words, 'one generation after a rebuild'
    assert not column.find_one({'row': 'word', 'body_markdown': {'$exists': True}}), 'no text in the index'
    assert recall(store, builder, {'query': 'SnowLuma'}, key='rebuilt')['elsewhere'][0]['ref'] == unit_id('g2', 30)
