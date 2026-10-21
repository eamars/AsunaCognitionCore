"""ADR-069: a text over its length is refused and nothing is done; the refusal offers its beginning, cut at the last
sentence end that fits, with the program's mark of the cut, so that sending it as it is never passes for the whole; a
list she writes gets no cut, since its end says what counts as done (her ask, 2026-10-22)."""
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


def refused(args, field, limit, **kw):
    try:
        role_tools.RoleTools._text(None, args, field, limit, **kw)
    except role_tools.Refused as exc:
        return str(exc)


def test_a_length_refusal_offers_the_cut_and_a_list_gets_none():
    said = refused({'why': '因为这样。' * 100}, 'why', 200)
    # Worded by what she is asked for, and the cut offered fits it (owner 2026-10-22).
    assert '要求 160 字以内，超了 340 字' in said and cut('因为这样。' * 100, 160) in said and '最多' not in said
    assert '去掉的是这' in said                            # what the cut leaves out is shown too (her ask)
    # A list's last line says what counts as done and any cut of the end loses it: no cut, she chooses (her ask).
    said = refused({'idea': '想法一。' * 200}, 'idea', role_tools.IDEA_CHARS, offer=False)
    assert said.endswith('要求 400 字以内，超了 400 字。精简到 400 字以内再调用，删哪段你自己定。') and '截' not in said
    assert '截' not in schedule.intent_problem('到点了。' * 300)


def test_the_list_fields_are_the_ones_without_a_cut():
    import inspect
    source = inspect.getsource(role_tools)
    for field in ("'intent', 1000", "'request', ERRAND_CHARS", "'idea', IDEA_CHARS"):
        calls = source.split("self._text(args, %s" % field)[1:]
        assert calls and all(call.startswith(', offer=False)') for call in calls), field


def test_a_text_past_what_she_was_asked_for_but_within_the_limit_is_kept_and_said():
    """Owner 2026-10-20: she is asked for four fifths of the limit; the limit itself does not move."""
    from asuna.config import over, soft
    tools = role_tools.RoleTools.__new__(role_tools.RoleTools)
    tools.over = []
    assert soft(role_tools.IDEA_CHARS) == 400
    assert tools._text({'idea': 'x' * 400}, 'idea', role_tools.IDEA_CHARS) and tools.over == []
    assert tools._text({'idea': 'x' * 450}, 'idea', role_tools.IDEA_CHARS)
    assert tools.over == ['idea 450 字，要求 400 字以内，超了 50 字，这次照收了']
    assert over(501, 500) is None and over(400, 500) is None
