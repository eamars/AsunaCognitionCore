"""Compatibility entry for the installed native DSH profile; stdlib only."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get('ASUNA_DATA_ROOT', Path(__file__).resolve().parents[2])).resolve()

def ui(config_path, *, port=8780):
    settings = ROOT / '.runtime/adr008/launch.json'
    if not settings.exists():
        raise ValueError('Install the native profile using tools/setup_native_profile.py first')
    launch = json.loads(settings.read_text(encoding='utf-8'))
    if Path(launch['config']).resolve() != Path(config_path).resolve():
        raise ValueError('Native profile was installed for a different local configuration')
    return subprocess.call(['node', str(ROOT / 'tools/asuna-launch.mjs'), 'ui', '--port', str(port)], cwd=ROOT)
