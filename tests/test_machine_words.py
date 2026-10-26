"""ADR-050, ADR-098: what a conversation outside home reads of a report holds nothing of the machine; a path is written
in the root table's one form, its tail kept, so an answer stays one."""
import json
from pathlib import Path

import pytest

from asuna import local_roots, machine_words

HOSTS = json.loads((Path(__file__).with_name('fixtures') / 'path_placeholders.json').read_text(encoding='utf-8'))['hosts']


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', local_roots.build(HOSTS['windows']))
    monkeypatch.setattr(local_roots, 'REFUSED', None)
    return HOSTS['windows']


def test_paths_are_written_with_the_tables_placeholders_and_keep_their_tails(windows):
    checkout = windows['workspace'] + '\\packages\\personas\\demo\\icon.png'
    data = windows['data'] + '\\channels\\qq-g\\out.txt'
    text = ('图在 %s，日志在 %s；另有 C:\\Users\\alice\\Desktop\\a.txt 和 D:/scratch/b.txt，'
            '\\\\nas\\share\\c.txt；产物 /task/out/f.png。' % (checkout, data))
    out = machine_words.text(text)
    assert out == ('图在 ${ASUNA_WORKSPACE}\\packages\\personas\\demo\\icon.png，日志在 ${ASUNA_DATA}\\channels\\qq-g\\out.txt；'
                   '另有 ${ASUNA_HOME}\\Desktop\\a.txt 和 ${ASUNA_DRIVE_D}/scratch/b.txt，${ASUNA_LOCAL_PATH}；'
                   '产物 /task/out/f.png。')
    assert '〔本机路径〕' not in out, 'one form everywhere: no second word for a hidden path'


def test_what_is_not_a_path_passes(windows):
    text = '见 https://example.org/a/b 和 http://127.0.0.1:8766/v1/x，发 /help，1/2 份，读写/执行，~/notes/a.md。'
    assert machine_words.text(text) == text


def test_a_traceback_is_one_line_naming_its_error_and_its_paths_go_with_it(windows):
    trace = ('跑失败了：\nTraceback (most recent call last):\n  File "C:\\Users\\alice\\x.py", line 3, in <module>\n'
             '    main()\nValueError: bad value in C:\\Users\\alice\\y.txt\n后面接着说。')
    out = machine_words.text(trace)
    assert out == '跑失败了：\n（程序出错：ValueError）\n后面接着说。'


def test_clean_walks_a_result_and_is_the_same_every_time(windows):
    value = {'text': 'C:\\Users\\alice\\a.txt', 'items': [{'path': 'D:\\b'}], 'n': 3}
    once = machine_words.clean(value)
    assert once == {'text': '${ASUNA_HOME}\\a.txt', 'items': [{'path': '${ASUNA_DRIVE_D}\\b'}], 'n': 3}
    assert machine_words.clean(once) == once
