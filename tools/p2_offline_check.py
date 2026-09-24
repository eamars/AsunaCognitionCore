#!/usr/bin/env python3
"""ADR-005 P2 离线自检：不需要 Mongo、不需要 pytest，直接跑摘要闭环那批用例。

用法：
  python3 tools/p2_offline_check.py                 # 跑当前工作树
  python3 tools/p2_offline_check.py --baseline      # 换成 P2 第一片（改动前）的基线再跑
  python3 tools/p2_offline_check.py --baseline p1c  # 换成 P1C 基线再跑
基线反证用来证明这批用例真的在测这次的改动，不是自说自话。
真实 Mongo 下的同一批结论由操作员在隔离宿主跑 tests/test_p2_summary_loop.py 复测。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINES = {'slice1': os.environ.get('P2_BASELINE', '/task/p2-slice1-baseline/src/asuna'),
             'p1c': os.environ.get('P1C_BASELINE', '/task/p1c-baseline/src/asuna')}
TARGETS = ('memory.py', 'context.py', 'dialogue_summary.py', 'memory_indexer.py')


def run_cases():
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'p2_summary_loop_cases.py')],
                          capture_output=True, text=True)
    print(proc.stdout, end='')
    if proc.stderr:
        print(proc.stderr, end='')
    rows = [line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL'))]
    failed = [line.split(' ', 1)[1] for line in rows if line.startswith('FAIL')]
    print('P2 离线自检：%d/%d 通过' % (len(rows) - len(failed), len(rows)))
    if failed:
        print('失败：' + ', '.join(failed))
    return 1 if failed or not rows else 0


def main():
    which = 'slice1'
    if '--baseline' in sys.argv:
        index = sys.argv.index('--baseline')
        if len(sys.argv) > index + 1 and sys.argv[index + 1] in BASELINES:
            which = sys.argv[index + 1]
    else:
        return run_cases()
    saved = {}
    try:
        for name in TARGETS:
            current = os.path.join(ROOT, 'src', 'asuna', name)
            saved[name] = open(current, encoding='utf-8').read()
            shutil.copyfile(os.path.join(BASELINES[which], name), current)
        print('（已换成 %s 基线的 %s）' % (which, '／'.join(TARGETS)))
        return run_cases()
    finally:
        for name, text in saved.items():
            with open(os.path.join(ROOT, 'src', 'asuna', name), 'w', encoding='utf-8') as handle:
                handle.write(text)
        print('（工作树已还原）')


if __name__ == '__main__':
    sys.exit(main())
