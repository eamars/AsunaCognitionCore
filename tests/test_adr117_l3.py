"""ADR-117 L3: her identity has one token ceiling per (place, class) pair. A write of hers that takes a pair over lands;
her next home turn that can write lists the pair's sections for her to choose; after that turn the program lets go,
felt ones last, the oldest memorable moment first, ties by the lowest program score, until the pair fits; a section
carried in two pairs frees both; when only a felt section would make it fit, nothing moves and she is asked again. A
persona job's import over the ceiling is still refused. On the fixture world (in memory); dm-a is the owner's DM."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from asuna import carried, clock, memory_tiers, visibility
from asuna.documents import DocumentError
from asuna.persona_data import PersonaDataAPI
from asuna.records import scenes as scene_records
from asuna.role_tools import RoleTools
from asuna.schedule_rules import her_zone
from asuna.store.words import Set

PERSONA = 'P1'
HOME = ('home', visibility.OWNER_PRIVATE)
PEER = ('peer', visibility.OWNER_PRIVATE)


@pytest.fixture
def home(world, monkeypatch):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'person_id': 'A', 'persona': PERSONA}
    ceiling = [None]
    monkeypatch.setattr(carried, 'limit', lambda store, persona: ceiling[0])
    coordinator = SimpleNamespace(store=world, scheduler=None, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator), serial=[0], ceiling=ceiling,
                           tiers=memory_tiers.Tiers(world, PERSONA))


def turn(home, state='TURN'):
    home.serial[0] += 1
    ep_id = 'ep-l3-%d' % home.serial[0]
    home.store.put('episodes', {
        '_id': ep_id, 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': 'A', 'episode_kind': 'external', 'state': state, 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': visibility.OWNER_PRIVATE},
        'turn_tools': ['think', 'write_document'], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    return ep_id


def write(home, heading, chars, *, places=('home',), visibility_='public'):
    """Her append to `self`, through write_document in a turn of its own."""
    ep_id = turn(home)
    return home.tools.call(ep_id, ep_id + ':0', 'write_document', {
        'doc': 'self', 'do': 'append_section', 'heading': heading, 'content': '字' * chars, 'why': 'mine',
        'visibility': visibility_, 'tags': ['place:' + place for place in places]})[0]


def aged(home, sid, days, at=None, **fields):
    at = at or (clock.now() - timedelta(days=days)).isoformat()
    home.store.collection('memory_tiers').update({'_id': memory_tiers.item_id(PERSONA, 'self', sid)},
                                                 Set({'memorable_at': at, 'last_use_at': at, **fields}))


def scored(home, pair, scores):
    carried.count_day(home.store, [{'_id': 'count:%s:%s' % (sid, pair[0]), 'persona': PERSONA,
                                    'section': 'doc:self#' + sid, 'pair': carried.PAIR_WORDS[pair],
                                    'day': clock.now().date().isoformat(), 'turns_carried': 1, 'pair_turns': 1,
                                    'recall_hits': 0, 'program_score': n, 'reconstructed': False}
                                   for sid, n in scores.items()])


def size(home, pair):
    return carried.identity(home.store, PERSONA)[pair]


def shown_at_home(home, ep_id):
    scene = scene_records.get(home.store, 'dm-a')
    return home.tiers.things(visibility.OWNER_PRIVATE, scene, her_zone(home.store.config), home=True,
                             readable_docs=set(), choose=ep_id).get('identity_over')


def ended(home, ep_id):
    row = home.store.collection('episodes').get(ep_id)
    home.store.put('episodes', {**row, 'state': 'COMMITTED'}, expected=row['revision'], stream=ep_id)


def test_a_write_over_the_ceiling_lands_she_chooses_at_home_then_the_stalest_lowest_scored_lapses(home):
    for heading in ('tie-one', 'tie-two', 'felt-old', 'recent'):
        write(home, heading, 60)
    tied = (clock.now() - timedelta(days=20)).isoformat()      # one moment stamped both (a sync does)
    aged(home, 'tie-one', 20, tied)
    aged(home, 'tie-two', 20, tied)
    aged(home, 'felt-old', 30, felt=True)          # the oldest, but felt: last
    aged(home, 'recent', 2)
    scored(home, HOME, {'tie-one': 4, 'tie-two': 0})
    home.ceiling[0] = size(home, HOME) + 20

    written = write(home, 'new', 60)               # over the ceiling: refused before L3
    over = size(home, HOME) - home.ceiling[0]
    assert written['note'] == '已写下。' and over > 0, 'the write lands'
    assert '超 %s' % carried.number(over) in written['room'], 'and says how far over'

    showing = turn(home)
    [choice] = shown_at_home(home, showing)
    assert choice['where'] == '家里' and carried.number(over) in choice['line']
    listed = [entry.split('」')[0][1:] for entry in choice['sections']]
    assert {'tie-one', 'tie-two', 'felt-old', 'recent', 'new'} <= set(listed), 'every section the pair carries'
    assert choice['sections'][0].startswith('「felt-old」30 天'), 'the longest unused first'
    assert memory_tiers.lapse_due(home.store, PERSONA) == [], 'nothing moves while the turn that showed it runs'

    ended(home, showing)
    moves = memory_tiers.lapse_due(home.store, PERSONA)
    assert [move['sid'] for move in moves] == ['tie-two'], 'the stalest, the lower score of the two'
    assert moves[0]['reason'] == 'ceiling' and moves[0]['lapse_line'].startswith('家里：tie-two 从这一处的随身放下了')
    assert size(home, HOME) <= home.ceiling[0], 'the pair fits'
    assert home.tiers.item('self', 'felt-old')['place'] == memory_tiers.CARRIED
    assert shown_at_home(home, turn(home)) is None, 'nothing left to choose'


def test_a_section_carried_in_two_pairs_frees_both(home):
    write(home, 'home-only', 60)
    write(home, 'peer-only', 60, places=('peer',))
    write(home, 'shared', 60, places=('home', 'peer'))
    tied = (clock.now() - timedelta(days=20)).isoformat()
    for sid in ('home-only', 'peer-only', 'shared'):
        aged(home, sid, 20, tied)
    # Each pair's own scores put a different section first: the shared one at home, the peer line's own one there.
    scored(home, HOME, {'shared': 0, 'home-only': 5})
    scored(home, PEER, {'shared': 5, 'peer-only': 0})
    home.ceiling[0] = max(size(home, HOME), size(home, PEER)) + 20
    write(home, 'grown', 60, places=('home', 'peer'))
    assert {tuple(row['pair']) for row in home.store.collection('memory_tiers').find({'row': 'pair_over'})} == {HOME, PEER}

    showing = turn(home)
    assert [choice['where'] for choice in shown_at_home(home, showing)] == ['家里', '线']
    ended(home, showing)
    moves = memory_tiers.lapse_due(home.store, PERSONA)
    assert [move['sid'] for move in moves] == ['shared'], 'the shared section frees the peer line too: nothing else goes'
    assert size(home, HOME) <= home.ceiling[0] and size(home, PEER) <= home.ceiling[0]
    assert home.tiers.item('self', 'peer-only')['place'] == memory_tiers.CARRIED
    assert list(home.store.collection('memory_tiers').find({'row': 'pair_over'})) == []


def test_when_only_a_felt_section_would_make_it_fit_nothing_moves_and_she_is_asked_again(home):
    write(home, 'felt-big', 120)
    write(home, 'small', 10)
    aged(home, 'felt-big', 30, felt=True)
    aged(home, 'small', 20)
    home.ceiling[0] = size(home, HOME) + 10
    write(home, 'grown', 60)                       # over by more than 'small' frees
    aged(home, 'grown', 0, felt=True)              # written in a turn where she recorded a feeling
    assert size(home, HOME) - home.ceiling[0] > carried.weight('self', {'heading': 'small', 'body': '字' * 10,
                                                                         'sid': 'small'})
    showing = turn(home)
    assert shown_at_home(home, showing)
    ended(home, showing)
    assert memory_tiers.lapse_due(home.store, PERSONA) == []
    assert home.tiers.item('self', 'small')['place'] == memory_tiers.CARRIED, 'not even the small one'
    [again] = shown_at_home(home, turn(home))
    assert again['waiting'] == memory_tiers.FELT_WAIT


def test_an_import_over_the_ceiling_is_refused_and_a_home_turn_is_where_she_chooses(home):
    home.ceiling[0] = size(home, HOME) + 20
    api = PersonaDataAPI(home.store, PERSONA, run_id='run-1', job_id='job-1', grants={'persona_data.write'},
                         sources={'origin-1': 'cohabiting'})
    with pytest.raises(DocumentError) as refused:
        api.dispatch('documents.upsert', {'slug': 'voice', 'kind': 'voice', 'origin': 'origin-1',
                                          'source_identity': 'src-1', 'title': 'voice',
                                          'sections': [{'heading': 'long', 'body': '字' * 200, 'visibility': 'public'}]})
    assert refused.value.code == 'PERSONA_RENDER_OVER_BUDGET'
    assert list(home.store.collection('memory_tiers').find({'row': 'pair_over'})) == [], 'never her choice'
    from asuna.role_tools import writes_at_home
    ep = home.store.collection('episodes').get(turn(home))
    assert writes_at_home(home.store, ep)
    assert not writes_at_home(home.store, {**ep, 'episode_kind': 'consult'})
    assert not writes_at_home(home.store, {**ep, 'manifest': {'session_class': visibility.PUBLIC}})
