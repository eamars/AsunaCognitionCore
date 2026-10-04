#!/usr/bin/env python3
"""ADR-009 offline checks: no MongoDB, model or sandbox required.

Usage:
  python tools/adr009_offline_check.py              # every phase that has cases
  python tools/adr009_offline_check.py --phase P0   # one phase

Each phase is a standalone script ``tests/adr009_<phase>_cases.py`` (plus the
personal-data scanner cases for P0) printing ``PASS <id>`` / ``FAIL <id> <why>``.
Mongo, JS and sandbox tests run separately (pytest / npm run test:native).
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXTRA = {'p0': ['tests/adr009_scan_cases.py']}


def scripts(phase):
    found = sorted((ROOT / 'tests').glob(f'adr009_{phase}_cases.py'))
    return [*found, *[ROOT / p for p in EXTRA.get(phase, [])]]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--phase', help='P0..P7')
    args = parser.parse_args()
    phases = [args.phase.lower()] if args.phase else sorted({p.stem.split('_')[1] for p in (ROOT / 'tests').glob('adr009_p*_cases.py')})
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests'), os.environ.get('PYTHONPATH', '')]),
           'PYTHONIOENCODING': 'utf-8'}
    failed = total = 0
    for phase in phases:
        for script in scripts(phase):
            proc = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')
            rows = [line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL', 'SKIP'))]
            if not rows or proc.returncode:
                rows.append('FAIL %s did-not-run: %s' % (script.name, (proc.stderr.strip().splitlines() or ['?'])[-1]))
            for row in rows:
                print(phase.upper(), row)
            total += sum(1 for r in rows if r.startswith(('PASS', 'FAIL')))
            failed += sum(1 for r in rows if r.startswith('FAIL'))
    print('adr009-offline: %d/%d passed' % (total - failed, total))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
