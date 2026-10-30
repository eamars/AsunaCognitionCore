"""The relevance gate (attend.py): a group turn nobody addressed to her asks 接话 or 不理 before any recall."""


from asuna import attend


def test_parse_takes_only_the_two_answers():
    assert attend.parse('接话：有人在问我刚才说的事') == {'choice': 'join', 'reason': '有人在问我刚才说的事'}
    assert attend.parse('\n不理：他们在聊游戏\n多余的') == {'choice': 'quiet', 'reason': '他们在聊游戏'}
    odd = attend.parse('我觉得可以说两句')
    assert odd['choice'] == 'quiet' and odd['unparsed'] == '我觉得可以说两句'
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'name_called'}})
    # ADR-086 E1: an @ or a reply to her is asked too, unless it answers what she waits for or asked; the ambiguous
    # looks stay asked.
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'mentioned_account'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'reply_to_character'}})
    assert not attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'mentioned_account', 'answers_her': True}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'awaited_answer'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'question_wait'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'watched'}})
    assert not attend.gated({'kind': 'dm'}, {'group_context': {'wake_reason': 'proactive_unprompted'}})


def test_each_gate_question_has_its_own_session_and_its_repairs_stay_in_it():
    from asuna.native_worker import gate_session_id
    first, again = gate_session_id('c:g:1:P1', 'ep-1:ATTEND:0'), gate_session_id('c:g:1:P1', 'ep-2:ATTEND:0')
    assert first != again and first.startswith('asuna-attend-')
    assert gate_session_id('c:g:1:P1', 'ep-1:ATTEND:0:fix-1') == first


def test_the_gate_reads_her_own_words_and_no_program_rules(monkeypatch):
    """ADR-110: her words for the gate (persona model `attend.guide`) follow her core sentences, introduced as hers;
    nothing of common.md. Lost silently, she would edit them for nothing."""
    from asuna import carried
    from asuna.render import common_text
    monkeypatch.setattr(carried, 'carried', lambda *args, **kwargs: {'core': []})

    class Store:
        config = {'chat': {'display_name': '测试'}, 'persona_model': {'attend': {'guide': '我自己定的分寸'}}}
    text = attend.system(Store(), 'P1')
    assert text == '你是测试。\n\n' + attend.GUIDE_HEAD + '\n我自己定的分寸'
    assert common_text({}).splitlines()[0] not in text
    for model in ({}, {'attend': {'guide': '   '}}):
        Store.config = {'chat': {'display_name': '测试'}, 'persona_model': model}
        assert attend.system(Store(), 'P1') == '你是测试。'
