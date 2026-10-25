"""The words that bring her items back by themselves (ADR-097): keys, a place's common words, and the segmenter.

An item's keys are the words of its tags and, for a group's notes, of its heading that are rare in the place a turn
is in; a heading word must also not be an everyday word. A word is rare in a place when at most RARE_SHARE of its recent lines contain it
(and never more than RARE_LINES lines in a quiet place): each place keeps the words its lines use more often than that
(`common`), so a key there is a heading word not in it. An everyday word is one the segmenter's dictionary rates at
EVERYDAY_FREQ or above. Chinese is cut into words by jieba with its own bundled dictionary, no model; ASCII letters and
digits count as whole runs without case, so 1017 inside 101737 is not 1017. A text contains a key when the key's
Chinese is a substring of it, with no ASCII letter or digit right beside the key's ASCII ends.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from functools import lru_cache

RARE_SHARE, RARE_LINES = 0.005, 5      # rare here: in at most 0.5% of the place's lines (5 lines in a quiet place)
EVERYDAY_FREQ = 500                    # a dictionary word this common is never a heading key (探针 64, 注意 9876)
KEYED_STORES = ('group_notes',)        # the stores whose headings give keys; every item's tags are keys
WINDOW_DAYS, WINDOW_LINES = 14, 10000  # the lines a place's table is counted over: its newest, at most this many
GRAMS = (2, 3, 4)                      # Chinese is counted as its substrings of these lengths
RUNS = re.compile(r'[一-鿿]+|[A-Za-z0-9]+')
_lock = threading.Lock()
_segmenter = None


def segmenter():
    """jieba, loaded once (its dictionary takes a fraction of a second), quiet."""
    global _segmenter
    if _segmenter is None:
        with _lock:
            if _segmenter is None:
                import warnings
                with warnings.catch_warnings():           # its source has escape sequences Python 3.12 warns about
                    warnings.simplefilter('ignore', SyntaxWarning)
                    import jieba
                jieba.setLogLevel(logging.WARNING)
                jieba.initialize()
                _segmenter = jieba
    return _segmenter


def words(text):
    """A text as words, in order: Chinese runs cut by the segmenter, ASCII runs whole and lower-cased."""
    out = []
    for run in RUNS.findall(text or ''):
        if run.isascii():
            out.append(run.lower())
        else:
            out.extend(word for word in segmenter().lcut(run) if word.strip())
    return out


@lru_cache(maxsize=4096)
def heading_words(heading):
    """The words of a heading that can be keys: two characters or more, each once, in order."""
    return tuple(dict.fromkeys(word for word in words(heading) if len(word) >= 2))


def everyday(word):
    """A Chinese word the segmenter's dictionary rates as everyday; ASCII runs never are."""
    return not word.isascii() and (segmenter().dt.FREQ.get(word) or 0) >= EVERYDAY_FREQ


def keys(item, table):
    """An item's keys in a place whose common atoms are `table`: its rare tags, then its rare, not everyday heading
    words."""
    out = [tag for tag in tag_keys(item.get('tags')) if rare(tag, table)]
    if item.get('store') in KEYED_STORES:
        out += [word for word in heading_words(item.get('heading') or '') if rare(word, table) and not everyday(word)]
    return list(dict.fromkeys(out))


def tag_keys(tags):
    """Her tags that are keys: free tags of two characters or more (a `place:` tag and the correction mark are not)."""
    out = []
    for tag in tags or ():
        tag = str(tag).strip()
        if len(tag) >= 2 and ':' not in tag and tag != 'correction':
            out.append(tag)
    return list(dict.fromkeys(out))


def atoms(line):
    """What a line is counted by: its ASCII runs and its Chinese substrings of GRAMS lengths."""
    out = set()
    for run in RUNS.findall(line or ''):
        if run.isascii():
            out.add(run.lower())
            continue
        for n in GRAMS:
            out.update(run[i:i + n] for i in range(len(run) - n + 1))
    return out


def limit(lines):
    """How many of the lines a rare word may be in."""
    return max(RARE_LINES, int(RARE_SHARE * lines))


def common(lines):
    """The atoms more of these lines contain than a rare word may be in, sorted: the place's table."""
    counts = Counter()
    for line in lines:
        counts.update(atoms(line))
    most = limit(len(lines))
    return sorted(atom for atom, n in counts.items() if n > most)


def rare(word, table):
    """Whether a word is rare in a place whose common atoms are `table` (a set). A word is in no more lines than any
    piece of it, so one longer than an atom, or a tag of several runs, is rare when one of its pieces is."""
    runs = RUNS.findall(word)
    if runs != [word]:
        return any(rare(run, table) for run in runs if len(run) >= 2) or not any(len(run) >= 2 for run in runs)
    if word.isascii() or len(word) <= GRAMS[-1]:
        return word.lower() not in table
    size = GRAMS[-1]
    return any(word[i:i + size] not in table for i in range(len(word) - size + 1))


@lru_cache(maxsize=4096)
def _pattern(key):
    left = r'(?<![A-Za-z0-9])' if key[:1].isascii() and key[:1].isalnum() else ''
    right = r'(?![A-Za-z0-9])' if key[-1:].isascii() and key[-1:].isalnum() else ''
    return re.compile(left + re.escape(key) + right, re.IGNORECASE)


def found(key, text):
    """The key as the text has it (its own spelling), or None."""
    match = _pattern(key).search(text or '')
    return match.group() if match else None


def lines_with(key, lines):
    """How many of the lines contain the key."""
    pattern = _pattern(key)
    return sum(1 for line in lines if pattern.search(line or ''))


# How often a tag of hers is said here, told when she sets it: a fact, never a judgment of her tag. A tag common here
# does not bring its section back here; the share says how common, so she can choose a rarer word.
TAG_HERE = {'never': '「%s」这里最近两周没人说过：有人说到它，就带出这一节',
            'rare': '「%s」这里最近两周少有人说：说到它就带出这一节',
            'common': '「%s」这里最近两周%s，太常见：在这里它不带出这一节；换一个这里少说的词才会带'}
SHARE_WORDS = ((0.02, '大约一两百句里有一句说到它'), (0.1, '大约几十句里有一句说到它'),
               (0.3, '差不多十句里就有一句说到它'), (None, '没几句就有一句说到它'))


def tag_here(tag, lines):
    """A tag's line in words: how often this place's recent lines say it, and whether it brings the section back."""
    n = lines_with(tag, lines)
    if n > limit(len(lines)):
        share = n / len(lines)
        return TAG_HERE['common'] % (tag, next(word for most, word in SHARE_WORDS if most is None or share <= most))
    return TAG_HERE['rare' if n else 'never'] % tag
