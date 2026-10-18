"""Every tool her character brain has gets its own row on the page (client.js), with a title in both languages. A
tool without one fell back to DSH's generic card showing the raw call; 16 of 30 had none until 2026-10-18. The vault's
row shows the name and never the values she was given to keep."""
import re

from asuna import role_tools
from asuna.config import ROOT

# DSH draws these rows itself; registering a second row under the same name stops the plugin from starting.
DSH_ROWS = {'read_image'}
CLIENT = (ROOT / 'packages' / 'cognition-core' / 'src' / 'client.js').read_text(encoding='utf-8')


def table(name):
    body = re.search(r'const %s = \{(.*?)\};' % name, CLIENT, re.S).group(1)
    return dict(re.findall(r"(\w+): '([^']*)'", body))


def test_every_tool_she_has_has_a_row_and_a_title_in_both_languages():
    rows = table('TOOL_ICONS')
    missing = sorted(set(role_tools.TOOLS) - set(rows) - DSH_ROWS)
    assert not DSH_ROWS & set(rows), 'a row under a name DSH draws itself: the plugin would not start'
    assert not missing, 'tools with no row of their own (they show raw JSON): %s' % missing
    titles = {name: CLIENT.count("'tool.%s':" % name) for name in set(role_tools.TOOLS) - DSH_ROWS}
    assert all(count == 2 for count in titles.values()), {n: c for n, c in titles.items() if c != 2}


def test_the_vault_row_never_reads_her_values():
    assert table('TOOL_SUMMARY')['credential'] == 'name'
    assert 'credential' not in table('TOOL_BODY')
    assert table('TOOL_SUMMARY')['private_words'] == 'category' and 'private_words' not in table('TOOL_BODY')


def test_her_words_in_a_tool_read_as_reasoning_and_her_speech_as_speech():
    assert "variant: 'compact'" in CLIENT, "a tool's body reads as DSH reads reasoning"
    assert "name === 'speak' && parts?.length" in CLIENT
