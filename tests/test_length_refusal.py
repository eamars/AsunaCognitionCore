"""ADR-069, ADR-108 D4a and D4c: a text over its line is refused and nothing is done. The refusal says the line, how far
over she went, the aim, where the line comes from and where the excess starts, by characters. It repeats none of her words,
offers no cut and does not judge which part to drop; a list she writes also says on which line the excess starts. A text
between the aim and the line is kept and the result says the fact, without leniency."""
from asuna import role_tools, schedule
from asuna.config import CUT_MARK, cut, excess_line, over, soft, too_long


def tools():
    return role_tools.RoleTools.__new__(role_tools.RoleTools)


def refused(args, field, limit, tool=None, **kw):
    maker = tools()
    maker.tool = tool
    try:
        maker._text(args, field, limit, **kw)
    except role_tools.Refused as exc:
        return str(exc), exc.codes


def repeats(refusal, prose, size=20):
    """The program check B3 counts on: whether a refusal holds `size` consecutive characters of the call's prose."""
    return any(prose[start:start + size] in refusal for start in range(0, max(1, len(prose) - size + 1)))


def test_the_cut_keeps_the_beginning_ends_at_a_sentence_and_says_how_much_was_cut():
    text = '第一句说完了。第二句也说完了！' + '第三句很长' * 20
    kept = '第一句说完了。第二句也说完了！'
    assert cut(text, 40) == kept + CUT_MARK % (len(text) - len(kept))
    assert len(cut(text, 40)) <= 40
    quoted = '他说：「好。」然后' + '没' * 60
    assert cut(quoted, 40).startswith('他说：「好。」（截在这里')      # a closing quote stays with its sentence


def test_without_a_sentence_end_it_cuts_at_the_limit_and_a_short_text_is_as_it_is():
    out = cut('x' * 100, 50)
    head = out.split('（')[0]
    assert len(out) <= 50 and out == head + CUT_MARK % (100 - len(head)) and set(head) == {'x'}
    assert cut('短。', 10) == '短。'


def test_a_length_refusal_says_the_line_the_excess_the_aim_and_where_it_starts_and_offers_no_cut():
    prose = '因为这样。' * 100
    said, codes = refused({'why': prose}, 'why', 200, tool='write_document')
    assert said.startswith('why 太长了：500 字，过了 200 字的线 300 字（要求 160 字以内）。')
    assert '这句话会记进这一节的修订记录。' in said, 'where the line comes from'
    assert said.endswith('精简到 160 字以内再调用；200 字之后起是超出部分。')
    assert codes == ('TEXT_TOO_LONG',)
    assert not repeats(said, prose) and '截' not in said and '去掉的是' not in said and '最多' not in said


def test_a_list_she_writes_gets_the_line_the_excess_starts_on_and_the_choice_is_hers():
    prose = '想法一。' * 140 + '\n' + '后面还有一行' * 10
    said, _ = refused({'idea': prose}, 'idea', role_tools.IDEA_CHARS, tool='ideas', offer=False)
    assert said.endswith('删哪段你自己定；500 字之后起是超出部分，落在第 1 行（共 2 行）。'), said
    later = '想法一。' * 60 + '\n' + '第二行内容' * 100
    said, _ = refused({'idea': later}, 'idea', role_tools.IDEA_CHARS, tool='ideas', offer=False)
    assert said.endswith('落在第 2 行（共 2 行）。'), 'the line the first character past the line is on'
    assert not repeats(said, prose) and '截' not in said
    lines = '\n'.join(['一行内容写在这里'] * 80)
    where, total = excess_line(lines, 200)
    assert total == 80 and where == lines[:200].count('\n') + 1 > 1
    assert '截' not in schedule.intent_problem('到点了。' * 300) and '删哪段你自己定' in schedule.intent_problem('到点了。' * 300)


def test_the_reason_comes_from_one_table_and_a_text_with_no_entry_gives_none():
    said, _ = refused({'thought': 'x' * 500}, 'thought', role_tools.THOUGHT_HARD_CHARS, tool='think', ask=role_tools.THOUGHT_CHARS)
    assert '心里话会存档' in said and '过了 360 字的线 140 字（要求 120 字以内）' in said
    said, _ = refused({'reason': 'x' * 2500}, 'reason', 1000, tool='task')
    assert 'reason 太长了' not in said and said.startswith('why 太长了：2500 字，过了 1000 字的线 1500 字（要求 800 字以内）。精简')


def test_a_failure_catch_has_no_aim_and_no_band():
    said, codes = refused({'brief': 'x' * 21000}, 'brief', 20000, tool='delegate')
    assert said == 'brief 太长了：21000 字，最多 20000 字。拆开：先交一部分，其余用 task 的 message 补。' and codes == ('TEXT_TOO_LONG',)
    said, _ = refused({'answer': 'x' * 21000}, 'answer', 20000, tool='task')
    assert said == 'answer 太长了：21000 字，最多 20000 字。'


def test_the_list_fields_are_the_ones_that_name_the_line_not_the_cut():
    import inspect
    source = inspect.getsource(role_tools)
    for field in ("'intent', 1000", "'request', ERRAND_CHARS", "'idea', IDEA_CHARS"):
        calls = source.split("self._text(args, %s" % field)[1:]
        assert calls and all(call.startswith(', offer=False)') for call in calls), field


def test_a_text_past_what_she_was_asked_for_but_within_the_line_is_kept_and_the_result_says_the_fact():
    """Owner 2026-10-20: she is asked for four fifths of the line; the line itself does not move (ADR-108 D4a)."""
    maker = tools()
    maker.over = []
    assert soft(role_tools.IDEA_CHARS) == 400
    assert maker._text({'idea': 'x' * 400}, 'idea', role_tools.IDEA_CHARS) and maker.over == []
    assert maker._text({'idea': 'x' * 450}, 'idea', role_tools.IDEA_CHARS)
    assert maker.over == ['idea 450 字，要求 400 字以内，多了 50 字；过了 500 字不收'], 'no 照收了: it is a fact'
    assert over(501, 500) is None and over(400, 500) is None


def test_a_field_the_strict_schema_named_is_not_named_twice_while_a_handler_collects():
    maker = tools()
    maker.collecting, maker.flagged, maker.problems = True, {'thought'}, []
    assert maker._text({}, 'thought', 360, ask=120) is None and maker.problems == []
    assert maker._text({'other': '  '}, 'other', 100) is None
    assert [code for code, *_ in maker.problems] == ['TEXT_EMPTY'], 'a field nobody named is still checked, and kept, not raised'


def test_the_tier_note_and_the_plan_intent_are_refused_in_the_same_form():
    """The delegate tier's reason and the scheduler's own intent check use the tool's sentence (config.too_long)."""
    from asuna import action_tiers
    import pytest
    text = '便条' * 400
    with pytest.raises(ValueError) as tier:
        action_tiers.chosen({'tier': '高', 'why': text})
    said = str(tier.value)
    assert said.startswith('why 太长了：800 字，过了 %d 字的线' % action_tiers.WHY_CHARS) and not repeats(said, text)
    intent = schedule.intent_problem('到点再想。' * 300)
    assert intent.startswith('intent 太长了：1500 字，过了 1000 字的线 500 字（要求 800 字以内）。') and not repeats(intent, '到点再想。' * 300)
