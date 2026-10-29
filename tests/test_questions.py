"""ADR-061 step 1: her questions to her home places and the action brain -- asked with `ask`, answered by the next line
there (or a line naming the question, or the task's report), lapsing past their patience, closed by her or once by the
program, and shown at home once per change without repeating a text in the same notice."""

from asuna import notes, questions
from asuna.channels import kept_raw

HOME = {'event_id': 'ask-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'}


def test_a_line_names_a_question_only_on_a_home_line(monkeypatch):
    raw = {questions.ANSWER_KEY: {'question': 'q-1a2b3c4d'}}
    from asuna import channel_kinds
    monkeypatch.setitem(channel_kinds._KINDS, 'homeline', type('HomeLine', (), {'KIND': 'homeline', 'HOME': True}))
    assert kept_raw({'scene_id': 'homeline:home:dm:x'}, raw)[questions.ANSWER_KEY] == {'question': 'q-1a2b3c4d'}
    assert questions.ANSWER_KEY not in kept_raw({'scene_id': 'qq:acct:group:1'}, raw)
    assert questions.ANSWER_KEY not in kept_raw({'scene_id': 'homeline:home:dm:x'}, {questions.ANSWER_KEY: {'question': 'x'}})


