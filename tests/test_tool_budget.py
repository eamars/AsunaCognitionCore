"""Each brain's tools have a budget: how many it defines and how large their descriptions are (characters of the JSON
the model is sent). A change that adds a tool or grows the descriptions past the budget fails here until the budget
below is raised. A change that removes one lowers the
count here too, so the budget never drifts above what exists."""
import json

from asuna import role_tools
from asuna.config import soft
from asuna.development import DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS
from asuna.image_generation import GENERATE_IMAGE_TOOL
from asuna.private_words import PRIVATE_WORDS_TOOL
from asuna.svg_render import RENDER_SVG_TOOL
from asuna.tasks import ACTION_DSH_CAPABILITIES, INTEGRATION_TOOLS, WORKSPACE_TOOLS

# (tools defined, description characters at most)
CHARACTER = (30, 21409)       # ADR-096 decision 6: write_document's pinned, and what each place carries +80; ADR-092 D1: speak's file part (its name and where its artifact_id is copied from) +49; ADR-091 D2: note's deliver names a reply's default +20; soft limits (owner 2026-10-22): a stated length names only what she is asked for -182; watch block takes person (ADR-052 addendum 2026-10-21) +29; ADR-087 §4.1: think asks 120, refused past 360 (both numbers) +10; §4.5: note's matching advice (naming the source does not pass) +32; ADR-086 D1/D5: feel's who field and the recording words, +264;       # ADR-060: new names and the wording audit, 21,490 -> 19,717 (rules the program does not enforce kept, her review);
                              # ADR-064 phase 2: reply +1,334 (QQ group lists +451 net, QQ private +1,028), stay_silent -16, leave_note question +88;
                              # reply force (a #number that is someone here is sent back unless force=yes; owner 2026-10-14) +90; stay_silent why optional (said: nothing to explain) -10;
                              # ADR-060 leftovers: recall query optional with sections, feel yes/no and its decisions named, recall section +25
                              # second wording audit (her yes 2026-10-14): 回合 for her turn, 家里·私聊 for the home chat, 叫到你才会醒 +2
                              # ADR-066: errand says it carries home and drops "only when the one talking asks" -6
                              # ADR-069: update_self retired (-396); pass_note and leave_note one note tool (1,028 -> 642;
                              # each conversation listed one of them: at home +75, elsewhere +181)
                              # sticker do=shelf +20: the home shelf (5,700 characters a home turn) comes on asking
                              # ADR-079 step 2: the quote tool removed (no channel that lists it can quote), quote and react
                              # take a line by its number, recall's which becomes line: 31 -> 30 tools, 20,452 -> 20,247
                              # her own line taken back (her ask, the owner's yes 2026-10-18): speak's recall part +153
                              # ADR-081: read_image reads a video as a contact sheet, its 32 MB cap stated +45
                              # ADR-076 R10: speak no longer restates where words leave (the guide says it once) -40;
                              # stay_silent is not listed where only speak speaks (one tool fewer there)
                              # ADR-082: recall reads a person and 「名单」 at home +114; understand_person writes anyone present
                              # with its short, 「不更新」, the three questions and speak-first +351 (block_hours leaves it);
                              # watch does block +85: 20,405 -> 20,955
                              # no night hours on her visits: place_timezone no longer says it decides night -3
                              # soft text budget (owner 2026-10-20): each stated length gives what she is asked for and
                              # where the program refuses, 「N 字以内，最多 M 字」 (her ask: both numbers) +155
# With tiered memory on (ADR-062 phase 2, memory_tiers.ENABLED): let_go, nature, from, about and the recall sentence (+294).
CHARACTER_TIERED = (30, 21705)                  # ADR-096 decision 6: pinned +80; ADR-092 D1: speak's file part +49
ACTION = (26 + len(ACTION_DSH_CAPABILITIES), 16141)        # the worker's tools, plus DSH's own (skill, todo, web);
                                                           # ADR-092 D2: offer_file, 25 -> 26 tools, +441 (15,467 -> 15,908 measured)


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


def test_with_tiered_memory_on_the_character_brain_stays_within_its_budget():
    check('character (tiered memory on)', list(role_tools.TIERED.values()), *CHARACTER_TIERED)


def test_with_tiered_memory_off_her_tools_are_exactly_as_before(monkeypatch):
    """The switch off changes nothing she is shown: the same tools, byte for byte (her prompt cache holds)."""
    from asuna import memory_tiers
    monkeypatch.setattr(memory_tiers, 'ENABLED', False)
    assert role_tools.tools() is role_tools.TOOLS and size(list(role_tools.TOOLS.values())) == CHARACTER[1]
    assert 'let_go' not in str(role_tools.TOOLS['write_document'])
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    assert role_tools.tools() is role_tools.TIERED and role_tools.aliases()['update_self'] == 'write_document'
    assert 'update_self' in [spec['name'] for spec in role_tools.all_specs()], 'the retired name still runs'


def test_the_action_brain_stays_within_its_tool_budget():
    worker = [*WORKSPACE_TOOLS, GENERATE_IMAGE_TOOL, RENDER_SVG_TOOL, PRIVATE_WORDS_TOOL, *INTEGRATION_TOOLS,
              *DEVELOPMENT_TOOLS, *PERSONA_JOB_TOOLS]
    check('action', worker, *ACTION, extra=len(ACTION_DSH_CAPABILITIES))


# Copied values (ids, names she copies from a list) and the thought, whose description states its own soft limit.
COPIED = {('think', 'thought'), ('attach_image', 'artifact_id'), ('set_policy', 'key'), ('feel', 'event_id'),
          ('feel', 'proposal_id'), ('feel', 'why'), ('plan', 'line'), ('plan', 'plan_id'), ('visit', 'place'),
          ('errand', 'place'), ('peer_line', 'line'), ('place_timezone', 'place'), ('place_timezone', 'timezone'),
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
            stated = (role_tools.LIMIT_WORDS % soft(value), role_tools.EXACT_WORDS % value)
            if not any(words in params[field].get('description', '') for words in stated):
                unstated.append('%s.%s (%d)' % (tool, field, value))
    assert not unstated, 'state these limits with _s(limit=...): ' + ', '.join(unstated)


# The harness prompt files (src/asuna/resources/prompts), characters at most. Same rule as the tools: growing one
# raises its number here in the same change, with the cost stated in its ADR; a new file gets a line.
PROMPTS = {'common.md': 418, 'turn.md': 639, 'turn_consult.md': 187, 'executor.md': 680, 'stage_attend.md': 445,
           'stage_appraise.md': 416}


def test_the_harness_prompts_stay_within_their_budget():
    from pathlib import Path
    folder = Path(role_tools.__file__).parent / 'resources' / 'prompts'
    have = {path.name: len(path.read_text(encoding='utf-8')) for path in folder.glob('*.md')}
    assert set(have) == set(PROMPTS), 'every prompt file has a budget line: %s' % sorted(set(have) ^ set(PROMPTS))
    over = ['%s is %d characters, over %d' % (name, have[name], PROMPTS[name]) for name in have if have[name] > PROMPTS[name]]
    assert not over, '; '.join(over) + ': shorten it, or state the cost in the ADR and raise the budget here.'
