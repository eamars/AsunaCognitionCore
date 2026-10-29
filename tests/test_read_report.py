"""A report longer than a page reaches her as its first page; she turns the other pages herself from the stored report
(task op page) instead of asking the action brain to write it again. The tool is in every turn of a conversation that
can hand work over; the report's own footer says when to use it."""

from asuna.tasks import (FIRST_PAGE_CHARS, FIRST_PAGE_MOST, RECORDS_TITLE, REPORT_CHARS, bounded_result,
                         key_observations, records_pages, report_pages)


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
    records = records_pages([{'tool': 'read_file', 'result_excerpt': 'a'}] * 3)
    value = bounded_result({'task_id': 'task-1', 'text': text}, records=records)
    pages = report_pages(text)
    assert value['report_pages'] == len(pages) + 1
    assert '后面：第 2 页「改了什么」' in value['text'] and '「%s（共 3 条' % RECORDS_TITLE in value['text']


def test_a_task_with_many_calls_has_its_records_on_pages_no_longer_than_the_reports():
    # B15: one page of every record ran to 154 records of up to 600 characters each, past what a tool result carries
    # inline; the records are paged like the report, every record still there.
    many = [{'tool': 'sandbox_run', 'result_excerpt': '%03d %s' % (n, '字' * 590)} for n in range(154)]
    pages = records_pages(many)
    assert len(pages) > 10 and all(len(page) <= REPORT_CHARS for page in pages)
    assert pages[0].startswith(RECORDS_TITLE + '（第 1–') and pages[-1].split('\n')[0].endswith('共 154 条，每条截到 600 字）')
    assert sum(page.count('\n- sandbox_run：') + page.startswith('- ') for page in pages) == 154
    assert records_pages([]) == [] and records_pages(many[:2])[0].startswith(RECORDS_TITLE + '（共 2 条')
    value = bounded_result({'task_id': 'task-1', 'text': '## 结论\n做成了。\n'}, records=pages)
    assert value['report_pages'] == 1 + len(pages) and '第 1/%d 页' % (1 + len(pages)) in value['text']


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


def test_a_page_ends_before_a_section_so_her_judgment_is_not_split():
    findings = '## 查到的\n' + ''.join('第 %02d 条：%s\n' % (n, '字' * 200) for n in range(24))
    judgment = '## 我的判断\n' + ''.join('判断 %d：%s\n' % (n, '断' * 200) for n in range(6))
    text = findings + judgment
    assert len(findings) < REPORT_CHARS < len(text)
    pages = report_pages(text, first=REPORT_CHARS, most=REPORT_CHARS)     # pages after the first: REPORT_CHARS each
    assert pages[0] == findings and pages[1].startswith('## 我的判断') and ''.join(pages) == text
    bold = report_pages('前言\n' + '字\n' * 2000 + '**结论：**\n' + '论\n' * 2000, first=REPORT_CHARS, most=REPORT_CHARS)
    assert bold[1].startswith('**结论：**')


