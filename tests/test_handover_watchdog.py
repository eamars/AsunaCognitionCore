"""ADR-030: the program's watchdog over handovers between the brains catches definite failures and nothing else."""
from types import SimpleNamespace

from asuna import handover
from asuna.state import now
from asuna.lanes import FakeTurn


def test_her_task_list_says_where_each_task_stands_in_words():
    words = handover.status_words
    assert words({'state': 'READY'}) == '排着队，还没开始跑'
    assert words({'state': 'RUNNING'}) == '在跑'
    assert words({'state': 'RETURNED', 'feedback_state': 'DELIVERED'}) == '跑完了，结果已经交给你'
    assert words({'state': 'RETURNED', 'feedback_state': 'READY'}) == '跑完了，结果还没交到你手上：报告存着，程序会交给你'
    assert words({'state': 'BLOCKED', 'feedback_state': 'UNDELIVERABLE'}).startswith('没做成，但结果交不到你手上')
    assert words({'state': 'PAUSED'}).startswith('做到一半宿主重启停了')
    assert words({'state': 'CANCELLED', 'cancel_reason': 'host_stop'}).endswith('task 的 message 接着做')


def test_a_task_carried_on_by_a_later_one_points_to_it():
    assert handover.status_words({'state': 'RETURNED', 'feedback_state': 'DELIVERED'}, 'task-later') == \
        '后来接着做了一趟，以 task-later 那条为准'
    assert handover.status_words({'state': 'RUNNING'}, 'task-later') == '在跑'


