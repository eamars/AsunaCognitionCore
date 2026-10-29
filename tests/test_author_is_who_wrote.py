"""ADR-089: a line's author is who wrote it. A task result and a due plan are the program's lines (PROGRAM_AUTHOR); the
person who authorized the turn stays on the event and the episode, and everything that decides who may do what reads
that. The program is never a person: no label number, no roster record, no voice, nobody present."""


from asuna.discussion_digest import build_digest
from asuna.ingress import PROGRAM_AUTHOR
from asuna.people import PROGRAM_LABEL


# ---- the rule -------------------------------------------------------------------------------------------------------


# ---- the program is never a person ----------------------------------------------------------------------------------


# ---- readers --------------------------------------------------------------------------------------------------------


def test_a_digest_counts_no_program_participant():
    def hit(mid, seq, author, speaker, text):
        return {'message_id': mid, 'scene_id': 'g1', 'scene_seq': seq, 'at': '2026-09-22T12:0%d:00Z' % seq,
                'time_source': 'messages.occurred_at', 'author': author, 'direction': 'inbound', 'side': '他说',
                'speaker': speaker, 'text': text, 'person_match': True}
    digest = build_digest([hit('a1', 1, 'A', '[林 #1]', '明天去修吧？'),
                           hit('p1', 2, PROGRAM_AUTHOR, PROGRAM_LABEL, '你之前安排的计划「喝水」现在到期了。')],
                          {}, {'scene_id': 'g1'})
    assert [person['display'] for person in digest['participants']] == ['[林 #1]']
    assert digest['source_ids'] == ['a1', 'p1']                         # read and covered, just nobody's words
