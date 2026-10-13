"""Words that point at real people and places, kept per deployment and never committed.

The character keeps the list herself (the `private_words` tool: add, remove, summary); the repository test, her skill
checks and the plugin packer refuse a committed or packed file that contains one. The list lives with the deployment's
data, never in the code: `<data>/private/personal-words.txt` (`ASUNA_PRIVATE_WORDS` names another file). A deployment
without one has nothing to check against, and every reader says so instead of passing.

One entry per line, `category|word|why`; blank lines and lines starting with `#` are ignored. Nothing here prints or
returns a listed word: a hit names its category and the entry's line number.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

CATEGORIES = {
    'person': '一个人的真名、群名片或网名',
    'group': '具体的群名',
    'account': 'QQ 号、群号或别的账号号码',
    'site': '设备或服务的站点 id',
    'host': '主机名或局域网地址',
    'email': '邮箱',
    'other': '别的能指到具体某人或某地的词',
}
MIN_LATIN = 3                 # an entry of Latin letters or digits only: at least this long, matched as a whole word
MIN_OTHER = 2                 # an entry with other characters (CJK): at least this long, matched where it appears
WHY_CHARS = 200
HEADER = ('# Words that point at real people and places in this deployment. Never commit this file.\n'
          '# One entry per line: category|word|why. Categories: ' + ', '.join(CATEGORIES) + '.\n')
_lock = threading.Lock()


class PrivateWordsError(ValueError):
    pass


def path():
    """The deployment's list: ASUNA_PRIVATE_WORDS, else <data>/private/personal-words.txt."""
    named = os.environ.get('ASUNA_PRIVATE_WORDS')
    if named:
        return Path(named)
    from .config import DATA
    return DATA / 'private' / 'personal-words.txt'


def parse(text):
    """[(line_number, category, word, why)] of the well-formed entries."""
    entries = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('|', 2)
        if len(parts) == 3 and parts[0].strip() in CATEGORIES and parts[1].strip():
            entries.append((number, parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return entries


def load(where=None):
    """The entries, or None when the deployment has no list."""
    target = Path(where) if where else path()
    if not target.is_file():
        return None
    return parse(target.read_text(encoding='utf-8'))


def _latin(word):
    return all(ch.isascii() for ch in word)


def problem(category, word, why):
    """Why an entry can't be kept, in words; None when it can."""
    if category not in CATEGORIES:
        return 'category 只能是：' + '、'.join('%s（%s）' % item for item in CATEGORIES.items())
    if not word or '|' in word or '\n' in word or word != word.strip():
        return 'word 要是一个词：不带竖线、不换行、前后没有空格'
    if _latin(word) and len(word) < MIN_LATIN:
        return '纯字母数字的词至少 %d 个字符，太短会把正常文字也拦下来' % MIN_LATIN
    if not _latin(word) and len(word) < MIN_OTHER:
        return '至少 %d 个字，一个字会把正常文字也拦下来' % MIN_OTHER
    if not why or not why.strip() or '\n' in why or len(why) > WHY_CHARS:
        return 'why 写一句为什么拦（一行，%d 字以内）：以后的人要靠它判断这条还该不该留' % WHY_CHARS
    return None


def pattern(word):
    """A Latin word matches as a whole word (case-insensitive); other text matches where it appears."""
    escaped = re.escape(word)
    if _latin(word):
        return re.compile(r'(?<![A-Za-z0-9_])' + escaped + r'(?![A-Za-z0-9_])', re.IGNORECASE)
    return re.compile(escaped)


def find(entries, text):
    """[(entry line number, category)] of the entries found in a text, each once."""
    return [(number, category) for number, category, word, _ in entries if pattern(word).search(text)]


def _write(target, entries_text):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(entries_text, encoding='utf-8')
    os.replace(temporary, target)


def add(category, word, why, home=True):
    """Keep an entry; the same word is kept once (at home its category and reason are replaced).

    Outside home a listed entry stays as it is and the answer is the same whether or not the word was listed:
    a conversation with others can neither learn from it what is on the list nor rewrite an entry."""
    category, word, why = str(category or '').strip(), str(word or '').strip(), str(why or '').strip()
    issue = problem(category, word, why)
    if issue:
        raise PrivateWordsError(issue)
    with _lock:
        target = path()
        lines = target.read_text(encoding='utf-8').splitlines() if target.is_file() else HEADER.splitlines()
        kept = [line for line in lines if not _same(line, word)]
        replaced = len(kept) != len(lines)
        if not (replaced and not home):
            kept.append('%s|%s|%s' % (category, word, why))
            _write(target, '\n'.join(kept) + '\n')
    if not home:
        return {'kept': True, 'category': category}
    return {'kept': True, 'replaced': replaced, 'category': category, 'line': len(kept)}


def remove(word):
    word = str(word or '').strip()
    with _lock:
        target = path()
        if not target.is_file():
            return {'removed': False, 'note': '这台机器上还没有名单'}
        lines = target.read_text(encoding='utf-8').splitlines()
        kept = [line for line in lines if not _same(line, word)]
        if len(kept) == len(lines):
            return {'removed': False, 'note': '名单里没有这一条（要逐字一致）'}
        _write(target, '\n'.join(kept) + '\n')
    return {'removed': True}


def summary():
    """How many entries per category; never the words."""
    entries = load()
    if entries is None:
        return {'configured': False, 'note': '这台机器上还没有名单；第一次 add 会建好它'}
    counts = {}
    for _, category, _, _ in entries:
        counts[category] = counts.get(category, 0) + 1
    return {'configured': True, 'entries': len(entries), 'by_category': counts}


def _same(line, word):
    parts = line.strip().split('|', 2)
    return len(parts) == 3 and parts[1].strip() == word


PRIVATE_WORDS_TOOL = {
    'name': 'private_words',
    'description': ('你的「别带出去」名单：能指到具体某个人或某个地方的词（真名、群名片、群名、QQ 号和群号、站点 id、'
                    '主机名和局域网地址、邮箱）。名单只在这台机器上，仓库的提交检查、技能自检和插件打包都拿它拦。'
                    'do=add 记一条（category、word、why 都写；同一个词再记就是改它）；remove 删一条（word 逐字一致）；'
                    'summary 看每类几条。名单上的词不再显示给你：命中只说哪一类、第几条。称呼词、你自己的名字、技术词不用记。'
                    '在家以外只能记新的。'),
    'parameters': {
        'op': {'type': 'string', 'enum': ['add', 'remove', 'summary'], 'description': 'add、remove 或 summary',
               'required': True},
        'category': {'type': 'string', 'enum': list(CATEGORIES),
                     'description': '; '.join('%s：%s' % item for item in CATEGORIES.items())},
        'word': {'type': 'string', 'description': '要拦的词，原样写'},
        'why': {'type': 'string', 'description': '一句为什么拦（%d 字以内）：以后的人靠它判断这条还该不该留' % WHY_CHARS},
    },
}


HOME_ONLY = '删一条只在家里做；在这里只能记新的。'


def run(args, home=True):
    """The tool, for either brain: what it did, never a listed word. Outside home (``home`` False) it only adds,
    and its answer does not tell whether the word was already listed."""
    args = args or {}
    op = args.get('op')
    if op == 'add':
        return add(args.get('category'), args.get('word'), args.get('why'), home=home)
    if op == 'remove':
        if not home:
            raise PrivateWordsError(HOME_ONLY)
        return remove(args.get('word'))
    if op == 'summary':
        return summary()
    raise PrivateWordsError('op 是 add、remove 或 summary')
