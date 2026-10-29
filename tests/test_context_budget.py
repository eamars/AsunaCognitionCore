"""What a turn may carry on its own, and how her notes stay short (context_budget.py, ADR-014)."""
import json

from asuna import context_budget as budget
from asuna.affect import affect_model, interpret
from conftest import FIXTURES

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


# ---- the whole turn ---------------------------------------------------------------
def test_an_oversized_turn_loses_the_oldest_list_rows_first_and_says_so():
    context = {'event': {'text': 'hi'},
               'memories': [{'_id': 'm%d' % n, 'body_markdown': '记' * 3000} for n in range(10)],
               'delivered_history': [{'_id': 'h%d' % n, 'text': '话' * 2000} for n in range(12)]}
    left = budget.trim_turn(context, limit=5000)
    assert left['memories'] == 10 and left['delivered_history'] == 8        # memories go first; four lines always stay
    assert [row['_id'] for row in context['delivered_history']] == ['h8', 'h9', 'h10', 'h11']   # newest kept
    assert left['shortened_texts'] >= 1, 'four lines still over: their texts are shortened, the ceiling is hard'
    assert budget.size({k: v for k, v in context.items() if k != 'trimmed_from_program'}) <= 5000
    assert 'recall' in context['trimmed_from_program']['note']
    small = {'event': {'text': 'hi'}, 'memories': []}
    assert budget.trim_turn(small) == {} and 'trimmed_from_program' not in small


def test_one_huge_message_is_cut_to_the_ceiling_saying_how_much_went():
    # Nothing in the trim lists can help: the one message is over the whole turn's ceiling by itself.
    context = {'event': {'text': '长' * 90000}, 'memories': [], 'persona': {'core': '我' * 2000}}
    left = budget.trim_turn(context)
    text = context['event']['text']
    assert left == {'shortened_texts': left['shortened_texts']} and left['shortened_texts'] >= 1
    assert budget.size({k: v for k, v in context.items() if k != 'trimmed_from_program'}) <= budget.TURN_CHARS
    assert text.startswith('长' * budget.SHORT_TEXT) and '没列出' in text and 'recall' in text
    assert context['persona']['core'] == '我' * 2000, 'the longest text goes first; a short block stays whole'


def test_many_texts_that_cannot_get_shorter_end_the_cutting():
    # Hundreds of ~450-character texts: halving one gives back 400 characters plus its note, no shorter. The cutting
    # looped forever on such a turn and stopped her queue for hours (10-13); now it stops and the turn goes over.
    context = {'rows': ['字' * 450 for _ in range(400)]}
    budget.trim_turn(context, limit=5000)
    assert all(len(text) <= 450 for text in context['rows'])


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


def test_the_identity_limit_gives_a_package_s_seeds_room_on_top_up_to_the_window_share(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from asuna import render
    monkeypatch.setattr(render, 'model_and_policy', lambda store, persona: ({}, {}))

    def limit(persona_chars, window=68608):
        (tmp_path / 'persona.md').write_text('## 我\n' + '她' * persona_chars, encoding='utf-8')
        (tmp_path / 'voice.md').write_text('## 说话\n短。', encoding='utf-8')
        seeds = [{'slug': 'persona', 'kind': 'persona', 'path': str(tmp_path / 'persona.md')},
                 {'slug': 'voice', 'kind': 'voice', 'path': str(tmp_path / 'voice.md')}]
        store = SimpleNamespace(config={'character': {'context_window': window}, 'persona_contribution': {'seeds': seeds}})
        return render.budget_limit(store, 'p'), render.seed_estimate(store, 'p')

    assert limit(800)[0] == 12288                                 # little seed text: the core ceiling
    big, seeded = limit(9000, window=200000)
    assert seeded > 9000 and big == 12288 + -(-seeded * 5 // 4) - 6144, 'seeds and a quarter, above the persona share'
    assert limit(9000, window=16000)[0] == 4000                   # never past the window share
    assert render.estimate_tokens('一之瀬アスナ') == 6 and render.estimate_tokens('hello world!') == 3


