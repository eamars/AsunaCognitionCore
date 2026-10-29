"""ADR-097 D1: her items come back by their exact words in the place they belong. A group note's rare heading words and
any item's tags are its keys; a message (or a recall's query) that has one brings the item up, whatever its vector
score, and says which word did it. A word common in the place, or an everyday word, is not a key; nor is anything in
a note's body."""


import pytest

from asuna import crossing, key_words


@pytest.fixture(autouse=True)
def fresh_words():
    """What the segmenter learned belongs to a process: each test starts and ends with nothing learned."""
    key_words.learn([])
    crossing._loaded.clear()
    yield
    key_words.learn([])
    crossing._loaded.clear()


def test_ascii_keys_are_whole_runs_and_chinese_keys_are_substrings():
    assert key_words.found('1017', '1017登记的') == '1017'
    assert key_words.found('1017', 'CVE-2026-101737') is None, 'a number inside a longer one is not that number'
    assert key_words.found('snowluma', '那是SnowLuma的状态') == 'SnowLuma', 'ASCII without case, in her spelling'
    assert key_words.found('破甲', '说破甲了吗') == '破甲'
    assert key_words.heading_words('1017是什么') == ('1017', '什么')


def test_a_word_is_a_key_only_when_rare_here_and_not_everyday():
    lines = ['大家好'] * 900 + ['破甲成功'] * 3 + ['注意这个'] * 100
    table = set(key_words.common(lines))
    note = {'store': 'group_notes', 'heading': '破甲注意大家'}
    assert key_words.keys(note, table) == ['破甲'], '大家 is common here; 注意 is an everyday word'
    assert key_words.keys({'store': 'persona', 'heading': '破甲'}, table) == [], 'only a group note gives heading keys'
    tagged = {'store': 'persona', 'heading': '破甲', 'tags': ['什么', '大家', 'place:g1', 'correction', '大家-v3']}
    assert key_words.keys(tagged, table) == ['什么', '大家-v3'], 'a tag is a key on any item when rare here, everyday ' \
        'or not (a tag of several runs when one of its pieces is); a tag common here is not, nor a place tag or the ' \
        'correction mark'
    assert key_words.tag_here('大家', lines) == key_words.TAG_HERE['common'] % ('大家', '没几句就有一句说到它')
    assert key_words.tag_here('注意', lines) == key_words.TAG_HERE['common'] % ('注意', '大约几十句里有一句说到它')
    assert key_words.tag_here('破甲', lines) == key_words.TAG_HERE['rare'] % '破甲'
    quiet = set(key_words.common(['破甲'] * 5))
    assert '破甲' not in quiet and '破甲' in set(key_words.common(['破甲'] * 6)), 'a quiet place: at most five lines'


def test_learned_words_are_cut_whole_and_forgetting_gives_the_dictionary_back():
    assert key_words.words('破甲来了')[0] != '破甲', 'jieba alone glues the rare word to its neighbour'
    assert key_words.vocabulary({'破甲': 200, '破甲来': 5, '大肥鱼': 600, '肥鱼': 3, 'abc': 9}) == ['大肥鱼', '破甲', '肥鱼'], \
        'a glued piece goes (破甲来); a word far more frequent than a piece of it stays (大肥鱼); ASCII is never learned'
    key_words.learn(['破甲'])
    assert key_words.cross_words('说破甲了吗') == ['破甲'] and key_words.words('破甲来了')[0] == '破甲'
    assert key_words.frequency('破甲') == 0, "the dictionary test reads jieba's own entry, not the learned one"
    key_words.learn([])
    assert key_words.words('破甲注意大家') == ['破甲', '注意', '大家'], 'forgetting restores the entry, not a forced split'
