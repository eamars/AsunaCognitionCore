"""ADR-135 landing 5 (D4, D5, D6 for the tool texts), on the fixture world in memory: an outside turn is told nothing in
advance about what her hands can do, and its system prompt explains no block only home carries; every tool text she
can be shown names no part of her, no block, no turn and no one's gender; `task` and `group_action` are the settled
texts byte for byte; an option of one moment is refused with the plain sentence outside it. g1 is an outside group,
dm-a the owner A's chat (home)."""
import re
from pathlib import Path

import pytest

from asuna import block_guide, guard, role_tools, visibility
from asuna import understanding as _understanding
from test_adr135_guard import denied, her, turn  # noqa: F401  (her: a fixture)

TEXTS = Path(__file__).resolve().parents[1] / 'docs/development_plans/ADR-135-what-an-ask-from-outside-can-reach/tool-texts.md'
# A part of her, a block, a turn, someone's gender (AGENTS.md; ADR-135 D6).
FORBIDDEN = {'a part of her': re.compile(r'行动脑|角色脑|说话的那一半|动手的那一半'),
             'a block': re.compile(r'_from_program'), 'a turn': re.compile(r'回合'), 'a gender': re.compile(r'[他她](?!们)')}


def words(spec):
    """Every text of a spec she reads: its description and each field's, nested ones included."""
    out = [spec.get('description') or '']

    def walk(params):
        for value in (params or {}).values():
            if isinstance(value, dict):
                out.append(value.get('description') or '')
                walk(value.get('properties'))
                walk((value.get('items') or {}).get('properties'))
    walk(spec.get('parameters'))
    return out


def shown(store, scene_id, person_id):
    return {spec['name']: spec for spec in role_tools.session_specs(store, scene_id, person_id)}


def test_T1_an_outside_turn_is_told_nothing_in_advance_about_her_hands(her, monkeypatch):
    from test_her_clock import prepared
    outside, home = prepared(her.store, monkeypatch, 'g1'), prepared(her.store, monkeypatch, 'dm-a')
    for key in ('action_capabilities_from_program', 'session_class'):
        assert key not in outside and key in home, key
    from asuna import notes
    named = [item['name'] for item in (outside.get('note_places_from_program') or {}).get('items') or []]
    assert set(named) <= {notes.HOME_NAME, *notes.owner_chat_names(her.store.config)}, named
    guide_outside = block_guide.guide(her.store.config, outside=True)
    guide_home = block_guide.guide(her.store.config)
    assert all(key not in guide_outside and key in guide_home for key in block_guide.HOME_ONLY)


def test_T1_a_home_turn_a_note_from_outside_opened_is_told_nothing_about_her_hands(her, monkeypatch):
    from test_her_clock import prepared
    from asuna import notes
    notes.save(her.store, {'_id': 'note-t1', 'persona': 'P1', 'from_scene': 'g1', 'from_class': visibility.PUBLIC,
                           'to_scene': 'dm-a', 'kind': 'home', 'text': '造的：外面写来的', 'trust': notes.UNTRUSTED,
                           'seen_in': [], 'created_at': '2026-09-24T04:58:00+00:00', 'mode': notes.WAKE, 'hop': 0}, stream='notes:P1')
    notes.save(her.store, {'_id': 'note-own', 'persona': 'P1', 'from_scene': 'dm-a',
                           'from_class': visibility.OWNER_PRIVATE, 'to_scene': 'dm-a', 'kind': 'home',
                           'text': '造的：家里写的', 'trust': notes.TRUSTED, 'seen_in': [], 'created_at': '2026-09-24T04:58:00+00:00', 'mode': notes.WAKE, 'hop': 0}, stream='notes:P1')
    opened = prepared(her.store, monkeypatch, 'dm-a', {'episode_kind': 'note', 'note': {'id': 'note-t1'}})
    own = prepared(her.store, monkeypatch, 'dm-a', {'episode_kind': 'note', 'note': {'id': 'note-own'}})   # home's
    assert 'action_capabilities_from_program' not in opened and 'action_capabilities_from_program' in own


def test_T2_no_tool_text_names_a_part_of_her_a_block_a_turn_or_a_gender(her):
    found = []
    for scene_id, person_id in (('g1', 'B'), ('dm-a', 'A')):
        for name, spec in shown(her.store, scene_id, person_id).items():
            for text in words(spec):
                # her own words, left as hers: the local chat's speak, and her three questions (AGENTS.md: her writing
                # names things as she likes)
                text = text.replace(role_tools.LOCAL_SPEAK, '').replace(_understanding.ASK, '')
                for what, pattern in FORBIDDEN.items():
                    found += ['%s %s: %s in %r' % (scene_id, name, what, match.group()) for match in pattern.finditer(text)]
    assert found == []


def settled(tool):
    """The text tool-texts.md gives for `task` (Settled) or `group_action` (unchanged)."""
    lines = TEXTS.read_text(encoding='utf-8').split('\n')
    start = next(n for n, line in enumerate(lines) if line.startswith('**`%s`**' % tool))
    if tool == 'task':
        start = next(n for n in range(start, len(lines)) if lines[n].startswith('Settled:'))
    return next(line[2:] for line in lines[start + 1:] if line.startswith('> '))


@pytest.mark.parametrize('tool', ['task', 'group_action'])
def test_T2_task_and_group_action_are_the_settled_texts_byte_for_byte(her, tool):
    assert role_tools.tools()[tool]['description'] == settled(tool)
    for scene_id, person_id in (('g1', 'B'), ('dm-a', 'A')):
        assert shown(her.store, scene_id, person_id)[tool]['description'] == settled(tool)


def test_T2_a_sentence_of_an_ability_is_shown_only_where_it_is_listed(her):
    outside, home = shown(her.store, 'g1', 'B'), shown(her.store, 'dm-a', 'A')
    for tool, sentence in (('plan', role_tools.PLAN_LINE), ('group_focus', role_tools.FOCUS_MUTE),
                           ('recall', role_tools.RECALL_ELSEWHERE), ('read_image', role_tools.READ_IMAGE_HOME),
                           ('note', role_tools.NOTE_DELIVER), ('write_document', role_tools.WRITE_OWN_DOCS)):
        assert sentence not in outside[tool]['description'] and sentence in home[tool]['description'], tool
    assert role_tools.WRITE_GROUP_NOTES in outside['write_document']['description']
    assert outside['note']['parameters']['to']['enum'][0] == '家里'


def test_T3_an_option_of_one_moment_outside_it_gets_the_plain_sentence(her):
    ep = turn(her)
    for args in ({'do': 'answer', 'task': 't', 'answer': '好'}, {'do': 'more', 'task': 't'}):
        assert 'task.' + args['do'] not in ep['turn_tools']
        refusal = denied(her, ep, 'task', args)
        assert (str(refusal), list(refusal.codes)) == (guard.NOT_DONE, ['not_now'])
