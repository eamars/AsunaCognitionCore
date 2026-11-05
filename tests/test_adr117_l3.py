"""ADR-117 L3: her identity has one token ceiling per (place, class) pair. A write of hers that leaves a pair over lands;
her next home turn that can write lists the pair's sections in the order the program would let them go; after that
turn the program lets go, felt ones never, the most days since last thought of first, ties by the lowest program
score, until the pair fits; a section carried in two pairs frees both. Nothing goes when only a felt section would
make it fit, or when only document order would decide (her choice); a pair that cannot fit is said once. A persona
job's import over the ceiling is still refused. On the fixture world (in memory); dm-a is the owner's DM."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from asuna import carried, clock, memory_tiers, visibility
from asuna.context import ContextBuilder
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


def ago(days):
    return (clock.now() - timedelta(days=days)).isoformat()


def aged(home, sid, days, at=None, *, used=None, **fields):
    at = at or ago(days)
    home.store.collection('memory_tiers').update({'_id': memory_tiers.item_id(PERSONA, 'self', sid)},
                                                 Set({'memorable_at': at, 'last_use_at': used or at, **fields}))


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


def listed(choice):
    return [entry.split('」')[0][1:] for entry in choice['sections']]


def over_rows(home):
    return list(home.store.collection('memory_tiers').find({'row': 'pair_over'}))


def test_the_list_is_the_order_the_program_lets_go_and_the_measure_is_the_last_time_it_was_thought_of(home):
    # Written in this order: document order alone would take 'used-now' first.
    for heading in ('used-now', 'stalest', 'middle', 'felt-old'):
        write(home, heading, 60)
    aged(home, 'used-now', 25, used=clock.now().isoformat())     # memorable long ago, but used just now
    aged(home, 'stalest', 20)
    aged(home, 'middle', 10)
    aged(home, 'felt-old', 30, felt=True)
    scored(home, HOME, {'stalest': 5, 'middle': 0})               # the score alone would take 'middle' first
    home.ceiling[0] = size(home, HOME) + 20
    written = write(home, 'new', 60)                              # over the ceiling: refused before L3
    over = size(home, HOME) - home.ceiling[0]
    assert written['note'] == '已写下。' and over > 0 and '超 %s' % carried.number(over) in written['room']

    showing = turn(home)
    [choice] = shown_at_home(home, showing)
    assert choice['where'] == '家里' and carried.number(over) in choice['line'] and 'waiting' not in choice
    order = listed(choice)
    assert order.index('stalest') < order.index('middle') < order.index('used-now') < order.index('felt-old')
    assert order[-1] == 'felt-old' and choice['sections'][-1].endswith(memory_tiers.FELT_MARK)
    assert choice['sections'][order.index('used-now')].startswith('「used-now」0 天'), 'the same measure she reads'
    assert home.tiers.lapse_over() == [] and over_rows(home)[0]['shown_in'] == [showing], \
        'nothing moves while the turn that showed it runs'

    ended(home, showing)
    moves = home.tiers.lapse_over()
    assert [move['sid'] for move in moves] == ['stalest'], 'the most days since last thought of, whatever its score'
    assert moves[0]['reason'] == 'ceiling' and moves[0]['lapse_line'].startswith('家里：stalest 从这一处的随身放下了')
    assert '它 20 天没用到' in moves[0]['lapse_line']
    assert size(home, HOME) <= home.ceiling[0] and over_rows(home) == []


def test_a_section_carried_in_two_pairs_frees_both(home):
    write(home, 'home-only', 60)
    write(home, 'peer-only', 60, places=('peer',))
    write(home, 'shared', 60, places=('home', 'peer'))
    tied = ago(20)
    for sid in ('home-only', 'peer-only', 'shared'):
        aged(home, sid, 20, tied)
    # Each pair's own scores put a different section first: the shared one at home, the peer line's own one there.
    scored(home, HOME, {'shared': 0, 'home-only': 5})
    scored(home, PEER, {'shared': 5, 'peer-only': 0})
    home.ceiling[0] = max(size(home, HOME), size(home, PEER)) + 20
    write(home, 'grown', 60, places=('home', 'peer'))
    assert {tuple(row['pair']) for row in over_rows(home)} == {HOME, PEER}

    showing = turn(home)
    assert [choice['where'] for choice in shown_at_home(home, showing)] == ['家里', '线']
    ended(home, showing)
    moves = home.tiers.lapse_over()
    assert [move['sid'] for move in moves] == ['shared'], 'the shared section frees the peer line too: nothing else goes'
    assert size(home, HOME) <= home.ceiling[0] and size(home, PEER) <= home.ceiling[0]
    assert home.tiers.item('self', 'peer-only')['place'] == memory_tiers.CARRIED and over_rows(home) == []


def test_only_a_felt_section_would_make_it_fit_nothing_moves_until_the_plan_she_is_shown_says_so(home):
    write(home, 'felt-big', 120)
    write(home, 'small', 10)
    aged(home, 'felt-big', 30, felt=True)
    aged(home, 'small', 20)
    home.ceiling[0] = size(home, HOME) + 10
    write(home, 'grown', 60)
    aged(home, 'grown', 0, felt=True)              # written in a turn where she recorded a feeling
    showing = turn(home)
    [choice] = shown_at_home(home, showing)
    assert choice['waiting'] == memory_tiers.FELT_WAIT
    # In that turn she writes her felt section shorter: 'small' alone is enough now.
    home.tools.call(showing, showing + ':0', 'write_document', {'doc': 'self', 'do': 'replace_section',
                                                                'section': 'grown', 'content': '字' * 15, 'why': 'shorter'})
    ended(home, showing)
    assert home.tiers.lapse_over() == [], 'she was told nothing goes: nothing goes before she is shown the new plan'
    assert home.tiers.item('self', 'small')['place'] == memory_tiers.CARRIED
    showing = turn(home)
    [again] = shown_at_home(home, showing)
    assert 'waiting' not in again
    ended(home, showing)
    assert [move['sid'] for move in home.tiers.lapse_over()] and over_rows(home) == []
    assert home.tiers.item('self', 'felt-big')['place'] == memory_tiers.CARRIED


def test_when_only_document_order_would_decide_nothing_goes_and_when_one_differs_it_goes(home):
    tied = ago(20)
    for heading in ('first', 'second', 'third'):
        write(home, heading, 60)
        aged(home, heading, 20, tied)
    home.ceiling[0] = size(home, HOME) + 20
    write(home, 'new', 60)
    showing = turn(home)
    [choice] = shown_at_home(home, showing)
    assert choice['waiting'] == memory_tiers.TIE_WAIT
    ended(home, showing)
    assert home.tiers.lapse_over() == [], 'first and second tie on days and score: document order would decide'
    showing = turn(home)
    assert shown_at_home(home, showing)[0]['waiting'] == memory_tiers.TIE_WAIT, 'asked again'

    aged(home, 'third', 25)                        # now one of them differs
    ended(home, showing)
    assert home.tiers.lapse_over() == [], 'she was shown a wait'
    showing = turn(home)
    [choice] = shown_at_home(home, showing)
    assert 'waiting' not in choice and listed(choice)[0] == 'third'
    ended(home, showing)
    assert [move['sid'] for move in home.tiers.lapse_over()] == ['third']


def test_a_place_over_even_with_every_section_gone_is_said_once(home):
    write(home, 'one', 60)
    home.ceiling[0] = carried.tokens(memory_tiers.Tiers(home.store, PERSONA)._identity()[2], {}, {}) - 10
    write(home, 'two', 60)
    choices = shown_at_home(home, turn(home))       # below the program's own opening text: every place is over
    choice = next(choice for choice in choices if choice['where'] == '家里')
    assert choice['line'] == memory_tiers.CANNOT_FIT % (carried.number(size(home, HOME)), carried.number(home.ceiling[0]))
    assert all('sections' not in choice for choice in choices)
    assert over_rows(home) == [] and shown_at_home(home, turn(home)) is None, 'said once'
    assert home.tiers.item('self', 'one')['place'] == memory_tiers.CARRIED


def test_an_import_over_the_ceiling_is_refused_and_a_seed_adopted_as_a_new_document_waits_for_her(home, tmp_path):
    home.ceiling[0] = size(home, HOME) + 20
    api = PersonaDataAPI(home.store, PERSONA, run_id='run-1', job_id='job-1', grants={'persona_data.write'},
                         sources={'origin-1': 'cohabiting'})
    with pytest.raises(DocumentError) as refused:
        api.dispatch('documents.upsert', {'slug': 'voice', 'kind': 'voice', 'origin': 'origin-1',
                                          'source_identity': 'src-1', 'title': 'voice',
                                          'sections': [{'heading': 'long', 'body': '字' * 200, 'visibility': 'public'}]})
    assert refused.value.code == 'PERSONA_RENDER_OVER_BUDGET' and over_rows(home) == [], 'never her choice'

    seed = tmp_path / 'self.md'
    seed.write_text('## steady\n' + '字' * 200 + '\n', encoding='utf-8')
    home.store.config['persona_contribution'] = {'seeds': [{'slug': 'self', 'kind': 'self', 'path': str(seed)}]}
    ep_id = turn(home)
    adopted = home.tools.call(ep_id, ep_id + ':0', 'write_document', {'doc': 'self', 'do': 'adopt_seed', 'why': 'mine'})
    assert adopted[0]['state'] == 'seeded' and HOME in {tuple(row['pair']) for row in over_rows(home)}, \
        'a new document from her seed leaves the place over: read from the state, it waits for her'

    from asuna.role_tools import writes_at_home
    ep = home.store.collection('episodes').get(turn(home))
    assert writes_at_home(home.store, ep)
    assert not writes_at_home(home.store, {**ep, 'episode_kind': 'consult'})
    assert not writes_at_home(home.store, {**ep, 'manifest': {'session_class': visibility.PUBLIC}})


def test_her_home_turn_built_by_prepare_shows_the_choice(home):
    write(home, 'one', 60)
    home.ceiling[0] = size(home, HOME) + 10
    write(home, 'two', 60)
    _, context, _ = ContextBuilder(home.store, None).prepare(
        {'event_id': 'ev-l3-home', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'}, PERSONA)
    [choice] = context['things_from_program']['identity_over']
    assert choice['where'] == '家里'
