"""ADR-069: a text over its length is refused and nothing is done; the refusal offers its beginning, cut at the last
sentence end that fits, with the program's mark of the cut, so that sending it as it is never passes for the whole."""
from asuna import role_tools, schedule
from asuna.config import CUT_MARK, cut


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


def test_every_length_refusal_offers_the_cut():
    try:
        role_tools.RoleTools._text(None, {'idea': '想法一。' * 200}, 'idea', role_tools.IDEA_CHARS)
    except role_tools.Refused as exc:
        said = str(exc)
    assert '超了 300 字' in said and cut('想法一。' * 200, role_tools.IDEA_CHARS) in said
    assert '去掉的是这' in said                            # what the cut leaves out is shown too (her ask)
    assert cut('到点了。' * 300, schedule.INTENT_CHARS) in schedule.intent_problem('到点了。' * 300)


def test_a_text_past_what_she_was_asked_for_but_within_the_limit_is_kept_and_said():
    """Owner 2026-10-20: she is asked for four fifths of the limit; the limit itself does not move."""
    from asuna.config import over, soft
    tools = role_tools.RoleTools.__new__(role_tools.RoleTools)
    tools.over = []
    assert soft(role_tools.IDEA_CHARS) == 400
    assert tools._text({'idea': 'x' * 400}, 'idea', role_tools.IDEA_CHARS) and tools.over == []
    assert tools._text({'idea': 'x' * 450}, 'idea', role_tools.IDEA_CHARS)
    assert tools.over == ['idea 450 字，超了 50 字（400 字以内，最多 500 字），这次照收了']
    assert over(501, 500) is None and over(400, 500) is None
