"""The zero-dependency offline checks (tools/*_offline_check.py) are what the character runs in her sandbox before a
publish. Each runs here too, in its own process as she runs it, so none can fail unseen: a check pytest never runs
goes stale and still reads as green to whoever trusts it."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKS = sorted(path.name for path in (ROOT / 'tools').glob('*_offline_check.py'))


@pytest.mark.parametrize('check', CHECKS)
def test_the_offline_check_passes(check):
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONIOENCODING': 'utf-8'}
    done = subprocess.run([sys.executable, str(ROOT / 'tools' / check)], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding='utf-8', timeout=600)
    failed = [line for line in done.stdout.splitlines() if line.startswith('FAIL')]
    assert done.returncode == 0, '%s:\n%s\n%s' % (check, '\n'.join(failed) or done.stdout[-2000:], done.stderr[-2000:])
