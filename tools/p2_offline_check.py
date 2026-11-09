#!/usr/bin/env python3
"""ADR-005 P2 离线自检：不需要 Mongo、不需要 pytest，直接跑摘要闭环那批用例。

用法：python3 tools/p2_offline_check.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cases():
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'p2_summary_loop_cases.py')],
                          capture_output=True, text=True, encoding='utf-8')
    print(proc.stdout, end='')
    if proc.stderr:
        print(proc.stderr, end='')
    rows = [line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL'))]
    failed = [line.split(' ', 1)[1] for line in rows if line.startswith('FAIL')]
    print('P2 离线自检：%d/%d 通过' % (len(rows) - len(failed), len(rows)))
    if failed:
        print('失败：' + ', '.join(failed))
    return 1 if failed or not rows else 0


if __name__ == '__main__':
    sys.exit(run_cases())
