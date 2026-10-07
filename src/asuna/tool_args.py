"""What she plainly meant, before a tool checks its arguments (owner 2026-10-06).

Her tool errors were mostly shape, not intent: a list written as a string, "True" for true, a page or a
window larger than the tool serves. Where the intent is unambiguous the program takes it, clamps to the
tool's own bound and says so in the result (`adjusted`); where it is not, the tool refuses as before.
No bound is widened here: a clamp returns at most what the tool already allows.
"""
from __future__ import annotations

import ast
import json

# Each tool's own upper bounds (kept in step with the tools; a clamp never exceeds them).
DATABASE_PAGE = 50                 # development_database_read rows per call
HISTORY_WINDOW_DAYS = 90           # query_authorized_history window_days
INTEGRATION_TEST_SECONDS = 60      # integration_test timeout

ARGV_TOOLS = ('sandbox_run', 'development_run', 'integration_test', 'integration_start')
FLAG_FIELDS = ('overwrite',)


def as_list(value):
    """argv written as a string that holds a list: '["python3", "-c", "…"]' or "['python3', …]"."""
    if not isinstance(value, str):
        return value
    for parse in (json.loads, ast.literal_eval):
        try:
            parsed = parse(value)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
        if isinstance(parsed, (list, tuple)) and parsed and all(isinstance(item, str) for item in parsed):
            return list(parsed)
    raise ValueError('ARGV_NOT_A_LIST: argv 给的是一条字符串（%d 字），读不出列表；拆成字符串列表再跑，'
                     '例如 ["python3", "-c", "print(1)"]（不经过 shell，程序不替你按空格切）' % len(value))


def as_flag(value):
    if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
        return value.strip().lower() == 'true'
    return value


def normalize(tool, args):
    """(arguments as she meant them, notes on what the program changed)."""
    if not isinstance(args, dict):
        return args, []
    out, notes = dict(args), []
    if tool in ARGV_TOOLS and isinstance(out.get('argv'), str):
        out['argv'] = as_list(out['argv'])
        notes.append('argv 是写成字符串的列表，已按列表读')
    for field in FLAG_FIELDS:
        if isinstance(out.get(field), str):
            flag = as_flag(out[field])
            if isinstance(flag, bool):
                out[field] = flag
                notes.append('%s 按 %s 读' % (field, 'true' if flag else 'false'))
    if tool == 'development_database_read' and type(out.get('limit')) is int and out['limit'] > DATABASE_PAGE:
        notes.append('一次最多 %d 行，这次给前 %d 行；要更多用 skip 翻页' % (DATABASE_PAGE, DATABASE_PAGE))
        out['limit'] = DATABASE_PAGE
    if tool == 'query_authorized_history' and type(out.get('window_days')) is int \
            and out['window_days'] > HISTORY_WINDOW_DAYS:
        notes.append('window_days 最多 %d 天，按 %d 天查' % (HISTORY_WINDOW_DAYS, HISTORY_WINDOW_DAYS))
        out['window_days'] = HISTORY_WINDOW_DAYS
    if tool == 'integration_test' and type(out.get('timeout')) is int and out['timeout'] > INTEGRATION_TEST_SECONDS:
        notes.append('timeout 最多 %d 秒，按 %d 秒跑' % (INTEGRATION_TEST_SECONDS, INTEGRATION_TEST_SECONDS))
        out['timeout'] = INTEGRATION_TEST_SECONDS
    return out, notes
