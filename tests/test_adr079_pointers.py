"""ADR-079 step 1: lines that point at other lines read the same whoever made them.

Where the channel's adapter declares quotes (`quote` or `quote_in` on its claims), every line shows its number; a
quote, anyone's, reads `> 回复 〔n〕 <speaker>：<first words>` (her own lines as 你); a quote of a line the program has no
record of says so; a line that only quotes says it has no words; a private chat's quote reaches her like a group's;
the `speak` result gives each sent line's number; and a number written into her words is refused."""

import pytest

from asuna import capabilities
from asuna.role_tools import LINE_NUMBER, NUMBER_NOT_WORDS, reply_receipt
from test_people import GROUP


@pytest.fixture(autouse=True)
def fresh_capabilities():
    capabilities.forget()
    yield
    capabilities.forget()


def test_the_speak_result_gives_each_sent_lines_number_and_a_number_in_her_words_is_refused():
    queued = [{'number': 1, 'shown': 'text', 'state': 'READY', 'seq': 320},
              {'number': 2, 'shown': 'text', 'state': 'READY', 'seq': 321}]
    assert '1 text 〔320〕；2 text 〔321〕' in reply_receipt(queued, numbered=True)
    assert '〔' not in reply_receipt(queued)
    assert LINE_NUMBER.search('你看〔318〕那句') and not LINE_NUMBER.search('今天 3 点')
    assert NUMBER_NOT_WORDS == '编号是挑引用用的，不写进你说的话里。'


def test_her_thought_under_a_quote_of_her_line_is_an_anchor_cut_at_a_sentence_end():
    from asuna.people import anchor
    thought = '他说得对，我先认下。' + '后面这段是我当时对整件事的长判断' * 6
    short = anchor(thought)
    assert short == '他说得对，我先认下。…（截断，原文 %d 字）' % len(thought)
    assert anchor('一句短的。') == '一句短的。'
    no_end = '没有句号的一整段' * 12
    assert anchor(no_end).startswith(no_end[:60] + '…（截断')
