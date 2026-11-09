#!/usr/bin/env python3
"""ADR-005 P5 离线自检：不需要 Mongo、不需要 pytest，直接跑话题追踪＋主动参与那批用例。

用法：python3 tools/p5_offline_check.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cases():
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'p5_proactive_cases.py')],
                          capture_output=True, text=True, encoding='utf-8')
    print(proc.stdout, end='')
    rows = [line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL'))]
    failed = [line.split(' ', 1)[1] for line in rows if line.startswith('FAIL')]
    if not rows:
        print('P5 离线自检：用例跑不起来——%s' % (proc.stderr or '').strip().splitlines()[-1:])
        return 1
    print('P5 离线自检：%d/%d 通过' % (len(rows) - len(failed), len(rows)))
    if failed:
        print('失败：' + ', '.join(failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(run_cases())
