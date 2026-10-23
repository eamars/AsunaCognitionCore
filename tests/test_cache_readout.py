"""The agents' cache readout: its self-test on synthetic sessions (counts once, triggers, masking) passes."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents' / 'skills' / 'asuna-cache-readout' / 'cache_readout.py'


def test_cache_readout_selftest():
    done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--selftest'], capture_output=True, text=True,
                          encoding='utf-8', timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
