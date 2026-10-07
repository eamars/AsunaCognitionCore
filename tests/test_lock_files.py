"""The lock files match what the project declares. A fresh install (a container clone, ADR-019) installs exactly the
locks: an entry missing from one broke two deployments on 2026-10-07 (npm workspaces, then tzdata in uv.lock)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from asuna.config import ROOT


def test_every_npm_workspace_is_in_the_lock():
    lock = json.loads((ROOT / 'package-lock.json').read_text(encoding='utf-8'))['packages']
    patterns = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['workspaces']
    workspaces = {path.parent.relative_to(ROOT).as_posix() for pattern in patterns for path in ROOT.glob(pattern + '/package.json')}
    assert {'packages/cognition-core', 'packages/channels/napcat-qq'} <= workspaces
    missing = sorted(workspace for workspace in workspaces if workspace not in lock)
    assert not missing, 'run npm install --package-lock-only: %s' % missing


def _uv():
    local = Path(sys.executable).with_name('uv.exe' if sys.platform == 'win32' else 'uv')
    return str(local) if local.exists() else shutil.which('uv')


@pytest.mark.skipif(not _uv(), reason='uv is not installed here')
def test_uv_lock_matches_pyproject():
    result = subprocess.run([_uv(), 'lock', '--check'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, 'run uv lock: ' + (result.stderr or result.stdout)[-400:]
