"""Committed files carry no word from the deployment's private list (private_words.py), and the list itself works.

The list lives with the deployment's data and never in git. Without one there is nothing to check against: the scan is
skipped with its path named, so a run never reads as clean when it checked nothing. A hit names the file, line,
category and the entry's line number, never the word."""
import subprocess

import pytest

from asuna import private_words
from asuna.config import ROOT

TEXT_LIMIT = 2 * 1024 * 1024


def committed_texts():
    names = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout.split(b'\0')
    for raw in filter(None, names):
        path = ROOT / raw.decode('utf-8')
        if not path.is_file() or path.stat().st_size > TEXT_LIMIT:
            continue
        data = path.read_bytes()
        if b'\0' in data[:4096]:
            continue                                           # binary
        yield path, data.decode('utf-8', 'replace')


def test_no_committed_file_names_a_real_person_or_place():
    entries = private_words.load()
    if entries is None:
        pytest.skip('personal words not configured: %s (create it; the character keeps it with private_words)'
                    % private_words.path())
    hits = []
    for path, text in committed_texts():
        for number, line in enumerate(text.splitlines(), 1):
            for entry, category in private_words.find(entries, line):
                hits.append('%s:%d %s (entry line %d)' % (path.relative_to(ROOT).as_posix(), number, category, entry))
    assert not hits, 'committed files name what the private list keeps out:\n' + '\n'.join(hits[:50])


@pytest.fixture
def private_list(tmp_path, monkeypatch):
    target = tmp_path / 'private' / 'personal-words.txt'
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(target))
    return target


def test_the_list_keeps_entries_without_ever_showing_them(private_list):
    assert private_words.summary()['configured'] is False
    assert private_words.add('group', '示例测试群', 'a fixture group')['kept']
    assert private_words.add('account', '10001234', 'a fixture number')['line'] > 0
    assert private_words.add('group', '示例测试群', 'reworded')['replaced'] is True
    shown = repr([private_words.summary(), private_words.add('host', 'fixture-host', 'a fixture host')])
    assert '示例测试群' not in shown and '10001234' not in shown and 'fixture-host' not in shown
    assert private_words.summary() == {'configured': True, 'entries': 3, 'by_category': {'group': 1, 'account': 1, 'host': 1}}
    assert private_list.read_text(encoding='utf-8').startswith('# Words that point at real people')
    assert private_words.remove('10001234') == {'removed': True}
    assert private_words.remove('10001234')['removed'] is False


def test_matching_is_whole_word_for_latin_and_refuses_short_or_reasonless_entries(private_list):
    entries = private_words.parse('person|Alex|fixture\naccount|10001234|fixture\ngroup|示例群|fixture\n# note\nbad line\n')
    assert [category for _, category in private_words.find(entries, 'ask ALEX about it')] == ['person']
    assert private_words.find(entries, 'Alexander and alexa') == []
    assert private_words.find(entries, 'id 910001234 and 100012345') == []
    assert [category for _, category in private_words.find(entries, 'qq 10001234.')] == ['account']
    assert [category for _, category in private_words.find(entries, '在示例群里')] == ['group']
    for args in [('person', 'Al', 'too short'), ('person', '人', 'too short'), ('nobody', 'Alex', 'why'),
                 ('person', 'A|B', 'bar'), ('person', 'Alex', '')]:
        with pytest.raises(private_words.PrivateWordsError):
            private_words.add(*args)


def test_both_brains_have_the_tool_and_its_result_never_holds_the_word(private_list):
    from asuna import role_tools
    assert 'private_words' in role_tools.TOOLS
    result = private_words.run({'op': 'add', 'category': 'person', 'word': 'Fixturename', 'why': 'a fixture'})
    assert 'Fixturename' not in repr(result)
    with pytest.raises(private_words.PrivateWordsError):
        private_words.run({'op': 'list'})
