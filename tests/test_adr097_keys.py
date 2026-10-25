"""ADR-097 D1: her items come back by their exact words in the place they belong. A group note's rare heading words and
any item's tags are its keys; a message (or a recall's query) that has one brings the item up, whatever its vector
score, and says which word did it. A word common in the place, or an everyday word, is not a key; nor is anything in
a note's body."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import key_words, memory_pilot, memory_tiers
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.group_admin import notes_slug
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory_tiers import AT_HAND, PUT_AWAY, Tiers
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event
from test_memory_pilot import Route
from test_memory_tiers_delivery import Retrieval, write


def test_ascii_keys_are_whole_runs_and_chinese_keys_are_substrings():
    assert key_words.found('1017', '1017登记的') == '1017'
    assert key_words.found('1017', 'CVE-2026-101737') is None, 'a number inside a longer one is not that number'
    assert key_words.found('snowluma', '那是SnowLuma的状态') == 'SnowLuma', 'ASCII without case, in her spelling'
    assert key_words.found('破甲', '说破甲了吗') == '破甲'
    assert key_words.heading_words('1017是什么') == ('1017', '什么')


def test_a_word_is_a_key_only_when_rare_here_and_not_everyday():
    lines = ['大家好'] * 900 + ['破甲成功'] * 3 + ['注意这个'] * 100
    table = set(key_words.common(lines))
    note = {'store': 'group_notes', 'heading': '破甲注意大家'}
    assert key_words.keys(note, table) == ['破甲'], '大家 is common here; 注意 is an everyday word'
    assert key_words.keys({'store': 'persona', 'heading': '破甲'}, table) == [], 'only a group note gives heading keys'
    tagged = {'store': 'persona', 'heading': '破甲', 'tags': ['什么', '大家', 'place:g1', 'correction', '大家-v3']}
    assert key_words.keys(tagged, table) == ['什么', '大家-v3'], 'a tag is a key on any item when rare here, everyday ' \
        'or not (a tag of several runs when one of its pieces is); a tag common here is not, nor a place tag or the ' \
        'correction mark'
    assert key_words.tag_here('大家', lines) == key_words.TAG_HERE['common'] % ('大家', '没几句就有一句说到它')
    assert key_words.tag_here('注意', lines) == key_words.TAG_HERE['common'] % ('注意', '大约几十句里有一句说到它')
    assert key_words.tag_here('破甲', lines) == key_words.TAG_HERE['rare'] % '破甲'
    quiet = set(key_words.common(['破甲'] * 5))
    assert '破甲' not in quiet and '破甲' in set(key_words.common(['破甲'] * 6)), 'a quiet place: at most five lines'


@pytest.fixture
def group(store, monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    owner(store)
    docs = DocumentStore(store, 'P1')
    slug = notes_slug('g1')
    sids = {'version': write(docs, slug, '1017是哪一版', '一个模型版本，十月十七日发的'),
            'common': write(docs, slug, '大家的规矩', '群里不许刷屏'),
            'body': write(docs, slug, '一些说法', '这里说的破甲是绕过安全锁'),
            'persona': write(docs, 'persona', '1017', '我的一个日子')}
    tiers = Tiers(store, 'P1')
    tiers.sync()
    for doc, sid in [(slug, sids['version']), (slug, sids['common']), (slug, sids['body']), ('persona', sids['persona'])]:
        tiers.rows.update_one({'_id': tiers.item(doc, sid)['_id']}, {'$set': {'place': AT_HAND}})
    at = datetime.now(timezone.utc) - timedelta(hours=1)
    store.db.messages.insert_many([{'_id': 'line-%d' % n, 'schema_version': 1, 'scene_id': 'g1', 'policy_epoch': 1, 'direction': 'inbound', 'scene_seq': n,
                                    'text': '大家早', 'received_at': at.isoformat()} for n in range(10)])
    pilot = memory_pilot.Pilot(store, 'P1', Route())
    pilot.sync()
    builder = ContextBuilder(store, Retrieval())
    builder.pilot = pilot
    return store, builder, sids, tiers, slug


def own(context):
    return [m for m in context['memories'] if m.get('kind') == 'own_item']


def test_a_group_note_comes_back_by_its_rare_heading_word_and_says_so(group):
    store, builder, sids, tiers, slug = group
    _, context, _ = builder.prepare(event('e-1', scene='g1', text='1017是什么？'), 'P1')
    [item] = own(context)
    assert item['_id'] == 'doc:%s#%s' % (slug, sids['version'])
    assert item['why'] == '因为这句话里有「1017」', 'the word that brought it'
    _, plain, _ = builder.prepare(event('e-2', scene='g1', text='大家晚上好'), 'P1')
    assert not own(plain), 'a heading word common in this place is not a key'
    _, body, _ = builder.prepare(event('e-3', scene='g1', text='破甲是啥'), 'P1')
    assert not own(body), 'a word in the body is not a key'
    assert tiers.rows.find_one({'_id': 'rarity:P1:g1'})['lines'] == 10, 'the place table is kept'


def test_her_tag_is_a_key_on_any_item_and_she_is_told_how_common_it_is_here(group):
    store, builder, sids, tiers, slug = group
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'persona', 'do': 'set_tags', 'section': sids['persona'],
                                                                 'tags': ['大家', '星火'], 'why': '记个词'})], '好。')])
    ep = Coordinator(store, lane, context=builder).ingest(event('e-tag'))
    result = next(call['result'] for call in ep['tool_calls'].values() if call['tool'] == 'write_document')
    assert result['tags_here'] == [key_words.TAG_HERE['never'] % '大家', key_words.TAG_HERE['never'] % '星火'], \
        'told for the place she set it in (home has no lines yet)'
    builder.pilot.sync()
    _, context, _ = builder.prepare(event('e-1', text='星火是什么'), 'P1')
    assert [(m['_id'], m['why']) for m in own(context)] == [('doc:persona#' + sids['persona'], '因为这句话里有「星火」')]


def recall_turn(store, builder, args, scene='g1'):
    lane = FakeLane(store, [FakeTurn([THINK, ('recall', args)], '好。')])
    ep = Coordinator(store, lane, context=builder).ingest(event('e-recall-' + args['query'], scene=scene))
    return next(call['result'] for call in ep['tool_calls'].values() if call['tool'] == 'recall')


def test_recall_with_the_bare_word_finds_the_note_and_lists_headings_by_the_same_keys(group):
    store, builder, sids, tiers, slug = group
    tiers.rows.update_one({'_id': tiers.item(slug, sids['version'])['_id']}, {'$set': {'place': PUT_AWAY}})
    found = recall_turn(store, builder, {'query': '1017'})
    assert [m['_id'] for m in found['memories'] if m.get('kind') == 'own_item'] == ['doc:%s#%s' % (slug, sids['version'])], \
        'the bare word is enough, put away too'
    nothing = recall_turn(store, builder, {'query': '刷屏的规矩'})
    assert 'headings' not in nothing, 'no key: 规矩 is an everyday word, 刷屏 is in the body'


def test_the_exact_word_still_works_when_the_embedding_route_is_down(group):
    store, builder, sids, tiers, slug = group

    class Down(Retrieval):
        def embed(self, texts, purpose):
            raise RuntimeError('EMBEDDING_RESTING')
    builder.retrieval = Down()
    _, context, _ = builder.prepare(event('e-1', scene='g1', text='1017呢'), 'P1')
    assert [m['_id'] for m in own(context)] == ['doc:%s#%s' % (slug, sids['version'])]


def test_settlement_counts_every_place_again_and_drops_a_silent_one(group):
    store, builder, sids, tiers, slug = group
    tiers.rows.insert_one({'_id': 'rarity:P1:gone', 'row': 'rarity', 'persona': 'P1', 'scene_id': 'gone', 'common': []})
    assert tiers.rerate_all() == 1
    assert tiers.rows.find_one({'_id': 'rarity:P1:g1'})['lines'] == 10
    assert not tiers.rows.find_one({'_id': 'rarity:P1:gone'})
