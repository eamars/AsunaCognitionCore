"""ADR-021: her self-development comes in stages through the night, one at a time, never stacked."""

from asuna.rhythm import night_stage_block


def test_she_reads_which_stage_of_the_night_this_is():
    block = night_stage_block({'window': '01:00–06:00', 'every_min': 30, 'last_stage': True})
    assert block['window'] == '01:00–06:00' and block['pace'] == '每 30 分钟一段' and block['last'] == '这是今晚最后一段'
    assert '一段一件事' in block['note'] and '那个项目不能再发布' in block['note']


def test_the_night_tick_is_named_apart_from_the_daily_turn():
    """The 10-minute tick only asks whether a night stage is due; the task page names it so (owner 2026-10-09)."""
    from asuna.schedule import plan_title
    night = plan_title({'kind': 'self_development', 'night': True})
    daily = plan_title({'kind': 'self_development'})
    assert night != daily and 'Night' in night and 'Daily' in daily


def test_every_rhythm_task_has_a_title_in_every_ui_language():
    """A rhythm the locale files do not name keeps its English title in any UI language."""
    import json, pathlib
    from asuna.schedule import RHYTHM_TITLES
    for path in pathlib.Path(__file__).parents[1].joinpath('packages/cognition-core/locale').glob('*.json'):
        titles = json.loads(path.read_text(encoding='utf-8'))['asuna']['titles']
        assert set(RHYTHM_TITLES) <= set(titles), (path.name, set(RHYTHM_TITLES) - set(titles))


def test_a_plan_title_drops_markdown_bold_and_code_marks_but_keeps_her_words():
    from asuna.schedule import plan_title
    assert plan_title({'intent': '回看 Claude 那两件**我自己看到没有**，看 `scene_people`'}) == '回看 Claude 那两件我自己看到没有，看 scene_people'
    assert plan_title({'intent': '回 罗兹__official 一句'}) == '回 罗兹__official 一句'
