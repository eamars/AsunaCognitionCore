"""A report longer than a page reaches her as its first page; she turns the other pages herself from the stored report
(task op page) instead of asking the action brain to write it again. The tool is in every turn of a conversation that
can hand work over; the report's own footer says when to use it."""
import pytest

from asuna import role_tools, visibility
from asuna.role_tools import Refused
from asuna.tasks import (FIRST_PAGE_CHARS, FIRST_PAGE_MOST, RECORDS_TITLE, REPORT_CHARS, TaskService, bounded_result,
                         key_observations, report_pages)


def report(lines=40, width=400):
    return ''.join('第 %02d 行：%s\n' % (n, '字' * width) for n in range(lines))


def test_pages_end_at_a_line_break_and_together_are_the_report():
    text = report()
    pages = report_pages(text)
    assert len(pages) > 2 and ''.join(pages) == text
    assert len(pages[0]) <= FIRST_PAGE_MOST and all(len(page) <= REPORT_CHARS for page in pages[1:])
    assert all(page.endswith('\n') for page in pages)
    assert report_pages('短报告') == ['短报告']
    assert report_pages('字' * FIRST_PAGE_MOST) == ['字' * FIRST_PAGE_MOST], 'up to the stretch, one page'
    unbroken = '字' * (FIRST_PAGE_CHARS + REPORT_CHARS + 5)
    assert [len(page) for page in report_pages(unbroken)] == [FIRST_PAGE_CHARS, REPORT_CHARS, 5]


def test_the_hand_back_gives_the_first_page_and_says_how_to_turn_it():
    text = '## 结论\n做成了。\n' + report(20, 200) + '## 过程\n' + report(20, 200)
    pages = report_pages(text)
    value = bounded_result({'task_id': 'task-1', 'text': text, 'artifact_refs': ['a', 'b']})
    assert value['text'].startswith(pages[0]) and value['report_pages'] == len(pages) and value['tool_records'] == 2
    assert '第 1/%d 页，原文 %d 字' % (len(pages), len(text)) in value['text']
    assert 'task 的 page：task 写 task-1，page=2' in value['text']
    short = bounded_result({'task_id': 'task-1', 'text': '短报告'})
    assert short['text'] == '短报告' and 'report_pages' not in short


def test_the_first_page_names_the_pages_after_it_and_the_tool_records_come_last():
    # Her answer (2026-10-21): she knows what she is concluding from, so the first page says what follows.
    text = '## 结论\n部分做成。\n' + '字\n' * 1200 + '## 改了什么\n' + '改\n' * 2000 + '## 没做到的\n' + '没\n' * 500
    value = bounded_result({'task_id': 'task-1', 'text': text}, records=3)
    pages = report_pages(text)
    assert value['report_pages'] == len(pages) + 1
    assert '后面：第 2 页「改了什么」' in value['text'] and '「%s」' % RECORDS_TITLE in value['text']


def test_the_first_page_stretches_to_the_next_section_or_the_end_of_a_table():
    # Her conditions (2026-10-21): about 2,000 characters, up to about 3,000 so the result or a table is not cut.
    head = '## 结论\n' + '字' * 300 + '\n'
    body = '## 结果\n' + '果\n' * 1100 + '## 过程\n' + '过\n' * 3000
    pages = report_pages(head + body)
    assert pages[0] == head + '## 结果\n' + '果\n' * 1100, 'cut at the next section, within the stretch'
    table = '| 列 | 值 |\n|---|---|\n' + ''.join('| 行%03d | %s |\n' % (n, '值' * 10) for n in range(80))
    text = '## 读数\n' + '字\n' * 600 + table + '## 后记\n' + '记\n' * 3000
    first = report_pages(text)[0]
    assert first.endswith(table) and len(first) <= FIRST_PAGE_MOST, 'the table ends the first page whole'
    long_table = '| 列 |\n' + ''.join('| %s |\n' % ('值' * 40) for n in range(200))
    text = '前言\n' + '字\n' * 600 + long_table
    first = report_pages(text)[0]
    assert first == '前言\n' + '字\n' * 600, 'a table too long for the stretch starts the next page'


def test_tool_records_on_the_first_page_only_for_a_task_that_changed_something():
    # Her answer: the risk is "it says it changed, and did not"; a read-only task's records are paged.
    read = [{'tool': 'read_file', 'result_excerpt': 'a'}, {'tool': 'sandbox_run', 'result_excerpt': 'b'}]
    assert key_observations(read) == []
    changed = read + [{'tool': 'development_write', 'result_excerpt': 'c'},
                      {'tool': 'development_run', 'result_excerpt': 'tests 12 passed'},
                      {'tool': 'development_publish', 'result_excerpt': 'ACTIVE'}]
    assert [item['tool'] for item in key_observations(changed)] == ['development_publish', 'development_run']
    wrote = [{'tool': 'write_file', 'result_excerpt': 'x'}, {'tool': 'write_file', 'result_excerpt': 'y'},
             {'tool': 'write_file', 'result_excerpt': 'z'}]
    assert [item['result_excerpt'] for item in key_observations(wrote)] == ['y', 'z']


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
    assert len(value['report'].split('…（只给了第一页')[0]) <= FIRST_PAGE_MOST
    assert '原文 %d 字共 %d 页' % (len(text), len(report_pages(text))) in value['report']
    assert value['report_pages'] == len(report_pages(text))


