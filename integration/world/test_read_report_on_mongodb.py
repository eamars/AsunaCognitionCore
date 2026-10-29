"""Reading a report on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): outside home a report
holds nothing of the machine, at home all of it."""

import pytest

from asuna import visibility
from asuna.tasks import TaskService

pytestmark = pytest.mark.world                # `store` is the fixture world


def report(lines=40, width=400):
    return ''.join('第 %02d 行：%s\n' % (n, '字' * width) for n in range(lines))


def task_row(store, text, scene='dm-a'):
    row = {'_id': 'task-long', 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': 1,
           'title': '照抄一份长文档', 'goal': '照抄', 'state': 'DONE', 'schema_version': 1, 'intent_revision': 1, 'result': {'task_id': 'task-long', 'text': text}}
    store.raw.tasks.insert_one(row)
    return row


def test_outside_home_a_report_holds_nothing_of_the_machine_and_at_home_all_of_it(store, monkeypatch):
    # ADR-050 (owner 2026-10-16, deterministic, in the program): 22 reports and 66 tool records handed back outside
    # home in a week held a local path, 82 a traceback. Outside home they read as words; a path keeps its tail under
    # the root table's placeholder (ADR-098) and one in the action brain's own folder stays; home and the stored
    # report are unchanged.
    import json
    from pathlib import Path
    from asuna import local_roots, machine_words
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane
    host = json.loads((Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'path_placeholders.json').read_text(encoding='utf-8'))
    host = host['hosts']['windows']
    monkeypatch.setattr(local_roots, 'TABLE', local_roots.build(host))
    found = host['workspace'] + '\\packages\\personas\\demo\\icon.png'
    text = ('图在 %s，草稿在 %s\\Desktop\\a.txt，产物 /task/out/f.png。\n'
            'Traceback (most recent call last):\n  File "%s\\x.py", line 3\nValueError: bad\n'
            % (found, host['home'], host['home']))
    task = task_row(store, text)
    service = object.__new__(TaskService)
    service.store = store
    outside = service._short_event(task, task, machine_words.clean)['trusted_context_events'][0]['report']
    assert '${ASUNA_WORKSPACE}\\packages\\personas\\demo\\icon.png' in outside and '/task/out/f.png' in outside
    assert host['user'] not in outside and '${ASUNA_HOME}\\Desktop' in outside and '（程序出错：ValueError）' in outside
    assert service._short_event(task, task)['trusted_context_events'][0]['report'] == text, 'home: as it is'
    tools = Coordinator(store, FakeLane(store, [])).tools
    group = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}
    assert host['user'] not in tools.tool_task_page(group, 'p1', {'task': 'task-long', 'page': 1})[0]['text']
    home = {**group, 'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    assert tools.tool_task_page(home, 'p2', {'task': 'task-long', 'page': 1})[0]['text'] == text
    assert store.raw.tasks.find_one({'_id': 'task-long'})['result']['text'] == text, 'the stored report is unchanged'
