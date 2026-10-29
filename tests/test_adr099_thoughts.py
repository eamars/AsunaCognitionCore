"""ADR-099: her thoughts can come from the model's own thinking. In `thinking` mode her turn's steps and tool list do
not ask the character brain for its thoughts; `tool` mode, the default, keeps its words; the setting reads either; a
thought shown back is cut and marked."""
import re

import pytest

from asuna import block_guide, native_settings, role_tools

# What asking for her thoughts looks like: the tool's name, or a step that has her write 心里话 first.
ASKS = re.compile(r'(?<![A-Za-z])think(?![A-Za-z])|第一步[^。\n]{0,8}心里话|先[^。\n]{0,4}写[^。\n]{0,4}心里话')


def test_the_turn_steps_follow_the_mode_and_tool_mode_keeps_its_words():
    tool, unset, thinking = block_guide.guide({'thoughts': 'tool'}), block_guide.guide({}), block_guide.guide(
        {'thoughts': 'thinking'})
    assert tool == unset and '1. 第一步调用 think' in tool
    assert not ASKS.search(thinking.split('# 每回合的资料')[0])
    assert '1. 需要时用工具' in thinking and '2. ' in thinking and '3. ' not in thinking.split('说话时')[0]


def test_the_tool_lists_drop_think_only_in_thinking_mode():
    assert 'think' in role_tools.EVERYWHERE
    assert role_tools.thinking_mode({'thoughts': 'thinking'}) and not role_tools.thinking_mode({})
    assert role_tools.asks_thought({'turn_tools': ['think', 'recall']})
    assert not role_tools.asks_thought({'turn_tools': ['recall']}) and not role_tools.asks_thought({})
    assert 'think' not in role_tools.STAY_SILENT_THINKING and '心里话' not in role_tools.STAY_SILENT_THINKING
    assert 'think' not in role_tools.CONSULT_ONLY_THINKING


DEPLOYMENT = {'database': 'd', 'mongo_uri': 'mongodb://127.0.0.1', 'chat': {},
              'embedding': {'base_url': 'http://127.0.0.1:9/v1', 'model': 'm'}}
MODELS = {'character': {'model': 'x'}, 'action': {'model': 'x'}}


def test_the_setting_is_tool_or_thinking_and_shown_as_tool_by_default():
    for value in ('tool', 'thinking'):
        assert native_settings.runtime_settings({**DEPLOYMENT, 'thoughts': value}, {}, MODELS, persona='p')['thoughts'] == value
    assert 'thoughts' not in native_settings.runtime_settings(DEPLOYMENT, {}, MODELS, persona='p')
    with pytest.raises(ValueError, match='INVALID_THOUGHTS'):
        native_settings.runtime_settings({**DEPLOYMENT, 'thoughts': 'off'}, {}, MODELS, persona='p')
    assert native_settings.export_settings({'chat': {}})['deployment']['thoughts'] == 'tool'
    assert native_settings.export_settings({'chat': {}, 'thoughts': 'thinking'})['deployment']['thoughts'] == 'thinking'


# ---- capture, links and projection (§3.1 items 3-5) ------------------------------------------------------------------
from asuna import reasons                 # noqa: E402

THOUGHT = '他问我家有没有猫，我想起橘猫那天的事，想顺着聊两句，不太想把话题拉远。' * 5     # 190 characters, past the 120 cut


def thinking(text=THOUGHT):
    return {'type': 'thinking', 'thinking': text, 'signature': 'sig'}


def test_shown_cuts_and_marks_only_a_summary_and_recall_reads_more():
    mine = {'body_markdown': '我' * 300}
    summary = {'body_markdown': '摘' * 300, 'source': 'thinking'}
    assert reasons.shown(mine) == '我' * 300 and reasons.shown({}) is None
    short = reasons.shown(summary)
    body = lambda text: text[len(reasons.THINKING_LABEL):]
    assert short.startswith(reasons.THINKING_LABEL) and body(short).count('摘') == reasons.THINKING_CHARS
    assert body(reasons.shown(summary, 1200, recall=True)).count('摘') == 300


