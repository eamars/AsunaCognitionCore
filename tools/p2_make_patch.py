#!/usr/bin/env python3
"""生成 P2 第一片的可审阅 unified diff（改动的两个 src 文件 + 新增文件）。

用法：python3 tools/p2_make_patch.py [输出路径]，默认写 /task/P2_SUMMARY_LOOP.patch。
基线取 P1C 那份开发副本；输出可直接 patch -p1。
"""
import difflib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get('P2_BASELINE', '/task/p1c-baseline/src/asuna')
CONTEXT_BASE = os.environ.get('P2_CONTEXT_BASE', '/task/p2-baseline/context.P1C.py')
MODIFIED = [('src/asuna/memory.py', os.path.join(BASE, 'memory.py')),
            ('src/asuna/context.py', CONTEXT_BASE)]
ADDED = ['tests/p2_summary_loop_cases.py', 'tests/test_p2_summary_loop.py',
         'tools/p2_offline_check.py', 'tools/p2_apply_patch.py', 'tools/p2_make_patch.py',
         'docs/development_plans/ADR-005-asuna_qq_functional/P2_SUMMARY_LOOP_USAGE.md']


def read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read().splitlines(keepends=True)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else '/task/P2_SUMMARY_LOOP.patch'
    chunks = []
    for name, base in MODIFIED:
        chunks.append(''.join(difflib.unified_diff(read(base), read(os.path.join(ROOT, name)),
                                                   'a/' + name, 'b/' + name)))
    for name in ADDED:
        chunks.append(''.join(difflib.unified_diff([], read(os.path.join(ROOT, name)),
                                                   '/dev/null', 'b/' + name)))
    text = '\n'.join(chunks)
    with open(out, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print('wrote %s (%d bytes, %d hunks)' % (out, len(text), len(chunks)))


if __name__ == '__main__':
    main()
