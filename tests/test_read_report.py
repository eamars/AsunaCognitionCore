"""A report longer than a page reaches her as its first page; she turns the other pages herself from the stored report
(read_report) instead of asking the action brain to write it again. The tool is offered only when such a report is in
the turn."""
import pytest

from asuna import role_tools, visibility
from asuna.role_tools import Refused
from asuna.tasks import REPORT_CHARS, SHORT_REPORT_CHARS, TaskService, bounded_result, report_pages


def report(lines=40, width=400):
    return ''.join('第 %02d 行：%s\n' % (n, '字' * width) for n in range(lines))


def test_pages_end_at_a_line_break_and_together_are_the_report():
    text = report()
    pages = report_pages(text)
    assert len(pages) > 2 and ''.join(pages) == text
    assert all(len(page) <= REPORT_CHARS and page.endswith('\n') for page in pages)
    assert report_pages('短报告') == ['短报告']
    unbroken = '字' * (REPORT_CHARS * 2 + 5)
    assert [len(page) for page in report_pages(unbroken)] == [REPORT_CHARS, REPORT_CHARS, 5]


def test_the_hand_back_gives_the_first_page_and_says_how_to_turn_it():
    text = report()
    pages = report_pages(text)
    value = bounded_result({'task_id': 'task-1', 'text': text, 'artifact_refs': ['a', 'b']})
    assert value['text'].startswith(pages[0]) and value['report_pages'] == len(pages) and value['tool_records'] == 2
    assert '第 1/%d 页，原文 %d 字' % (len(pages), len(text)) in value['text']
    assert 'read_report：task 写 task-1，page=2' in value['text']
    short = bounded_result({'task_id': 'task-1', 'text': '短报告'})
    assert short['text'] == '短报告' and 'report_pages' not in short


def task_row(store, text, scene='dm-a'):
    row = {'_id': 'task-long', 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': 1,
           'title': '照抄一份长文档', 'goal': '照抄', 'state': 'DONE', 'schema_version': 1, 'intent_revision': 1, 'result': {'task_id': 'task-long', 'text': text}}
    store.db.tasks.insert_one(row)
    return row


def test_the_short_hand_back_points_to_the_pages_too(store):
    text = report()
    task = task_row(store, text)
    service = object.__new__(TaskService)
    service.store = store
    event = service._short_event(task, task)
    value = event['trusted_context_events'][0]
    assert len(value['report'].split('…（只给了开头')[0]) <= SHORT_REPORT_CHARS
    assert '原文 %d 字共 %d 页' % (len(text), len(report_pages(text))) in value['report']
    assert value['report_pages'] == len(report_pages(text))


