"""What a turn may carry on its own, and how her notes stay short (context_budget.py, ADR-014)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from asuna import context_budget as budget
from asuna.affect import AffectLedger, affect_model, interpret
from asuna.coordinator import Coordinator
from asuna.documents import DocumentError, DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import budget_gate
from conftest import FIXTURES
from test_engineering_m1 import THINK, event

MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))


def section(sid, body, heading=None, **extra):
    return {'sid': sid, 'heading': heading or sid, 'body': body, 'inject': 'always', **extra}


# ---- her notes ------------------------------------------------------------------
def test_a_note_within_its_limit_shows_whole_and_says_how_full_it_is():
    kept, about = budget.note_view([section('a', '一' * 100), section('b', '二' * 100)], 1000)
    assert [s['sid'] for s in kept] == ['a', 'b'] and about == {'fullness': '宽裕'}
    assert budget.fullness(700, 1000) == '用了一大半' and budget.fullness(1001, 1000) == '超了'


def test_over_its_limit_a_note_shows_its_newest_sections_whole_and_names_the_rest():
    sections = [section('old%d' % n, '旧' * 400) for n in range(5)] + [section('new', '新' * 400)]
    kept, about = budget.note_view(sections, 1000)
    assert [s['sid'] for s in kept] == ['old4', 'new']                     # newest that fit, in their own order
    assert all(len(s['body']) == 400 for s in kept)                         # never cut inside a section
    assert [s['sid'] for s in about['not_shown']] == ['old0', 'old1', 'old2', 'old3']
    assert about['fullness'] == '超了' and '4 节' in about['over_limit']
    huge, about = budget.note_view([section('one', '长' * 5000)], 1000)
    assert len(huge) == 1 and '截断' in huge[0]['body'] and about['not_shown'] == []


def test_tucked_and_corrected_sections_do_not_count_or_show():
    sections = [section('a', '错的'), section('fix', '对的', corrects='a'), section('tucked', '细节' * 500, inject='on_demand')]
    kept, about = budget.note_view(sections, 1000)
    assert [s['sid'] for s in kept] == ['fix'] and '1 节收起了' in about['tucked_away']
    assert budget.note_chars(sections) == len('fix') + len('对的')


def test_a_note_far_over_its_limit_takes_no_new_text_but_can_always_shrink(store):
    docs = DocumentStore(store, 'P1')
    gate = budget_gate(store, 'P1')
    slug = 'group:demo-notes'
    limit = budget.NOTE_CHARS['group_notes']
    base = docs.apply(slug, {'op': 'append_section', 'heading': '一', 'reason': '记', 'visibility': 'public', 'inject': 'always'},
                      '甲' * (limit * budget.NOTE_HARD_FACTOR - 10), base_revision_id=None, author='character',
                      mutation_id='m1', budget=gate)['_id']
    with pytest.raises(DocumentError, match='NOTE_OVER_LIMIT'):
        docs.apply(slug, {'op': 'append_section', 'heading': '二', 'reason': '再记', 'inject': 'always'}, '乙' * 50,
                   base_revision_id=base, author='character', mutation_id='m2', budget=gate)
    sid = docs.read(slug)[1]['sections'][0]['sid']
    shorter = docs.apply(slug, {'op': 'replace_section', 'sid': sid, 'reason': '整理'}, '甲' * 100,
                         base_revision_id=base, author='character', mutation_id='m3', budget=gate)
    assert shorter['content']['sections'][0]['body'] == '甲' * 100


# ---- the whole turn ---------------------------------------------------------------
def test_an_oversized_turn_loses_the_oldest_list_rows_first_and_says_so():
    context = {'event': {'text': 'hi'},
               'memories': [{'_id': 'm%d' % n, 'body_markdown': '记' * 3000} for n in range(10)],
               'delivered_history': [{'_id': 'h%d' % n, 'text': '话' * 2000} for n in range(12)]}
    left = budget.trim_turn(context, limit=5000)
    assert left == {'memories': 10, 'delivered_history': 8}               # memories go first; four lines always stay
    assert [row['_id'] for row in context['delivered_history']] == ['h8', 'h9', 'h10', 'h11']   # newest kept
    assert 'recall' in context['trimmed_from_program']['note']
    small = {'event': {'text': 'hi'}, 'memories': []}
    assert budget.trim_turn(small) == {} and 'trimmed_from_program' not in small


# ---- her mood ---------------------------------------------------------------------
def test_mood_reasons_are_capped_stable_and_keep_every_unsettled_feeling():
    model = affect_model(MODEL)
    kind = next(iter(model['kinds']))
    rows = [{'event_id': '%064x' % n, 'kind': kind, 'val': 60 - n, 'arl': 10, 'age_h': 0.2 + n, 'held': n == 9,
             'why': 'why %d' % n} for n in range(10)]
    state = {'val': 30, 'arl': 20, 'contributions': rows, 'open_count': 1}
    view = interpret(model, state, 'owner_private')
    assert len(view['reasons']) == budget.AFFECT_REASONS and view['fainter'] == '还有 4 笔较淡的心情没列出'
    assert any(r.get('unsettled') for r in view['reasons'])                  # the held one is shown though faint
    assert all(len(r['event_id']) == 12 for r in view['reasons'])
    later = interpret(model, {**state, 'contributions': [{**r, 'age_h': r['age_h'] + 0.3} for r in rows]}, 'owner_private')
    assert later == view                                                     # minutes later it reads the same


def test_a_short_event_id_closes_the_feeling_it_names(store):
    from test_adr009_p3 import setup
    ledger = setup(store)
    record = ('feel', {'op': 'record', 'kind': 'joy', 'intensity': '明显', 'arousal': '有些波动', 'ref': 'happy-1',
                       'why': '他夸了我', 'cost': '有点不好意思'})
    Coordinator(store, FakeLane(store, [FakeTurn([THINK, record], '嗯。')])).ingest(event('happy-1'))
    stored = store.db.affect_events.find_one({'why': '他夸了我'})
    void = ('feel', {'op': 'void', 'event_id': stored['_id'][:12], 'why': '其实是客气话'})
    lane = FakeLane(store, [FakeTurn([THINK, void], '嗯。')])
    Coordinator(store, lane).ingest(event('happy-2'))
    assert lane.tool_results[1][5], lane.tool_results
    assert store.db.affect_amendments.find_one({'target': stored['_id'], 'op': 'void'})
    assert ledger.enabled


def test_an_expired_proposal_is_said_once_then_leaves_the_view(store):
    from asuna import visibility
    from test_adr009_p3 import setup
    ledger = setup(store)
    scope = visibility.owner_private_scope('P1')
    ledger.propose({'_id': 'ep-x', 'scope_key': scope, 'context': {'ref_index': []}}, 0,
                   {'kind': 'joy', 'val': 20, 'arl': 10, 'why': '一个建议'}, 'owner_private')
    later = (datetime.now(timezone.utc) + timedelta(hours=float(ledger.model.get('proposal_ttl_h') or 24) + 1)).isoformat()
    first = ledger.proposals(scope, 'owner_private', at=later)
    assert [row['status'] for row in first] == ['已过期']
    assert ledger.proposals(scope, 'owner_private', at=later) == []


# ---- her ideas -------------------------------------------------------------------
def test_open_ideas_come_before_deferred_ones_and_the_rest_are_counted(store):
    from asuna.role_tools import ideas_block, ideas_left, note_idea
    source = {'by': 'character'}
    deferred = [note_idea(store, 'P1', '旧想法 %d' % n, '因为', key=['d', n], source=source) for n in range(3)]
    for row in deferred:
        store.db.ideas.update_one({'_id': row['_id']}, {'$set': {'state': 'deferred'}})
    fresh = note_idea(store, 'P1', '新想法', '因为', key=['n'], source=source)
    items = ideas_block(store, 'P1', datetime.now(timezone.utc), limit=2)
    assert [item['_id'] for item in items] == [fresh['_id'], deferred[0]['_id']]
    assert ideas_left(store, 'P1', len(items)) == '还有 2 条没列出，处理掉几条就会轮到它们。'
    assert ideas_left(store, 'P1', 4) is None


# ---- nightly tidying ---------------------------------------------------------------
def test_settlement_lists_the_notes_due_for_tidying_most_pressing_first(store):
    docs = DocumentStore(store, 'P1')
    limit = budget.NOTE_CHARS['group_notes']

    def write(slug, body, mutation, base=None, op='append_section', sid=None):
        intent = {'op': op, 'reason': '记', 'heading': mutation, 'visibility': 'public', 'inject': 'always',
                  **({'sid': sid} if sid else {})}
        return docs.apply(slug, intent, body, base_revision_id=base, author='character', mutation_id=mutation)['_id']

    write('group:over', '满' * (limit + 10), 'o1')                            # over its limit
    write('group:near', '近' * int(limit * 0.9), 'n1')                         # near it
    changed = write('group:stale', '旧', 's1')
    write('group:stale', '新', 's2', base=changed)                            # changed after it began
    store.db.episodes.insert_one({'_id': 'ep-settle', 'schema_version': 1, 'episode_kind': 'settlement'})
    tidied = write('group:tidy', '整', 'ep-settle:write:c1')                  # tidied, unchanged since
    assert tidied
    week = datetime.now(timezone.utc) + timedelta(days=budget.REVIEW_EVERY_DAYS + 1)
    review = budget.review_block(store, 'P1', week)
    assert [item['doc'] for item in review['items']] == ['group:over', 'group:near', 'group:stale']
    assert review['items'][0]['fullness'] == '超了' and review['items'][0]['sections'][0]['body'].startswith('满')
    assert review['items'][2]['last_tidied'] == '还没整理过' and 'more' not in review
    assert budget.review_block(store, 'P1', datetime.now(timezone.utc))['items'][-1]['doc'] == 'group:near'


# ---- single-body notes and the persona render -----------------------------------
def test_her_self_description_and_understanding_have_a_length_limit(store):
    from test_adr009_p2 import owner
    owner(store)
    long = '我' * (budget.SINGLE_BODY_CHARS + 1)
    lane = FakeLane(store, [FakeTurn([THINK, ('update_self', {'target': 'current_self', 'body': long, 'reason': '写'})], '嗯。')])
    Coordinator(store, lane).ingest(event('self-1'))
    refused = lane.tool_results[1]
    assert not refused[5] and '%d 字以内' % budget.SINGLE_BODY_CHARS in refused[4]


def test_the_persona_render_has_a_fixed_budget_she_can_only_raise_so_far():
    from asuna.persona_model import CORE_DEFAULTS, key_spec
    assert CORE_DEFAULTS['render']['budget_tokens'] == 16384
    assert key_spec({}, 'render.budget_tokens')['max'] == 32768


def test_in_its_group_she_tucks_a_section_away_and_from_home_she_tidies_it_by_name(store):
    from asuna import group_admin
    from test_adr009_p2 import owner
    from test_group_admin import BOT, GROUP, SCENE, setup as group_setup
    scene = group_setup(store, 'member')
    docs = DocumentStore(store, 'P1')
    slug = group_admin.notes_slug(SCENE)
    docs.apply(slug, {'op': 'append_section', 'heading': '细节', 'reason': '记', 'visibility': 'public', 'inject': 'always'},
               '很长的细节', base_revision_id=None, author='character', mutation_id='g1')
    sid = docs.read(slug)[1]['sections'][0]['sid']
    tuck = {'doc': 'group_notes', 'op': 'set_tags', 'sid': sid, 'inject': 'on_demand', 'reason': '不常用'}
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', tuck)], '在')])
    group_event = {'event_id': 'tuck-1', 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': '@演示 在吗',
                   'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 't', 'mentioned_account_ids': [BOT]},
                   'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                               'sender_id': '20002', 'platform_event_id': 'tuck-1'}}
    Coordinator(store, lane).ingest(group_event, persona='P1')
    assert lane.tool_results[1][5], lane.tool_results
    tucked = docs.read(slug)[1]['sections'][0]
    assert tucked['inject'] == 'on_demand' and tucked['visibility'] == 'public'
    _, block = group_admin.notes_block(docs, scene)
    assert block['sections'] == [] and '1 节收起了' in block['tucked_away']
    owner(store)
    tidy = {'doc': slug, 'op': 'append_section', 'heading': '要点', 'body': '一句话的要点', 'reason': '整理'}
    home = FakeLane(store, [FakeTurn([THINK, ('write_document', tidy)], '嗯。')])
    Coordinator(store, home).ingest(event('tidy-1'), persona='P1')
    assert home.tool_results[1][5], home.tool_results
    added = docs.read(slug)[1]['sections'][-1]
    assert added['visibility'] == 'public' and added['inject'] == 'always'     # a group's notes stay public
