"""Each brain's tools have a budget: how many it defines and how large their descriptions are (characters of the JSON
the model is sent). A change that adds a tool or grows the descriptions past the budget fails here until the budget
below is raised in the same change, with the cost stated in its ADR (AGENTS.md). A change that removes one lowers the
count here too, so the budget never drifts above what exists."""
import json

from asuna import role_tools
from asuna.development import DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS
from asuna.image_generation import GENERATE_IMAGE_TOOL
from asuna.private_words import PRIVATE_WORDS_TOOL
from asuna.svg_render import RENDER_SVG_TOOL
from asuna.tasks import ACTION_DSH_CAPABILITIES, INTEGRATION_TOOLS, WORKSPACE_TOOLS

# (tools defined, description characters at most)
CHARACTER = (37, 21500)
ACTION = (25 + len(ACTION_DSH_CAPABILITIES), 15700)        # the worker's tools, plus DSH's own (skill, todo, web)


def size(specs):
    return len(json.dumps(specs, ensure_ascii=False))


def check(name, specs, count, budget, extra=0):
    have = len(specs) + extra
    assert have == count, ('%s brain defines %d tools, the budget says %d. Adding one: state its cost (tools, '
                           'description tokens, per-turn lines) in its ADR and raise the budget here; removing one: '
                           'lower it.' % (name, have, count))
    assert size(specs) <= budget, ('%s brain tool descriptions are %d characters, over the budget of %d: shorten '
                                   'them, or state the cost in the ADR and raise the budget here.'
                                   % (name, size(specs), budget))


def test_the_character_brain_stays_within_its_tool_budget():
    check('character', list(role_tools.TOOLS.values()), *CHARACTER)


def test_the_action_brain_stays_within_its_tool_budget():
    worker = [*WORKSPACE_TOOLS, GENERATE_IMAGE_TOOL, RENDER_SVG_TOOL, PRIVATE_WORDS_TOOL, *INTEGRATION_TOOLS,
              *DEVELOPMENT_TOOLS, *PERSONA_JOB_TOOLS]
    check('action', worker, *ACTION, extra=len(ACTION_DSH_CAPABILITIES))


# Copied values (ids, names she copies from a list) and the thought, whose description states its own soft limit.
COPIED = {('think', 'thought'), ('attach_image', 'artifact_id'), ('set_policy', 'key'), ('feel', 'event_id'),
          ('feel', 'proposal_id'), ('feel', 'why'), ('plan', 'line'), ('plan', 'plan_id'), ('visit', 'place'),
          ('errand', 'place'), ('peer_line', 'line'), ('place_timezone', 'place'), ('place_timezone', 'timezone'),
          ('read_report', 'task'), ('review_idea', 'idea')}
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
        if not head or head.group(1) not in role_tools.TOOLS:
            continue
        tool = head.group(1)
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
            if role_tools.LIMIT_WORDS % value not in params[field].get('description', ''):
                unstated.append('%s.%s (%d)' % (tool, field, value))
    assert not unstated, 'state these limits with _s(limit=...): ' + ', '.join(unstated)
