"""ADR-050: what a conversation outside home reads of a report holds nothing of the machine; an answer stays one."""
from asuna import machine_words
from asuna.config import DATA, ROOT


def test_paths_of_the_machine_are_hidden_and_paths_in_the_project_stay_answers():
    checkout = str(ROOT / 'packages' / 'personas' / 'demo' / 'icon.png')
    data = str(DATA / 'channels' / 'qq-g' / 'out.txt')
    text = ('图在 %s，日志在 %s；另有 C:\\Users\\someone\\Desktop\\a.txt 和 D:/scratch/b.txt，'
            '\\\\nas\\share\\c.txt，/home/someone/d.txt 与 /tmp/x/e.log；产物 /task/out/f.png。' % (checkout, data))
    out = machine_words.text(text)
    assert 'packages/personas/demo/icon.png' in out and checkout not in out, 'a file in the project is still named'
    assert 'channels/qq-g/out.txt' in out and data not in out
    assert out.count(machine_words.LOCAL_PATH) == 5
    for gone in ('someone', 'scratch', 'share', 'tmp'):
        assert gone not in out
    assert '/task/out/f.png' in out, "the action brain's own folder stays: she asks about its files by it"


def test_what_is_not_a_path_passes():
    text = '见 https://example.org/a/b 和 http://127.0.0.1:8766/v1/x，发 /help，1/2 份，读写/执行，~/notes/a.md。'
    assert machine_words.text(text) == text


def test_a_traceback_is_one_line_naming_its_error_and_its_paths_go_with_it():
    trace = ('跑失败了：\nTraceback (most recent call last):\n  File "C:\\Users\\someone\\x.py", line 3, in <module>\n'
             '    main()\nValueError: bad value in C:\\Users\\someone\\y.txt\n后面接着说。')
    out = machine_words.text(trace)
    assert out == '跑失败了：\n（程序出错：ValueError）\n后面接着说。'


def test_clean_walks_a_result_and_is_the_same_every_time():
    value = {'text': 'C:\\Users\\someone\\a.txt', 'items': [{'path': '/home/someone/b'}], 'n': 3}
    once = machine_words.clean(value)
    assert once == {'text': machine_words.LOCAL_PATH, 'items': [{'path': machine_words.LOCAL_PATH}], 'n': 3}
    assert machine_words.clean(once) == once