def test_she_turns_the_pages_of_a_report_in_this_conversation(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    text = report()
    pages = report_pages(text)
    task_row(store, text)
    tools = Coordinator(store, FakeLane(store, [])).tools
    ep = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}
    second, _ = tools.tool_read_report(ep, 'c1', {'task': 'task-long', 'page': 2})
    assert second['text'] == pages[1] and second['page'] == '第 2/%d 页（原文 %d 字）' % (len(pages), len(text))
    assert second['more'] == 'page=3 接着读' and second['title'] == '照抄一份长文档'
    last, _ = tools.tool_read_report(ep, 'c2', {'task': 'task-long', 'page': len(pages)})
    assert last['more'] == '报告到这里完了'
    with pytest.raises(Refused, match='共 %d 页' % len(pages)):
        tools.tool_read_report(ep, 'c3', {'task': 'task-long', 'page': len(pages) + 1})
    elsewhere = {**ep, 'scene_id': 'g1', 'scope_key': 'scene:g1'}
    with pytest.raises(Refused, match='不是这个对话里的任务'):
        tools.tool_read_report(elsewhere, 'c4', {'task': 'task-long', 'page': 1})
    at_home = {**elsewhere, 'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    assert tools.tool_read_report(at_home, 'c6', {'task': 'task-long', 'page': 1})[0]['text'] == pages[0], \
        'at home every task of hers'
    with pytest.raises(Refused, match='不是你的任务'):
        tools.tool_read_report(at_home, 'c7', {'task': 'task-none', 'page': 1})
    with pytest.raises(Refused, match='只收 task 和 page'):
        tools.tool_read_report(ep, 'c5', {'task': 'task-long', 'page': 2, 'count': 3})


def test_the_tool_is_offered_only_when_a_long_report_is_in_the_turn():
    handed = {'event': {'trusted_context_events': [{'kind': 'task_result', 'value': {'text': '…', 'report_pages': 3}}]}}
    # the short version gives 3,000 characters: a report of one 6,000-character page is cut there too
    short_version = {'event': {'trusted_context_events': [{'kind': 'task_result', 'short': True, 'report_pages': 1}]}}
    listed = {'task_state_from_program': [{'_id': 'task-long', 'report': '报告 3 页（原文 15000 字）'}]}
    plain = {'event': {'trusted_context_events': [{'kind': 'task_result', 'value': {'text': '短报告'}}]},
             'task_state_from_program': [{'_id': 'task-1', 'status': '做完了'}]}
    assert role_tools.long_report(handed) and role_tools.long_report(short_version) and role_tools.long_report(listed)
    assert not role_tools.long_report(plain) and not role_tools.long_report({})


def test_the_turn_offers_read_report_only_with_a_long_report(store):
    turn = lambda context: role_tools.exposed(store, {
        '_id': 'ep-x', 'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'external',
        'manifest': {'session_class': visibility.PUBLIC}, 'context': context})
    assert 'read_report' in turn({'task_state_from_program': [{'_id': 'task-long', 'report': '报告 3 页'}]})
    assert 'read_report' not in turn({'task_state_from_program': [{'_id': 'task-1', 'status': '做完了'}]})


def test_a_turn_lists_the_long_report_and_offers_the_tool(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr009_p2 import owner
    owner(store)
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    def task(key, text):
        store.put('tasks', {'_id': 'task-' + key, 'scene_id': 'dm-a', 'scope_key': scene['scope_key'],
            'policy_epoch': scene['policy_epoch'], 'state': 'RETURNED', 'title': key, 'goal': key,
            'raw_input_refs': ['in-' + key], 'finished_at': '2026-10-10T00:00:00Z', 'request_key': 'task-' + key,
            'result': {'task_id': 'task-' + key, 'text': text}}, stream='task-' + key)
        store.put('messages', {'_id': 'in-' + key, 'received_at': '2026-10-10T00:00:00Z'}, stream='in-' + key)
    text = report()
    task('long', text)
    task('brief', '做完了。')
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '看看。'})], '嗯。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'n1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    rows = {row['_id']: row for row in ep['context']['task_state_from_program']}
    assert rows['task-long']['report'] == '报告 %d 页（原文 %d 字），交回来时只给了第一页；其余用 read_report 翻读' % (
        len(report_pages(text)), len(text))
    assert 'report' not in rows['task-brief']
    assert 'read_report' in lane.calls[0]['tools']


def test_a_page_ends_before_a_section_so_her_judgment_is_not_split():
    findings = '## 查到的\n' + ''.join('第 %02d 条：%s\n' % (n, '字' * 200) for n in range(24))
    judgment = '## 我的判断\n' + ''.join('判断 %d：%s\n' % (n, '断' * 200) for n in range(6))
    text = findings + judgment
    assert len(findings) < REPORT_CHARS < len(text)
    pages = report_pages(text)
    assert pages[0] == findings and pages[1].startswith('## 我的判断') and ''.join(pages) == text
    bold = report_pages('前言\n' + '字\n' * 2000 + '**结论：**\n' + '论\n' * 2000)
    assert bold[1].startswith('**结论：**')