def test_the_hand_back_keeps_its_finish_time_utc_and_her_turn_shows_it_local_once(store):
    """The stored event keeps UTC; the turn localizes it once (localizing it here too showed it 13 hours late)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from asuna import local_time
    task = {**task_row(store, '短报告'), 'finished_at': '2026-10-14T01:28:00+00:00'}
    service = object.__new__(TaskService)
    service.store = store
    value = service._short_event(task, task)['trusted_context_events'][0]
    assert value['finished_at'] == '2026-10-14T01:28:00+00:00'
    shown = local_time.for_model(value, {'tz': ZoneInfo('Pacific/Auckland')}, now=datetime(2026, 10, 14, 2, tzinfo=timezone.utc))
    assert shown['finished_at'] == '10/14 14:28'


def test_she_turns_the_pages_of_a_report_in_this_conversation(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    text = report()
    pages = report_pages(text)
    task_row(store, text)
    tools = Coordinator(store, FakeLane(store, [])).tools
    ep = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}
    second, _ = tools.tool_task_page(ep, 'c1', {'task': 'task-long', 'page': 2})
    assert second['text'] == pages[1] and second['page'] == '第 2/%d 页（原文 %d 字）' % (len(pages), len(text))
    assert second['more'].startswith('page=3 接着读：「第') and second['title'] == '照抄一份长文档'
    last, _ = tools.tool_task_page(ep, 'c2', {'task': 'task-long', 'page': len(pages)})
    assert last['more'] == '报告到这里完了'
    with pytest.raises(Refused, match='共 %d 页' % len(pages)):
        tools.tool_task_page(ep, 'c3', {'task': 'task-long', 'page': len(pages) + 1})
    elsewhere = {**ep, 'scene_id': 'g1', 'scope_key': 'scene:g1'}
    with pytest.raises(Refused, match='不是这个对话里的任务'):
        tools.tool_task_page(elsewhere, 'c4', {'task': 'task-long', 'page': 1})
    at_home = {**elsewhere, 'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    assert tools.tool_task_page(at_home, 'c6', {'task': 'task-long', 'page': 1})[0]['text'] == pages[0], \
        'at home every task of hers'
    with pytest.raises(Refused, match='不是你的任务'):
        tools.tool_task_page(at_home, 'c7', {'task': 'task-none', 'page': 1})
    with pytest.raises(Refused, match='只收 task 和 page'):
        tools.tool_task_page(ep, 'c5', {'task': 'task-long', 'page': 2, 'count': 3})


def test_task_page_is_in_every_turn_that_can_hand_work_over(store):
    from test_adr009_p2 import owner
    owner(store)
    turn = lambda context: role_tools.exposed(store, {
        '_id': 'ep-x', 'scene_id': 'dm-a', 'person_id': 'A', 'episode_kind': 'external',
        'manifest': {'session_class': visibility.OWNER_PRIVATE}, 'context': context})
    assert 'task.page' in turn({'task_state_from_program': [{'_id': 'task-long', 'report': '报告 3 页'}]})
    assert 'task.page' in turn({'task_state_from_program': [{'_id': 'task-1', 'status': '做完了'}]})


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
    assert rows['task-long']['report'] == '报告 %d 页（原文 %d 字），交回来时只给了第一页；其余用 task 的 page 翻读' % (
        len(report_pages(text)), len(text))
    assert 'report' not in rows['task-brief']
    assert 'task' in lane.calls[0]['tools']


def test_a_page_ends_before_a_section_so_her_judgment_is_not_split():
    findings = '## 查到的\n' + ''.join('第 %02d 条：%s\n' % (n, '字' * 200) for n in range(24))
    judgment = '## 我的判断\n' + ''.join('判断 %d：%s\n' % (n, '断' * 200) for n in range(6))
    text = findings + judgment
    assert len(findings) < REPORT_CHARS < len(text)
    pages = report_pages(text, first=REPORT_CHARS, most=REPORT_CHARS)     # pages after the first: REPORT_CHARS each
    assert pages[0] == findings and pages[1].startswith('## 我的判断') and ''.join(pages) == text
    bold = report_pages('前言\n' + '字\n' * 2000 + '**结论：**\n' + '论\n' * 2000, first=REPORT_CHARS, most=REPORT_CHARS)
    assert bold[1].startswith('**结论：**')


def test_outside_home_a_report_holds_nothing_of_the_machine_and_at_home_all_of_it(store):
    # ADR-050 (owner 2026-10-16, deterministic, in the program): 22 reports and 66 tool records handed back outside
    # home in a week held a local path, 82 a traceback. Outside home they read as words; a path in the project and
    # one in the action brain's own folder stay answers; home and the stored report are unchanged.
    from asuna import machine_words
    from asuna.config import ROOT
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    found = str(ROOT / 'packages' / 'personas' / 'demo' / 'icon.png')
    text = ('图在 %s，草稿在 C:\\Users\\someone\\Desktop\\a.txt，产物 /task/out/f.png。\n'
            'Traceback (most recent call last):\n  File "C:\\Users\\someone\\x.py", line 3\nValueError: bad\n' % found)
    task = task_row(store, text)
    service = object.__new__(TaskService)
    service.store = store
    outside = service._short_event(task, task, machine_words.clean)['trusted_context_events'][0]['report']
    assert 'packages/personas/demo/icon.png' in outside and '/task/out/f.png' in outside
    assert 'someone' not in outside and machine_words.LOCAL_PATH in outside and '（程序出错：ValueError）' in outside
    assert service._short_event(task, task)['trusted_context_events'][0]['report'] == text, 'home: as it is'
    tools = Coordinator(store, FakeLane(store, [])).tools
    group = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}
    assert 'someone' not in tools.tool_task_page(group, 'p1', {'task': 'task-long', 'page': 1})[0]['text']
    home = {**group, 'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    assert tools.tool_task_page(home, 'p2', {'task': 'task-long', 'page': 1})[0]['text'] == text
    assert store.db.tasks.find_one({'_id': 'task-long'})['result']['text'] == text, 'the stored report is unchanged'
