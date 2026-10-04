"""ADR-009 P2 offline cases: T2.2 render selection/order, T2.3 render never truncates, T2.9 sid rules."""
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def doc(*sections, kind='persona'):
    from asuna.documents import _section
    return {'kind': kind, 'sections': [_section(sid, sid.upper(), 'BODY_' + sid, visibility=vis, inject=inj, tags=tags)
                                       for sid, vis, inj, tags in sections]}


@case
def t2_2_render_selects_by_class_and_inject():
    from asuna.render import compose
    persona = doc(('a', 'owner_private', 'always', []), ('b', 'public', 'always', []), ('c', 'public', 'on_demand', []),
                  ('d', 'public', 'never', []), ('e', 'owner_private', 'on_demand', []))
    public = compose('COMMON', persona, None, 'public')
    private = compose('COMMON', persona, None, 'owner_private')
    assert 'BODY_b' in public and 'BODY_a' not in public, public
    assert private.index('BODY_b') < private.index('BODY_a'), 'public sections come first'
    for text in (public, private):
        assert 'BODY_c' not in text and 'BODY_d' not in text and 'BODY_e' not in text
        assert text.startswith('COMMON\n')


@case
def t2_2_context_blocks_follow_recall_order():
    from asuna.context import order_context
    context = {'event': 1, 'ref_index': 2, 'memories': 3, 'dossier_from_program': 4, 'scene_id': 5,
               'delivered_history': 6, 'action_capabilities_from_program': 7, 'retrieval_diagnostic_from_host': 8,
               'self_state_from_program': 9, 'relationship': 10, 'custom_from_program': 11}
    default = list(order_context(context))
    assert default == ['scene_id', 'self_state_from_program', 'dossier_from_program', 'relationship', 'memories',
                       'delivered_history', 'custom_from_program', 'action_capabilities_from_program',
                       'retrieval_diagnostic_from_host', 'ref_index', 'event'], default
    ordered = list(order_context(context, ['memories', 'dossier', 'history']))
    assert ordered[1:5] == ['memories', 'dossier_from_program', 'delivered_history', 'self_state_from_program'], ordered
    assert set(ordered) == set(context), 'no key is dropped'


@case
def t2_3_over_budget_render_is_complete():
    from asuna.render import compose, estimate_tokens
    big = doc(*[(f's{i}', 'public', 'always', []) for i in range(400)])
    text = compose('C', big, None, 'owner_private')
    assert all(f'BODY_s{i}' in text for i in range(400)) and estimate_tokens(text) >= len(text)


@case
def t2_9_sid_generation_is_deterministic():
    from asuna.documents import parse_markdown, slugify
    text = '<!-- asuna-seed {"sections": {"values": {"tags": ["values"], "visibility": "owner_private"}, "ghost": {}}} -->\n' \
           '# Title\nintro\n## Values\nv1\n## Values\nv2\n## 说话 方式！\nx\n'
    one, two = parse_markdown(text, 'persona'), parse_markdown(text, 'persona')
    assert one == two
    _, sections, unknown = one
    assert [s['sid'] for s in sections] == ['_preamble', 'values', 'values-2', '说话-方式'], [s['sid'] for s in sections]
    assert sections[1]['tags'] == ['values'] and sections[1]['visibility'] == 'owner_private'
    assert sections[2]['visibility'] == 'public' and sections[0]['inject'] == 'always'
    assert unknown == ['ghost']
    assert slugify('Hello, World') == 'hello-world'
    _, ledger, _ = parse_markdown('## a\nx', 'working')
    assert ledger[0]['inject'] == 'on_demand'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    for fn in CASES:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception as exc:
            detail = str(exc) or traceback.format_exc().strip().splitlines()[-1]
            print('FAIL', fn.__name__, detail[:300].replace('\n', ' '))


if __name__ == '__main__':
    main()
