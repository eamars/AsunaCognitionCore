#!/usr/bin/env python3
"""ADR-005 P5 离线自检：不需要 Mongo、不需要 pytest，直接跑话题追踪＋主动参与那批用例。

用法：
  python3 tools/p5_offline_check.py            # 跑当前工作树
  python3 tools/p5_offline_check.py --baseline # 换回 P4 基线（没有 proactive 模块）再跑
  python3 tools/p5_offline_check.py --hooks    # 只把 channels/context/chat 换回基线，模块留着
基线反证用来说明这批用例确实在测这次的改动：全基线下它们连导入都过不去，
只回退挂钩则钩住的那几条会红。真实 Mongo 那一层由操作员跑 tests/test_p5_proactive.py。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.environ.get('P5_BASELINE', '/task/p5-baseline/src/asuna')
SRC = os.path.join(ROOT, 'src', 'asuna')
HOOKS = ('channels.py', 'context.py', 'chat.py')
NEW = 'proactive.py'


def run_cases(label):
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'p5_proactive_cases.py')],
                          capture_output=True, text=True)
    print(proc.stdout, end='')
    rows = [line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL'))]
    failed = [line.split(' ', 1)[1] for line in rows if line.startswith('FAIL')]
    if not rows:
        print('%s：用例跑不起来——%s' % (label, (proc.stderr or '').strip().splitlines()[-1:]))
        return None
    print('%s：%d/%d 通过' % (label, len(rows) - len(failed), len(rows)))
    if failed:
        print('失败：' + ', '.join(failed))
    return failed


def main():
    mode = None
    for flag in ('--baseline', '--hooks'):
        if flag in sys.argv:
            mode = 'full' if flag == '--baseline' else 'hooks'
    if mode is None:
        failed = run_cases('P5 离线自检')
        return 1 if failed or failed is None else 0
    targets = list(HOOKS) + ([NEW] if mode == 'full' else [])
    saved = {}
    for name in targets:
        current = os.path.join(SRC, name)
        saved[name] = open(current, encoding='utf-8').read() if os.path.exists(current) else None
        source = os.path.join(BASELINE, name)
        if os.path.exists(source):
            shutil.copyfile(source, current)
        elif os.path.exists(current):
            os.remove(current)
    print('（已换成 P4 基线的 %s）' % '／'.join(targets))
    try:
        failed = run_cases('基线反证')
        if failed is None:
            print('→ 基线上这批用例连导入都过不去：它们依赖的确实是这次新增的模块与挂钩')
            return 0
        print('→ 基线上红的就是靠这次改动的用例：%s' % ', '.join(sorted(failed)))
        return 0
    finally:
        for name, text in saved.items():
            if text is None:
                path = os.path.join(SRC, name)
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(os.path.join(SRC, name), 'w', encoding='utf-8') as handle:
                    handle.write(text)
        print('（工作树已还原）')


if __name__ == '__main__':
    sys.exit(main())
