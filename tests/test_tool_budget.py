"""Each brain's tools have a budget: how many it defines and how large their descriptions are (characters of the JSON
the model is sent). A change that adds a tool or grows the descriptions past the budget fails here until the budget
below is raised. A change that removes one lowers the
count here too, so the budget never drifts above what exists."""
import json

from asuna import role_tools, tool_schema
from asuna.config import soft
from asuna.development import DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS
from asuna.image_generation import GENERATE_IMAGE_TOOL
from asuna.private_words import PRIVATE_WORDS_TOOL
from asuna.svg_render import RENDER_SVG_TOOL
from asuna.tasks import ACTION_DSH_CAPABILITIES, INTEGRATION_TOOLS, WORKSPACE_TOOLS

# (tools defined, description characters at most)
# ADR-108 D4b: the budget is measured on what the model is sent, her tools DECLARED (tool_schema.declared): each enum
# dropped for its values in the field's description, speak's parts one description. Declared, the character brain's tools are
# 20,990 characters (tiered memory on: 21,426), against 21,915 (22,211) measured on the definitions before: the aim and the line
# stated for her prose (D4a) and the new `line` field (D2) cost, the enum arrays and the nested part schema they replace save more.
# Her tools as she is sent them, tiered memory's (ADR-062 phase 2: let_go, nature, from, about, the recall sentence).
CHARACTER = (29, 21098)                  # ADR-129 D8: stay_silent removed, 30 -> 29 tools, -156 declared; ADR-126: write_document names her documents as she writes them, kind needed to make one +96; ADR-119 F14 §9.7: set_policy's home lines said as the gate is +36; F14: set_policy null clears, home only +30; ADR-117 L4: correction -47; ADR-112 §12.10: task's settle +103; §12.2: task's more +34; ADR-103: 贴纸 -> 表情包 +1, 表情名 -> 小黄脸名 +1; ADR-106: place_timezone removed, 31 -> 30 tools, -426 declared (21,426 -> 21,000); ADR-102: received_file +499; ADR-097: recall's bare word +19, elsewhere and past notes +19; ADR-096: pin and what each place carries +49; ADR-092 D1: speak's file part +49
ACTION = (27 + len(ACTION_DSH_CAPABILITIES), 16490)        # the worker's tools, plus DSH's own (skill, todo, web);
                                                           # ADR-102: received_file, 26 -> 27 tools, +291; its copy (part 3) +58;
                                                           # ADR-092 D2: offer_file, 25 -> 26 tools, +441 (15,467 -> 15,908 measured)


def size(specs):
    return len(json.dumps(specs, ensure_ascii=False))


def sent(tools):
    """Her tools as the model is sent them (ADR-108 D4b)."""
    return [{**spec, 'parameters': tool_schema.declared(name, spec['parameters'])} for name, spec in tools.items()]


def check(name, specs, count, budget, extra=0):
    have = len(specs) + extra
    assert have == count, ('%s brain defines %d tools, the budget says %d. Adding one: state its cost (tools, '
                           'description tokens, per-turn lines) in its ADR and raise the budget here; removing one: '
                           'lower it.' % (name, have, count))
    assert size(specs) <= budget, ('%s brain tool descriptions are %d characters, over the budget of %d: shorten '
                                   'them, or state the cost in the ADR and raise the budget here.'
                                   % (name, size(specs), budget))


def test_the_character_brain_stays_within_its_tool_budget():
    assert role_tools.tools() is role_tools.TIERED
    check('character', sent(role_tools.TIERED), *CHARACTER)


def test_retired_tools_never_come_back():
    # ADR-069: retired, never back; ADR-129 D8: stay_silent, gone from every conversation, aliased by nothing.
    retired = {'update_self', 'pass_note', 'leave_note', 'stay_silent'}
    assert not retired & set(role_tools.aliases()) and not retired & {spec['name'] for spec in role_tools.all_specs()}


