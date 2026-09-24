#!/usr/bin/env python3
"""生成 P3 审阅用 patch：旧内容一律取自 /task/p3-baseline 那份快照，不靠回忆拼。

那份快照 = P4 交付状态的工作树（交付前用 cp -a 复制，并 diff -rq 对过零差异）。
快照里没有的文件按新建给整篇；改过的文件按 unified diff 给 hunk。
"""
import difflib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get('P3_BASELINE_ROOT', '/task/p3-baseline')
DOC = 'docs/development_plans/ADR-005-asuna_qq_functional'
PATHS = ('src/asuna/schedule_rules.py', 'src/asuna/schedule.py', 'src/asuna/context.py',
         'src/asuna/coordinator.py', 'tests/p3_schedule_cases.py', 'tests/test_p3_schedule.py',
         'tools/p3_offline_check.py', 'tools/p3_make_patch.py', 'tools/p3_apply_patch.py',
         '%s/P3_NL_SCHEDULE_USAGE.md' % DOC)


def read(path):
    return io.open(path, encoding='utf-8').read().splitlines(True)


def main():
    out, created, changed = [], [], []
    for name in PATHS:
        before_path = os.path.join(BASE, name)
        before = read(before_path) if os.path.exists(before_path) else []
        after = read(os.path.join(ROOT, name))
        if before == after:
            continue
        (created if not before else changed).append(name)
        out.append(''.join(difflib.unified_diff(
            before, after, fromfile=('/dev/null' if not before else 'a/%s\t(p3-baseline)' % name),
            tofile='b/%s' % name, lineterm='\n')))
    body = ''.join(out)
    target = sys.argv[1] if len(sys.argv) > 1 else '/task/P3_NL_SCHEDULE.patch'
    io.open(target, 'w', encoding='utf-8').write(body)
    print('%s：%d 行；改 %d 个，新建 %d 个' % (
        target, len(body.splitlines()), len(changed), len(created)))
    for name in changed + created:
        print('   ', name)


if __name__ == '__main__':
    main()
