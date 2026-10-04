"""Compatibility entry for the installed native DSH profile; stdlib only."""
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get('ASUNA_DATA_ROOT', Path(__file__).resolve().parents[2])).resolve()

def ui(config_path, *, port=8780, profile=None):
    """Delegate to the launcher, which checks the profile was installed for this config."""
    args = ['node', str(ROOT / 'tools/asuna-launch.mjs'), 'ui', '--config', str(Path(config_path).resolve()),
            '--port', str(port)]
    if profile:
        args += ['--profile', profile]
    return subprocess.call(args, cwd=ROOT)
