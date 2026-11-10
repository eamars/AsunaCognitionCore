"""ADR-119 F7 (c): the private list has one Python reader (asuna.private_words) and one copy the plugin keeps in
JavaScript (packages/cognition-core/src/private-words.js, which cannot import Python). Both are held to one table,
tests/fixtures/private_words_cases.json; its JS twin is packages/cognition-core/test/private-words.test.js."""
import json

from asuna import private_words
from asuna.config import ROOT

CASES = json.loads((ROOT / 'tests/fixtures/private_words_cases.json').read_text(encoding='utf-8'))


def test_the_list_parses_to_the_table_s_entries():
    assert [list(entry[:3]) for entry in private_words.parse(CASES['list'])] == CASES['entries']


def test_each_word_matches_where_the_table_says():
    for case in CASES['matches']:
        assert bool(private_words.pattern(case['word']).search(case['text'])) is case['hit'], case
