"""ADR-098 in her tools: what goes to the action brain expands what her place hands over and refuses a raw root, an
unknown name and `..` (D3); what she writes is kept contracted (D4); her words leave with no raw root, each
replacement counted and told to her weekly (D5); a placeholder is never a key word (D7)."""
import json
from pathlib import Path

import pytest

from asuna import key_words, local_roots

HOST = json.loads((Path(__file__).with_name('fixtures') / 'path_placeholders.json').read_text(encoding='utf-8'))
HOST = HOST['hosts']['windows']
WS, HOME = HOST['workspace'], HOST['home']


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', local_roots.build(HOST))
    monkeypatch.setattr(local_roots, 'REFUSED', None)


@pytest.fixture
def home(store, monkeypatch):
    """dm-a as the owner's own chat: its person is the owner."""
    monkeypatch.setitem(store.config['chat'], 'person_id', 'A')


def test_a_placeholder_is_not_a_word_she_said():
    assert key_words.words('看 ${ASUNA_HOME}/notes 和 ${ASUNA_WORKSPACE}') == ['看', 'notes', '和']
    assert 'workspace' not in key_words.cross_words('${ASUNA_WORKSPACE}\\docs\\x') and \
        'asuna' not in key_words.atoms('${ASUNA_WORKSPACE}\\docs')


def test_her_program_context_names_the_placeholders_never_their_values():
    for home in (True, False):
        line = local_roots.context_line(home)
        assert 'WORKSPACE' in line and '${ASUNA_' in line and WS not in line and HOME not in line
    assert '只有 ${ASUNA_WORKSPACE} 和 ${ASUNA_DATA}' in local_roots.context_line(False)


