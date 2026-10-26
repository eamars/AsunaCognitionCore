"""What a conversation outside home reads of an action brain's report holds nothing of the machine (ADR-050, ADR-098).

A plain rewrite, the same input giving the same output, applied where a report or its tool records are shown in a
conversation that is not the owner's own (the hand-back, `task` op `page`, the answers to her questions); home and the
stored result are unchanged. It hides only what points at the machine or a person on it, never where a thing can be
found:

- a Python traceback becomes one line, 「（程序出错：<type>）」;
- a path is written with the root table's placeholder and its tail kept (`${ASUNA_WORKSPACE}/packages/...`,
  local_roots.py), the one form every reader of hers sees;
- a path in the action brain's own folder (`/task/...`) stays as it is.

Nothing is held back: what matches is replaced, everything else passes.
"""
from __future__ import annotations

import re

from . import local_roots

FAULT = '（程序出错：%s）'
FAULT_UNNAMED = '（程序出错）'

# A traceback: its header, then its indented frames, then the line naming the error.
_TRACEBACK = re.compile(r'Traceback \(most recent call last\):\n(?:[ \t]+[^\n]*\n|\n)*([^\s\n:][^\n]*)?')


def _fault(match):
    last = (match.group(1) or '').strip()
    kind = last.split(':', 1)[0].strip()
    return FAULT % kind if re.fullmatch(r'[A-Za-z_][\w.]*', kind or '') else FAULT_UNNAMED


def text(value: str) -> str:
    return local_roots.contract_text(_TRACEBACK.sub(_fault, value))[0]


def clean(value):
    """The same value with every string in it rewritten (dicts and lists walked; keys kept)."""
    if isinstance(value, str):
        return text(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
