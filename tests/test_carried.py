"""ADR-096: what she carries is measured as it is carried. One function says what reaches a turn of each (place, class)
pair and every reader uses it; each pair has its own identity budget, gated on every path that changes what is
carried; a write says the room left; a group's notes fold by last surfacing, pins never; what was carried is counted."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from asuna import (attend, block_guide, carried, context_budget, dice, group_admin, memory_pilot, memory_tiers, render,
                   self_review, visibility)
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.documents import DocumentError, DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.memory_tiers import AT_HAND, CARRIED, Tiers
from asuna.persona_data import PersonaDataAPI
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event
from test_memory_pilot import Route
from test_memory_tiers_delivery import Retrieval

HOME = ('home', visibility.OWNER_PRIVATE)
GROUP = ('group', visibility.PUBLIC)


@pytest.fixture(autouse=True)
def tiers_on(monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)


def write(store, slug, intent, body=None, *, mutation):
    """One of her writes as write_document makes it: gated, then placed."""
    docs = DocumentStore(store, 'P1')
    base, before = docs.read(slug)
    intent = {'reason': 'test', **intent}
    docs.apply(slug, intent, body, base_revision_id=base, author='character', mutation_id=mutation,
               budget=render.budget_gate(store, 'P1'))
    return Tiers(store, 'P1').written(slug, intent, before, docs.read(slug)[1], before_revision=base)


def sid_of(store, slug, heading):
    return next(s['sid'] for s in DocumentStore(store, 'P1').read(slug)[1]['sections'] if s['heading'] == heading)


def ceiling_at(monkeypatch, value):
    monkeypatch.setattr(carried, 'limit', lambda store, persona: value)


# ---- one function, every reader -------------------------------------------------------
def test_a_section_let_go_is_carried_by_no_reader_and_counts_nowhere(store):
    owner(store)
    write(store, 'persona', {'op': 'append_section', 'heading': '放下的一节', 'visibility': 'public', 'inject': 'always'},
          'PERSONA_LET_GO ' * 40, mutation='p1')
    write(store, 'core', {'op': 'append_section', 'heading': '我是谁'}, 'CORE_LET_GO ' * 40, mutation='c1')
    persona_sid, core_sid = sid_of(store, 'persona', '放下的一节'), sid_of(store, 'core', '我是谁')
    probe = PersonaDataAPI(store, 'P1', run_id='r', job_id='j', grants=['probe'], sources={})

    def readers():
        blocks = probe.probe_context({'as': visibility.PUBLIC, 'place': 'group'})['blocks']
        return {'system': 'PERSONA_LET_GO' in render.render_system(store, 'P1', visibility.PUBLIC, 'group')[0],
                'gate': 'CORE_LET_GO' in attend.system(store, 'P1'),
                'action brain': 'CORE_LET_GO' in render.action_values(store, 'P1', visibility.PUBLIC, 'group'),
                'probe': persona_sid in [s['sid'] for s in blocks.get('persona', [])]
                         and core_sid in [s['sid'] for s in blocks.get('core', [])]}
    sizes = lambda: {(row['place'], row['class']): row['tokens'] for row in render.render_status(store, 'P1')['pairs']}
    before, weighed = readers(), sizes()
    assert all(before.values()), before
    tiers = Tiers(store, 'P1')
    tiers.sync()
    tiers.let_go('persona', persona_sid)
    tiers.let_go('core', core_sid)
    assert not any(readers().values()), readers()
    assert all(sizes()[pair] < weighed[pair] for pair in weighed), 'a section let go no longer counts in any pair'
    ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。')])).ingest(event('let-go-turn'))
    assert 'CORE_LET_GO' not in json.dumps(ep['context'], ensure_ascii=False), 'the self and core blocks'
    assert 'doc:persona#' + persona_sid not in ep['context'].get('doc_refs_from_program', [])
    assert not {'doc:persona#' + persona_sid, 'doc:core#' + core_sid} & set(ep['manifest']['carried']['refs'])


def test_self_and_core_honour_place_tags_as_persona_does(store):
    owner(store)
    write(store, 'self', {'op': 'append_section', 'heading': '群里的我', 'tags': ['place:group']}, 'ONLY_GROUP_SELF',
          mutation='s1')
    home = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。')])).ingest(event('self-home'))
    group = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。')])).ingest(event('self-group', scene='g1'))
    assert 'ONLY_GROUP_SELF' not in json.dumps(home['context'], ensure_ascii=False)
    assert 'ONLY_GROUP_SELF' in json.dumps(group['context'], ensure_ascii=False)


def test_a_re_render_after_a_restart_is_the_prompt_that_was_measured(store):
    owner(store)
    write(store, 'persona', {'op': 'append_section', 'heading': '要放下的', 'visibility': 'public', 'inject': 'always'},
          'RERENDER_LINE', mutation='r1')
    text, ref = render.render_system(store, 'P1', visibility.OWNER_PRIVATE, 'home')
    assert 'RERENDER_LINE' in text and sid_of(store, 'persona', '要放下的') in ref['carried']['persona']
    tiers = Tiers(store, 'P1')
    tiers.sync()
    tiers.let_go('persona', sid_of(store, 'persona', '要放下的'))
    render._CACHE.clear()                                   # a restart: the cache is gone, the tiers moved since
    assert render.system_for(store, ref, stream='ep-x') == text
    assert not store.db.audit_events.find_one({'type': 'system.render_drift'})


# ---- one budget per pair, on every path ---------------------------------------------
def test_each_pair_has_its_own_ceiling_and_a_group_only_write_over_the_group_s_is_refused(store, monkeypatch):
    owner(store)
    write(store, 'persona', {'op': 'append_section', 'heading': '家里的规矩', 'visibility': 'owner_private',
                             'inject': 'always', 'tags': ['place:home']}, '家' * 3000, mutation='h1')
    sizes = carried.identity(store, 'P1')
    home, group = sizes[HOME], sizes[GROUP]
    assert home > group + 1000
    ceiling_at(monkeypatch, home - 10)                        # home is over already; the group is not
    with pytest.raises(DocumentError) as refused:
        # The largest render (home's) does not change, so a ruler of the largest let this through.
        write(store, 'persona', {'op': 'append_section', 'heading': '群里才用', 'visibility': 'public',
                                 'inject': 'always', 'tags': ['place:group']}, '群' * (home - group), mutation='g1')
    said = refused.value.detail
    assert refused.value.code == 'PERSONA_RENDER_OVER_BUDGET' and said.startswith('外面的群 这次改动会让它超 ')
    assert 'let_go 一节，或者把它写短' in said and '现在带得最多的是：「' in said
    with pytest.raises(DocumentError) as refused:
        write(store, 'persona', {'op': 'append_section', 'heading': '家里再加', 'visibility': 'owner_private',
                                 'inject': 'always', 'tags': ['place:home']}, '再' * 50, mutation='h3')
    assert refused.value.detail.startswith('家里 现在超 %s token，这次改动会让它更长。' % carried.number(10)), \
        "the number is carried()'s for that pair"
    shorter = write(store, 'persona', {'op': 'replace_section', 'sid': sid_of(store, 'persona', '家里的规矩')}, '家' * 100,
                    mutation='h2')
    assert shorter == [] and carried.identity(store, 'P1')[HOME] < home, 'a write that shrinks an over pair goes through'


def test_a_rewrite_that_brings_a_section_back_is_measured_before_it_lands(store, monkeypatch):
    owner(store)
    write(store, 'persona', {'op': 'append_section', 'heading': '收起来的', 'visibility': 'public', 'inject': 'always'},
          '旧' * 2000, mutation='t1')
    sid = sid_of(store, 'persona', '收起来的')
    write(store, 'persona', {'op': 'set_tags', 'sid': sid, 'inject': 'on_demand'}, mutation='t2')     # her let_go
    assert Tiers(store, 'P1').item('persona', sid)['place'] == AT_HAND
    ceiling_at(monkeypatch, max(carried.identity(store, 'P1').values()) + 100)
    with pytest.raises(DocumentError, match='PERSONA_RENDER_OVER_BUDGET'):
        write(store, 'persona', {'op': 'replace_section', 'sid': sid}, '新' * 2000, mutation='t3')
    assert Tiers(store, 'P1').item('persona', sid)['place'] == AT_HAND, 'nothing landed'
    docs = DocumentStore(store, 'P1')
    before = docs.read('persona')[1]
    after = {**before, 'sections': [{**s, 'body': '新', 'body_sha256': 'x'} if s['sid'] == sid else s
                                    for s in before['sections']]}
    plan = Tiers(store, 'P1').placement_after('persona', {'op': 'replace_section', 'sid': sid}, before, after)
    assert plan[sid] == [(CARRIED, 'rewritten')], 'the same rule the write follows'


def test_a_promoted_fact_and_an_adopted_seed_pass_the_same_gate(store, monkeypatch):
    owner(store)
    ceiling_at(monkeypatch, max(carried.identity(store, 'P1').values()))
    with pytest.raises(DocumentError, match='PERSONA_RENDER_OVER_BUDGET'):
        memory_tiers.land(store, {'_id': 'ep-land', 'persona': 'P1', 'scene_id': 'dm-a'},
                          {'about': 'self', 'fact': '我喜欢把话说完整' * 30, 'why': '几次都这样'}, [])
    docs = DocumentStore(store, 'P1')
    with pytest.raises(DocumentError, match='PERSONA_RENDER_OVER_BUDGET'):
        docs.adopt_seed('persona', 'persona', '## 种子里新的一节\n' + '新' * 600, base_revision_id=docs.read('persona')[0],
                        author='character', mutation_id='adopt-1', budget=render.budget_gate(store, 'P1'))


# ---- what she reads -------------------------------------------------------------------
def test_her_write_says_its_weight_and_each_place_s_room_and_a_tier_that_differs_is_said(store):
    owner(store)
    add = ('write_document', {'doc': 'persona', 'do': 'append_section', 'heading': '新的一节', 'content': '一句新的话。',
                              'why': '试', 'visibility': 'public'})
    lane = FakeLane(store, [FakeTurn([THINK, add], '好。')])
    Coordinator(store, lane).ingest(event('room-1'))
    result = lane.tool_results[1][4]
    sizes, ceiling = carried.identity(store, 'P1'), carried.limit(store, 'P1')
    weight = carried.weight('persona', DocumentStore(store, 'P1').read('persona')[1]['sections'][-1])
    assert result['room'] == '这节约 %s token。带它的地方：%s' % (carried.number(weight), '｜'.join(
        '%s 剩 %s' % (carried.PAIR_WORDS[pair], carried.number(ceiling - sizes[pair]))
        for pair in carried.ordered(sizes))), 'exact numbers, in her order, only where it is carried'
    sid = result['sid']
    let = ('write_document', {'doc': 'persona', 'do': 'let_go', 'section': sid, 'why': '少带一点'})
    read = ('recall', {'sections': [{'doc': 'persona', 'section': sid}]})
    lane = FakeLane(store, [FakeTurn([THINK, let, read], '好。')])
    Coordinator(store, lane).ingest(event('room-2'))
    gone, recalled = lane.tool_results[1][4], lane.tool_results[2][4]
    first, last = gone['tier'].splitlines()
    assert first == '这一节的真带是 手边；你写的 when_shown 是 always' and gone['room'].endswith('带它的地方：无')
    assert last.startswith('上一次挪档：') and last.endswith(' · 你 · 你放手了')
    assert recalled['documents'][0]['tier'] == gone['tier'], 'every read of that section says both'
    assert DocumentStore(store, 'P1').read('persona')[1]['sections'][-1]['inject'] == 'always', 'never written for her'
    moved = store.db.memory_tiers.find_one({'row': 'move', 'sid': sid})
    assert moved['by'] == 'her' and moved['reason'] == 'let_go'


def test_things_says_how_full_each_place_is_in_words_only_when_it_changes(store, monkeypatch):
    owner(store)
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    tiers = Tiers(store, 'P1')
    first = tiers.things(visibility.OWNER_PRIVATE, scene, 'UTC', home=True)
    assert set(first['identity_room']) == {carried.PAIR_WORDS[pair] for pair in carried.pairs(store.config)}
    assert set(first['identity_room'].values()) <= {word for _, word in carried.ROOM_WORDS}
    assert 'identity_room' not in tiers.things(visibility.OWNER_PRIVATE, scene, 'UTC', home=True), 'said once'
    ceiling_at(monkeypatch, 10)
    again = tiers.things(visibility.OWNER_PRIVATE, scene, 'UTC', home=True)
    assert set(again['identity_room'].values()) == {'超了'}
    public = tiers.things(visibility.PUBLIC, store.db.scenes.find_one({'_id': 'g1'}), 'UTC')
    assert set(public['identity_room']) == {'外面的群', '私聊'}, 'a public turn hears only its own pairs'


# ---- a group's notes fold -----------------------------------------------------------
def note(sid, chars, **extra):
    return {'sid': sid, 'heading': sid, 'body': '字' * chars, 'inject': 'always', **extra}


def test_over_the_limit_what_surfaced_longest_ago_folds_first_and_a_pin_never_folds():
    sections = [note('anchor', 900, pin=True), note('a', 900), note('b', 900), note('c', 900)]
    kept, about = context_budget.note_view(sections, 2400, order=['anchor', 'a', 'c', 'b'])
    assert [s['sid'] for s in kept] == ['anchor', 'b'], 'a then c folded; the pin, longest unused, stays'
    assert [s['sid'] for s in about['not_shown']] == ['a', 'c'] and '2 节' in about['over_limit']
    assert 'pins_over' not in about
    pins = [note('p1', 1500, pin=True), note('p2', 1500, pin=True), note('x', 100)]
    kept, about = context_budget.note_view(pins, 2400, order=['p1', 'p2', 'x'])
    assert [s['sid'] for s in kept] == ['p1', 'p2'] and about['pins_over'].startswith('置顶的节加起来就有 3004 字')
    assert about['fullness'] == '超了', 'pins still count inside the limit'


def test_a_group_s_notes_fold_by_last_surfacing_and_a_folded_one_comes_up_when_a_turn_is_about_it(store):
    slug = group_admin.notes_slug('g1')
    write(store, slug, {'op': 'append_section', 'heading': '松饼', 'visibility': 'public', 'inject': 'always'},
          '群里的人周六一起烤松饼。' + '细' * 1200, mutation='n1')
    write(store, slug, {'op': 'append_section', 'heading': '登山', 'visibility': 'public', 'inject': 'always'},
          '这个群里大家都爱聊登山。' + '节' * 1200, mutation='n2')
    write(store, slug, {'op': 'append_section', 'heading': '这个群是什么', 'visibility': 'public', 'inject': 'always'},
          '一个聊天的群。' + '锚' * 300, mutation='n3')
    tiers = Tiers(store, 'P1')
    anchor = sid_of(store, slug, '这个群是什么')
    write(store, slug, {'op': 'set_tags', 'sid': anchor, 'pin': True}, mutation='n4')
    baking, hiking = sid_of(store, slug, '松饼'), sid_of(store, slug, '登山')
    for sid, days in ((baking, 20), (anchor, 30)):
        tiers.rows.update_one({'_id': tiers.item(slug, sid)['_id']}, {'$set': {
            'added': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}})
    tiers.used([(slug, hiking)], 'recalled', 'g1')             # her recall counts as surfacing
    assert tiers.folding(slug, DocumentStore(store, 'P1').read(slug)[1])[:2] == [baking, hiking], 'kept, not recomputed'
    tiers.refold(slug, DocumentStore(store, 'P1').read(slug)[1])            # as settlement does
    assert tiers.folding(slug, None)[:2] == [anchor, baking]
    assert group_admin.folded(store, 'P1', slug) == {baking}, 'the pin is older still, and never folds'
    _, block = group_admin.notes_block(DocumentStore(store, 'P1'), {'_id': 'g1'})
    assert [s['sid'] for s in block['sections']] == [hiking, anchor] and block['not_shown'][0]['sid'] == baking
    pilot = memory_pilot.Pilot(store, 'P1', Route())
    pilot.sync()
    builder = ContextBuilder(store, Retrieval())
    builder.pilot = pilot
    _, context, manifest = builder.prepare(event('fold-1', scene='g1', text='松饼'), 'P1')
    own = [m for m in context['memories'] if m.get('kind') == 'own_item']
    assert ('doc:%s#%s' % (slug, baking)) in [m['_id'] for m in own] and own[0]['place'] == memory_tiers.FOLDED
    assert manifest['carried']['notes'] == ['doc:%s#%s' % (slug, s) for s in (hiking, anchor)]
    assert 'doc:%s#%s' % (slug, baking) in manifest['carried']['brought_up']


def test_a_pin_is_said_with_what_it_does_not_do_and_only_in_a_group_s_notes(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'persona', 'do': 'set_tags', 'section': 'x',
                                                                  'pin': 'yes', 'why': '置顶'})], '好。')])
    Coordinator(store, lane).ingest(event('pin-home'))
    assert 'pin 只用于群笔记' in lane.tool_results[1][4] and not lane.tool_results[1][5]
    assert '随身' in context_budget.PIN_NOTE and '%d 条' in context_budget.PIN_NOTE


# ---- voice in the item index ----------------------------------------------------------
def test_a_stored_voice_section_is_found_by_recall_like_any_other(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    write(store, 'voice', {'op': 'append_section', 'heading': '烤松饼时', 'visibility': 'public', 'inject': 'always'},
          '说到周六烤松饼就会多说几句', mutation='v1')
    sid = sid_of(store, 'voice', '烤松饼时')
    write(store, 'voice', {'op': 'set_tags', 'sid': sid, 'inject': 'never'}, mutation='v2')
    assert any(item['store'] == 'voice' and item['sid'] == sid for item in memory_pilot.own_items(store, 'P1'))
    pilot = memory_pilot.Pilot(store, 'P1', Route())
    pilot.sync()
    found, _ = memory_tiers.deliver(store, 'P1', pilot, Retrieval(), '周六烤松饼', {'global-safe'}, 'dm-a', recall=True)
    assert 'doc:voice#' + sid in [m['_id'] for m in found] and docs.read('voice')[1]


# ---- what was carried, counted --------------------------------------------------------
def test_carried_counts_are_a_replay_of_what_the_turns_recorded(store):
    owner(store)
    coordinator = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。') for _ in range(3)]))
    eps = [coordinator.ingest(event('count-%d' % n, scene=scene)) for n, scene in enumerate(('dm-a', 'dm-a', 'g1'))]
    scored = eps[1]['manifest']['carried']['refs'][0]
    store.db.episodes.update_one({'_id': eps[1]['_id']}, {'$set': {'manifest.carried.would_surface': [scored]}})
    doc, sid = scored[len('doc:'):].split('#')
    store.audit(eps[1]['_id'], 'recall.read', {'sections_read': [{'doc': doc, 'sid': sid}], 'memories': [],
                                               'place': 'home'}, eps[1]['scope_key'])
    day = datetime.now(timezone.utc).date()
    tally, pair_turns = {}, {}
    for ep in eps:
        mark = store.db.episodes.find_one({'_id': ep['_id']})['manifest']['carried']
        pair = carried.PAIR_WORDS[(mark['place'], mark['class'])]
        pair_turns[pair] = pair_turns.get(pair, 0) + 1
        for ref in mark['refs'] + mark['notes']:
            tally[(ref, pair)] = tally.get((ref, pair), 0) + 1
    rows, spans = carried.day_counts(store, 'P1', day)
    assert {(row['section'], row['pair']): row['turns_carried'] for row in rows} == tally and tally
    assert all(row['pair_turns'] == pair_turns[row['pair']] for row in rows)
    assert set(rows[0]) == {'_id', 'persona', 'section', 'pair', 'day', 'turns_carried', 'pair_turns', 'recall_hits',
                            'program_score', 'reconstructed'}
    mine = next(row for row in rows if (row['section'], row['pair']) == (scored, '家里'))
    assert (mine['program_score'], mine['recall_hits']) == (1, 1) and not any(row['reconstructed'] for row in rows)
    assert set(spans) == {ref for ref, _ in tally}
    # A turn from before the manifest recorded it is reconstructed from the tiers' moves, and says so.
    store.db.episodes.update_one({'_id': eps[0]['_id']}, {'$unset': {'manifest.carried': ''}})
    rebuilt, _ = carried.day_counts(store, 'P1', day)
    assert ({(row['section'], row['pair']): row['turns_carried'] for row in rebuilt}
            == {(row['section'], row['pair']): row['turns_carried'] for row in rows})
    assert all(row['reconstructed'] for row in rebuilt if row['pair'] == '家里')
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    store.db.carried_counts.insert_one({'_id': 'count:old', 'persona': 'P1', 'day': (day - timedelta(days=40)).isoformat()})
    done = carried.count_days(store, 'P1', tomorrow)
    assert done['deleted'] == 1 and done['days'] >= 1
    assert store.db.carried_counts.count_documents({'day': day.isoformat()}) == len(rebuilt)
    assert store.db.carried_days.find_one({'day': day.isoformat()})['rows'] == len(rebuilt), 'the day is recorded'
    kept = store.db.carried_sections.find_one({'section': scored})
    assert kept['first_carried_at'] <= kept['last_carried_at']
    assert carried.count_days(store, 'P1', tomorrow)['days'] == 0, 'a day is counted once, rows or none'
    carried.count_days(store, 'P1', tomorrow + timedelta(days=60))
    assert not store.db.carried_counts.find_one({'day': day.isoformat()}), 'the day rows keep 30 days'
    assert store.db.carried_sections.find_one({'section': scored}), 'first and last stay past them'


def test_a_move_from_before_moves_said_who_reads_with_who_from_its_reason(store):
    from asuna.dbread import Reader
    store.db.memory_tiers.insert_many([{'_id': 'move:old-her', 'row': 'move', 'reason': 'let_go'},
                                       {'_id': 'move:old-program', 'row': 'move', 'reason': 'stay'},
                                       {'_id': 'move:new', 'row': 'move', 'reason': 'stay', 'by': 'program'}])
    reader = Reader(store.db, store.db.name)
    rows = {row['_id']: row['by'] for row in reader.find('memory_tiers', {'row': 'move'})['rows']}
    assert rows == {'move:old-her': 'her', 'move:old-program': 'program', 'move:new': 'program'}
    assert reader.count('memory_tiers', {'row': 'move', 'by': 'her'})['found'] == 1
    assert {row['_id'] for row in reader.find('memory_tiers', {'by': 'program'})['rows']} == {'move:old-program',
                                                                                              'move:new'}
    assert not store.db.memory_tiers.find_one({'_id': 'move:old-her'}).get('by'), 'old rows are not rewritten'


# ---- her install checks ------------------------------------------------------------------
def test_her_four_install_checks_pass_on_a_build_that_carries_what_it_measures(store, monkeypatch):
    owner(store)
    write(store, 'persona', {'op': 'append_section', 'heading': '要放下的', 'visibility': 'public', 'inject': 'always'},
          'CHECK_LINE', mutation='k1')
    tiers = Tiers(store, 'P1')
    tiers.sync()
    tiers.let_go('persona', sid_of(store, 'persona', '要放下的'))            # one tier/inject difference to say
    render._CACHE.clear()                                                  # a restart
    Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。')])).ingest(event('check-1'))
    ceiling_at(monkeypatch, carried.identity(store, 'P1')[HOME] - 5)      # home over: its refusal says by how much
    checks = carried.install_checks(store, 'P1')
    assert {name for name, *_ in checks} == {'system_ref_is_carried', 'refusal_is_carried_number', 'room_line',
                                             'tier_line'}
    assert all(passed for _, passed, _ in checks), checks
    assert next(seen for name, _, seen in checks if name == 'tier_line') == {'differ': 1, 'said': 1}
    home = next(seen for name, _, seen in checks if name == 'refusal_is_carried_number' and seen['pair'] == '家里')
    assert home['said'] == 5 == home['expected']


def test_the_closed_pilot_s_old_turn_rows_go_and_its_index_stays(store):
    rows = store.db[memory_pilot.COLLECTION]
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    rows.insert_many([{'_id': 'turn:old', 'row': 'turn', 'at': old}, {'_id': 'recall:old', 'row': 'recall', 'at': old},
                      {'_id': 'turn:new', 'row': 'turn', 'at': datetime.now(timezone.utc).isoformat()},
                      {'_id': 'shadow:x', 'row': 'item', 'synced_at': old}, {'_id': 'pair:x', 'row': 'pair', 'at': old}])
    assert memory_pilot.prune(store) == 2 and not memory_pilot.SHADOW_PILOT
    assert {row['_id'] for row in rows.find()} == {'turn:new', 'shadow:x', 'pair:x'}


# ---- persona wording ------------------------------------------------------------------
def test_the_three_wordings_come_from_the_persona_package_and_the_core_s_are_neutral(store):
    from asuna.persona_model import TIERS_TOLD, validate, writable_keys
    model = validate({'model_version': 1, 'persona': {'id': 'p1', 'display_name': '某人'},
                      'memory': {'tiers_told': 'PKG_TOLD'}, 'heartbeat': {'idle_hint': 'PKG_IDLE'},
                      'self_review': {'exchanges_note': 'PKG_NOTE'}}, 'p1')
    assert not {'memory.tiers_told', 'heartbeat.idle_hint', 'self_review.exchanges_note'} & set(writable_keys(model))
    assert TIERS_TOLD in block_guide.guide(store.config) and '置顶' in TIERS_TOLD, 'true now that pins exist'
    assert '待着' in dice.line('idle', 'awake', dice.parse('待着 1'))
    store.config['persona_model'] = model
    assert 'PKG_TOLD' in block_guide.guide(store.config) and TIERS_TOLD not in block_guide.guide(store.config)
    assert dice.line('idle', 'awake', dice.parse('待着 1'), (), model).count('PKG_IDLE') == 1
    assert self_review.exchanges_note(store, 'P1') == 'PKG_NOTE'
