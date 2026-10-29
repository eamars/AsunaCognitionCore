"""Her own account is her (2026-10-22). A group's roster had filed her own QQ account as another person ("沈小满 #4",
in 11 groups since 10-06): a task result carried its request's @-list, and the check "is this number me" compared it
with that row's own envelope, which a program line does not have. The member list then showed her own row as a
stranger. Now the account her channel speaks with in a scene is her wherever an account becomes a person, a program
line carries nothing of the line it is about but its thread, and the member list tells her her own names there."""

from asuna import attend
from asuna.ingress import program_group_context
from test_people import BOT

REQUEST = {'wake_reason': 'mentioned_account', 'topic_id': 'topic-1', 'reply_to': '555', 'reply_message_id': 'in-mine',
           'mentioned_account_ids': [BOT]}


# ---- one definition: her account is her ------------------------------------------------------------------------


# ---- she is told her own names --------------------------------------------------------------------------------


# ---- a program line carries only its thread -------------------------------------------------------------------

def test_a_program_line_keeps_the_thread_and_nothing_of_its_requests_envelope():
    group = program_group_context({'event': {'group_context': REQUEST}})
    assert group == {'wake_reason': None, 'topic_id': 'topic-1', 'reply_to': None, 'reply_message_id': None,
                     'mentioned_account_ids': []}
    scene = {'kind': 'group'}
    assert attend.gated(scene, {'group_context': REQUEST}) and not attend.gated(scene, {'group_context': group})
    assert program_group_context({'event': {}}) is None and program_group_context(None) is None


