"""Compatibility entry for the installed native DSH profile; stdlib only."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]   # the development checkout that holds the launcher

def ui(config_path, *, port=8780, profile=None):
    """Delegate to the launcher, which checks the profile was installed for this config."""
    args = ['node', str(ROOT / 'tools/asuna-launch.mjs'), 'ui', '--config', str(Path(config_path).resolve()),
            '--port', str(port)]
    if profile:
        args += ['--profile', profile]
    return subprocess.call(args, cwd=ROOT)
