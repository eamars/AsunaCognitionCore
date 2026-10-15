"""What a conversation outside home reads of an action brain's report holds nothing of the machine (ADR-050).

A plain rewrite, the same input giving the same output, applied where a report or its tool records are shown in a
conversation that is not the owner's own (the hand-back, `task` op `page`, the answers to her questions); home and the
stored result are unchanged. It hides only what points at the machine or a person on it, never where a thing can be
found:

- a Python traceback becomes one line, 「（程序出错：<type>）」;
- an absolute path inside the checkout or the data folder becomes its path from there (an answer stays an answer);
- a path in the action brain's own folder (`/task/...`) stays as it is;
- any other absolute path, judged by its shape (a drive letter, a share, a POSIX path of two or more parts), becomes
  「〔本机路径〕」, nothing of it kept.

Nothing is held back: what matches is replaced, everything else passes.
"""
from __future__ import annotations

import re
from pathlib import PureWindowsPath

from .config import DATA, ROOT

LOCAL_PATH = '〔本机路径〕'
FAULT = '（程序出错：%s）'
FAULT_UNNAMED = '（程序出错）'
SANDBOX = '/task'

_STOP = r'\s"\'<>|*?`()（）「」『』【】，。；：、！？,;'
# A traceback: its header, then its indented frames, then the line naming the error.
_TRACEBACK = re.compile(r'Traceback \(most recent call last\):\n(?:[ \t]+[^\n]*\n|\n)*([^\s\n:][^\n]*)?')
_WINDOWS = re.compile(r'(?<![\w/\\])(?:[A-Za-z]:[\\/]|\\\\[^\\/' + _STOP + r']+[\\/])[^' + _STOP + r']*')
_POSIX = re.compile(r'(?<![\w.:/\\~])/[^/' + _STOP + r']+(?:/[^/' + _STOP + r']*)+')


def _path(match):
    path = match.group(0)
    if path == SANDBOX or path.startswith(SANDBOX + '/'):
        return path
    plain = path.replace('\\', '/')
    # The checkout names a path from itself (its data folder too, when inside it); a data folder elsewhere by its name.
    for root, name in ((ROOT, ''), (DATA, DATA.name + '/')):
        base = str(root).replace('\\', '/').rstrip('/').lower() + '/'
        if plain.lower().startswith(base):
            return name + plain[len(base):]
    return LOCAL_PATH


def _fault(match):
    last = (match.group(1) or '').strip()
    kind = last.split(':', 1)[0].strip()
    return FAULT % kind if re.fullmatch(r'[A-Za-z_][\w.]*', kind or '') else FAULT_UNNAMED


def text(value: str) -> str:
    value = _TRACEBACK.sub(_fault, value)
    value = _WINDOWS.sub(_path, value)
    return _POSIX.sub(_path, value)


def clean(value):
    """The same value with every string in it rewritten (dicts and lists walked; keys kept)."""
    if isinstance(value, str):
        return text(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
