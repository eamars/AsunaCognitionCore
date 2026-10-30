"""ADR-108 D2: a claim that someone said something rests on the line that said it. `line` resolves in the conversation and
sets `from`; without one, or when it is not a line, the claim is recorded as her own judgment; the item remembers its line
exactly while it is someone's word; a reader sees where it rests."""
from types import SimpleNamespace

import pytest

from asuna import memory_tiers
from asuna.config import character_id
from asuna.documents import DocumentStore
from asuna.ingress import persist_input
from asuna.people import People
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records
from asuna.role_tools import RoleTools
from test_people import BOT, SCENE

OWNER, OTHER = 'qq:20001', 'qq:20002'
OTHER_SCENE = 'qq:%s:group:81000' % BOT


@pytest.fixture
def world(store):
    store.config['chat'] = {**store.config.get('chat', {}), 'person_id': 'local-user', 'persona': 'demo', 'display_name': '演示'}
    store.config.pop('persona_model', None)
    store.config['canonical_persons'] = {OWNER: 'local-user'}
    for scene_id in (SCENE, OTHER_SCENE):
        scene_records.save(store, {'_id': scene_id, 'kind': 'group', 'scope_key': 'scene:' + scene_id,
                                  'channel_account_id': BOT, 'policy_epoch': 1, 'sequence': 0, 'members': [OWNER, OTHER]})
    lines = {}
    for name, person in (('owner', OWNER), ('other', OTHER)):
        lines[name], _ = persist_input(store, {'event_id': 'evt-' + name, 'scene_id': SCENE, 'person_id': person,
                                               'text': '明天下午三点开会', 'received_at': '2026-10-29T08:00:00+00:00'})
    seq = scene_records.next_seq(store, SCENE)
    hers = message_records.save(store, {'_id': 'out-1', 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1,
                                        'scene_seq': seq, 'direction': 'outbound', 'delivery_state': 'DELIVERED',
                                        'author': character_id(store.config), 'text': '好的', 'phase': 'SPEAK',
                                        'received_at': '2026-10-29T08:01:00+00:00'}, stream='out-1')
    tools = RoleTools(SimpleNamespace(store=store))
    ep = {'_id': 'ep-write', 'scene_id': SCENE, 'persona': 'demo'}
    return SimpleNamespace(store=store, tools=tools, ep=ep, owner=lines['owner'], other=lines['other'], hers=hers)


def resolve(world, **item):
    return world.tools._anchored(world.ep, {'op': 'append_section', 'heading': 'h', **item})


def test_a_line_sets_from_by_whose_it_is_and_the_item_remembers_it(world):
    item, note = resolve(world, line=str(world.owner['scene_seq']))
    assert item['from'] == '主人定的' and item['anchor'] == {'scene': SCENE, 'seq': world.owner['scene_seq']}
    assert 'line' not in item and note.startswith('记成「主人定的」，出自 〔%d〕' % world.owner['scene_seq'])
    assert '明天下午三点开会' in note, 'her check is in front of her at write time: the line\'s opening words'
    item, note = resolve(world, line=world.other['scene_seq'])
    assert item['from'] == '别人说的' and item['anchor']['seq'] == world.other['scene_seq']


def test_her_own_line_a_line_that_is_not_one_and_a_missing_line_are_her_own_judgment(world):
    for given in ({'line': world.hers['scene_seq']}, {'line': '99'}, {'from': '别人说的'}, {'from': '主人定的'},
                  {'from': '别人说的', 'line': '99'}):
        item, note = resolve(world, **given)
        assert item['from'] == '我自己的判断' and 'anchor' not in item, given
        assert '我自己的判断' in note, given
        assert ('set_tags' in note) == (given.get('line') != world.hers['scene_seq']), 'the remedy only where a line may turn up'
    assert '不是这里的一行' in resolve(world, line='99')[1]
    assert '没有指到哪一行' in resolve(world, **{'from': '别人说的'})[1]
    assert '你自己说的' in resolve(world, line=world.hers['scene_seq'])[1]