def test_the_action_brain_stays_within_its_tool_budget():
    worker = [*WORKSPACE_TOOLS, GENERATE_IMAGE_TOOL, RENDER_SVG_TOOL, PRIVATE_WORDS_TOOL, *INTEGRATION_TOOLS,
              *DEVELOPMENT_TOOLS, *PERSONA_JOB_TOOLS]
    check('action', worker, *ACTION, extra=len(ACTION_DSH_CAPABILITIES))


# Copied values (ids, names she copies from a list) and the thought, whose description states its own soft limit.
COPIED = {('think', 'thought'), ('attach_image', 'artifact_id'), ('set_policy', 'key'), ('feel', 'event_id'),
          ('feel', 'proposal_id'), ('feel', 'why'), ('plan', 'line'), ('plan', 'plan_id'), ('visit', 'place'),
          ('errand', 'place'), ('peer_line', 'line'),
          ('task', 'task'), ('ideas', 'id'), ('ask', 'id')}
SAFETY_CAP = 20000          # limits this large are a guard, never a length she writes toward


def test_every_length_she_can_be_refused_for_is_stated(tmp_path):
    """ADR-054 (her rule): a free-text parameter the program refuses past a length says that length in its
    description, so the rule holds for every tool instead of being added one at a time."""
    import re
    from pathlib import Path
    source = (Path(role_tools.__file__)).read_text(encoding='utf-8')
    unstated = []
    for method in re.split(r'\n    def ', source):
        head = re.match(r'tool_([a-z_]+)\(', method)
        # tool_<tool>, or tool_<tool>_<op> for a tool with options (role_tools.OPS)
        tool = head and next((name for name in (head.group(1), head.group(1).split('_')[0])
                              if name in role_tools.TOOLS), None)
        if not tool:
            continue
        params = role_tools.TOOLS[tool].get('parameters') or {}
        for field, limit in re.findall(r"_text\(args, '([a-z_]+)', ([A-Z_0-9]+)\)", method):
            if limit.isdigit():
                value = int(limit)
            elif hasattr(role_tools, limit):
                value = getattr(role_tools, limit)
            else:                                   # a constant the method imports: from .module import NAME
                import importlib
                module = re.search(r'from \.(\w+) import [^\n]*\b%s\b' % limit, method).group(1)
                value = getattr(importlib.import_module('asuna.' + module), limit)
            if field not in params or value >= SAFETY_CAP or (tool, field) in COPIED:
                continue
            stated = (role_tools.LIMIT_WORDS % (soft(value), value), role_tools.EXACT_WORDS % value)
            if not any(words in params[field].get('description', '') for words in stated):
                unstated.append('%s.%s (%d)' % (tool, field, value))
    assert not unstated, 'state these limits with _s(limit=...): ' + ', '.join(unstated)


# The harness prompt files (src/asuna/resources/prompts), characters at most. Same rule as the tools: growing one
# raises its number here in the same change, with the cost stated in its ADR; a new file gets a line.
PROMPTS = {'common.md': 418, 'turn.md': 639, 'turn_consult.md': 187, 'executor.md': 680, 'stage_attend.md': 349,
           'turn_thinking.md': 639, 'turn_consult_thinking.md': 187,          # ADR-099: their tool-mode twins' budgets
           'stage_appraise.md': 416,
           'turn_task_time.md': 219, 'turn_task_time_thinking.md': 211}   # ADR-112 §12.2: the program asks her at a stage's limit


def test_the_harness_prompts_stay_within_their_budget():
    from pathlib import Path
    folder = Path(role_tools.__file__).parent / 'resources' / 'prompts'
    have = {path.name: len(path.read_text(encoding='utf-8')) for path in folder.glob('*.md')}
    assert set(have) == set(PROMPTS), 'every prompt file has a budget line: %s' % sorted(set(have) ^ set(PROMPTS))
    over = ['%s is %d characters, over %d' % (name, have[name], PROMPTS[name]) for name in have if have[name] > PROMPTS[name]]
    assert not over, '; '.join(over) + ': shorten it, or state the cost in the ADR and raise the budget here.'
