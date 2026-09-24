"""ADR-005 P3 交付前自检：零依赖跑法，操作员不必起 Mongo、不必起 DSH、不必联网。

三件事：
1) 语法与导入面：src/asuna 全部能编译，schedule_rules 只用标准库；
2) 真用例：tests/p3_schedule_cases.py（假集合＋假原生 lane 真算，含 DST 的确定性例子）；
3) 反证：把同一批用例对着**改动前**的 schedule.py/coordinator.py 再跑一遍，必须看到它们变红——
   不然这套用例只是在自我确认，证明不了 P3 那几条行为真的存在。

跑法：python3 tools/p3_offline_check.py [基线目录]
基线目录默认 /task/p3-baseline（本次补丁的 before 侧）；找不到就跳过反证并说明。
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = sys.argv[1] if len(sys.argv) > 1 else '/task/p3-baseline'
MUST_FAIL_ON_BASELINE = (
    'create_daily_registers_one_native_single_shot',      # 每日钟点：旧代码只认 after/every
    'update_keeps_one_plan_and_one_live_native',          # 改期：旧代码根本没有 update
    'stale_dispatch_after_update_does_not_act',
    'decide_schema_accepts_the_four_timings',             # DECIDE 形状：旧 schema 不认 at/clock
    'hooks_are_wired_in_context_and_coordinator',         # 投影与控制面接线
)
STDLIB_ONLY = ('json', 'datetime', 'zoneinfo', 're')


def run(env_extra=None):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, 'tests'), **(env_extra or {}))
    done = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'p3_schedule_cases.py')],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    rows = [line.split(' ', 2) for line in done.stdout.splitlines() if line.startswith(('PASS ', 'FAIL '))]
    return done.returncode, [(row[1], row[0] == 'PASS') for row in rows], done.stdout, done.stderr


def compile_all():
    done = subprocess.run([sys.executable, '-m', 'compileall', '-q',
                           os.path.join(ROOT, 'src', 'asuna'), os.path.join(ROOT, 'tests'),
                           os.path.join(ROOT, 'tools')], cwd=ROOT, capture_output=True, text=True)
    return done.returncode == 0, (done.stdout + done.stderr)[-400:]


def rules_are_stdlib_only():
    source = open(os.path.join(ROOT, 'src', 'asuna', 'schedule_rules.py'), encoding='utf-8').read()
    imports = [line.strip() for line in source.splitlines()
               if line.strip().startswith(('import ', 'from ')) and 'import' in line]
    bad = [line for line in imports
           if line.split()[1].split('.')[0] not in STDLIB_ONLY and not line.startswith('from __future__')]
    return not bad, bad


def main():
    report = []
    ok, tail = compile_all()
    report.append(('全部源文件能编译', ok, tail))
    ok, bad = rules_are_stdlib_only()
    report.append(('schedule_rules 只用标准库（离线自测不靠第三方）', ok, bad))
    code, rows, _out, err = run()
    passed = [name for name, flag in rows if flag]
    failed = [name for name, flag in rows if not flag]
    report.append(('离线用例全绿（%d/%d）' % (len(passed), len(rows)), code == 0, failed or err[-300:]))

    baseline_src = os.path.join(BASELINE, 'src', 'asuna')
    if not os.path.isdir(baseline_src):
        report.append(('基线反证跳过（找不到 %s）' % baseline_src, True, ''))
    else:
        scratch = tempfile.mkdtemp(prefix='p3-baseline-')
        try:
            # A：基线驱动 + 新换算模块。红就该红在驱动、接线与 schema 上，不是红在"文件不存在"。
            target = os.path.join(scratch, 'withRules', 'asuna')
            shutil.copytree(baseline_src, target)
            shutil.copyfile(os.path.join(ROOT, 'src', 'asuna', 'schedule_rules.py'),
                            os.path.join(target, 'schedule_rules.py'))
            code, rows, _out, _err = run({'ASUNA_P3_SRC': target})
            red = {name for name, flag in rows if not flag}
            missing = [name for name in MUST_FAIL_ON_BASELINE if name not in red]
            report.append(('反证 A：基线驱动上 %d 条用例变红（驱动/接线/schema 确实是新行为）' % len(red),
                           code != 0 and not missing, '基线上竟然还过：' + str(missing)))
            # B：纯基线。全红——换算模块在 P3 之前不存在，说明这不是把旧代码换个名字。
            plain = os.path.join(scratch, 'plain', 'asuna')
            shutil.copytree(baseline_src, plain)
            code, rows, _out, _err = run({'ASUNA_P3_SRC': plain})
            red = [name for name, flag in rows if not flag]
            report.append(('反证 B：纯基线上 %d/%d 条变红（换算模块本身是新增）' % (len(red), len(rows)),
                           code != 0 and len(red) == len(rows), '纯基线上竟然有过的：'
                           + str([name for name, flag in rows if flag])))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    bad = 0
    for name, ok, detail in report:
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else '  → ' + str(detail)[:300]))
        bad += 0 if ok else 1
    print('P3 自检：%s' % ('可以出补丁' if not bad else '%d 项不合格' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