def test_the_other_sources_stand_as_she_wrote_them_and_a_from_that_differs_is_replaced(world):
    for source in ('查过的', '我自己的判断'):
        item, note = resolve(world, **{'from': source})
        assert item['from'] == source and 'anchor' not in item and note is None
    item, note = resolve(world, **{'from': '查过的', 'line': world.other['scene_seq']})
    assert item['from'] == '查过的' and 'anchor' not in item and 'line 没用上' in note
    item, note = resolve(world, **{'from': '别人说的', 'line': world.owner['scene_seq']})
    assert item['from'] == '主人定的' and '按那一行改了' in note
    assert resolve(world) == ({'op': 'append_section', 'heading': 'h'}, None), 'a write that names no source is not touched'


def test_a_downgrade_goes_through_and_a_nature_she_gave_as_fact_goes_with_it(world):
    """Her own judgment is a fact only once someone confirms it (memory_tiers.signing): the write must not be refused for that."""
    from asuna import memory_tiers
    item, note = resolve(world, **{'from': '别人说的', 'nature': '事实'})
    assert item['from'] == '我自己的判断' and 'nature' not in item and '没有记成事实' in note
    assert memory_tiers.signing(None, item, '正文') is None, 'nothing left for signing to refuse'
    item, _ = resolve(world, **{'from': '别人说的', 'nature': '记忆'})
    assert item['nature'] == '记忆', 'a nature that is not fact stays'


def test_a_source_restated_beside_a_line_it_already_rests_on_keeps_it(world):
    from asuna import memory_tiers
    store = world.store
    docs = DocumentStore(store, 'demo')
    docs.apply('notes', {'op': 'append_section', 'heading': '会议', 'reason': '记', 'kind': 'ledger'}, '明天开会',
               base_revision_id=None, author='character', mutation_id='m-restate')
    _, content = docs.read('notes')
    sid = content['sections'][0]['sid']
    tiers = memory_tiers.Tiers(store, 'demo')
    anchor = {'scene': SCENE, 'seq': world.other['scene_seq']}
    tiers.written('notes', {'op': 'set_tags', 'sid': sid, 'from': '别人说的', 'anchor': anchor}, content, content, scene_id=SCENE)
    restated = {'op': 'set_tags', 'sid': sid, 'doc': 'notes', 'from': '别人说的', 'tags': ['x']}
    item, note = world.tools._anchored(world.ep, restated)
    assert item['from'] == '别人说的' and note is None, 'not downgraded: the line it rests on is still there'
    tiers.written('notes', item, content, content, scene_id=SCENE)
    assert tiers.item('notes', sid)['line'] == anchor
    other, _ = world.tools._anchored(world.ep, {**restated, 'sid': 'no-such-section'})
    assert other['from'] == '我自己的判断', 'restated on an item with no line: recorded as hers'


def test_a_line_an_erasure_redacted_reads_as_gone_not_as_who_said_it(world):
    from asuna.records.view import redact
    store = world.store
    people = People(store, 'demo')
    anchor = {'scene': SCENE, 'seq': world.other['scene_seq']}
    here = scene_records.get(store, SCENE)
    assert people.source_of(here, anchor).startswith('〔')
    redact(store, 'messages', here['scope_key'], 'deletion-1', 2)
    assert people.source_of(here, anchor) == People.SOURCE_GONE


def test_what_was_decided_is_reported_by_field_for_the_audit(world):
    world.tools._anchored(world.ep, {'op': 'append_section', 'heading': 'h', 'from': '别人说的'})
    assert world.tools.__dict__.pop('report') == {'asked': '别人说的', 'line_named': False, 'recorded': '我自己的判断', 'anchored': False}
    world.tools._anchored(world.ep, {'op': 'append_section', 'heading': 'h', 'line': str(world.other['scene_seq'])})
    assert world.tools.__dict__.pop('report') == {'asked': None, 'line_named': True, 'recorded': '别人说的', 'anchored': True}
    world.tools._anchored(world.ep, {'op': 'append_section', 'heading': 'h'})
    assert 'report' not in world.tools.__dict__, 'a write that names no source reports nothing'


def test_an_anchor_she_writes_herself_is_never_taken(world):
    item, _ = resolve(world, **{'anchor': {'scene': SCENE, 'seq': 1}, 'from': '别人说的'})
    assert 'anchor' not in item and item['from'] == '我自己的判断'


def test_the_item_has_its_line_exactly_while_it_is_someones_word(world):
    store = world.store
    docs = DocumentStore(store, 'demo')
    docs.apply('notes', {'op': 'append_section', 'heading': '会议', 'reason': '记一下', 'kind': 'ledger'}, '明天开会',
               base_revision_id=None, author='character', mutation_id='m-1')
    _, before = docs.read('notes')
    sid = before['sections'][0]['sid']
    tiers = memory_tiers.Tiers(store, 'demo')
    anchor = {'scene': SCENE, 'seq': world.other['scene_seq']}

    def write(**fields):
        tiers.written('notes', {'op': 'set_tags', 'sid': sid, **fields}, before, before, scene_id=SCENE)
        return tiers.item('notes', sid)

    assert write(**{'from': '别人说的', 'anchor': anchor})['line'] == anchor
    assert write(tags=['x']).get('line') == anchor, 'a write that restates neither keeps both'
    replaced = {'scene': SCENE, 'seq': world.owner['scene_seq']}
    row = write(**{'from': '主人定的', 'anchor': replaced})
    assert row['line'] == replaced and row['from'] == '主人定的', 'a new line replaces it'
    assert 'line' not in write(**{'from': '查过的'}), 'another source removes it'
    assert 'line' not in write(**{'from': '别人说的'}), 'someone\'s word with no line to rest on keeps none'
    assert write(**{'from': '别人说的', 'anchor': anchor})['line'] == anchor
    assert 'line' not in write(**{'from': '我自己的判断'})


def test_a_reader_sees_where_the_claim_rests_in_the_words_of_where_she_reads(world):
    store = world.store
    people = People(store, 'demo')
    here, elsewhere = scene_records.get(store, SCENE), scene_records.get(store, OTHER_SCENE)
    anchor = {'scene': SCENE, 'seq': world.other['scene_seq']}
    same = people.source_of(here, anchor)
    assert same.startswith('〔%d〕 ' % world.other['scene_seq']) and '：' not in same, 'the pointer without the line\'s words'
    away = people.source_of(elsewhere, anchor)
    assert away.startswith('出自别处的一行（') and '〔' not in away, 'another scene\'s label would mislead'
    assert people.source_of(here, {'scene': SCENE, 'seq': 999}) == People.SOURCE_GONE
    assert people.source_of(here, None) is None and people.source_of(here, {'scene': SCENE}) is None


def test_sources_lists_only_the_items_that_rest_on_a_line(world):
    store = world.store
    docs = DocumentStore(store, 'demo')
    for number, heading in enumerate(('有出处', '没出处')):
        docs.apply('notes', {'op': 'append_section', 'heading': heading, 'reason': '记', 'kind': 'ledger' if number == 0 else None}, '正文',
                   base_revision_id=docs.read('notes')[0], author='character', mutation_id='m-%d' % number)
    _, content = docs.read('notes')
    first, second = (section['sid'] for section in content['sections'])
    tiers = memory_tiers.Tiers(store, 'demo')
    anchor = {'scene': SCENE, 'seq': world.other['scene_seq']}
    tiers.written('notes', {'op': 'set_tags', 'sid': first, 'from': '别人说的', 'anchor': anchor}, content, content, scene_id=SCENE)
    tiers.written('notes', {'op': 'set_tags', 'sid': second, 'from': '我自己的判断'}, content, content, scene_id=SCENE)
    found = memory_tiers.sources(store, 'demo', 'notes', scene_records.get(store, SCENE))
    assert list(found) == [first] and found[first].startswith('〔')
    assert memory_tiers.sources(store, 'demo', 'no-such-document', None) == {}
