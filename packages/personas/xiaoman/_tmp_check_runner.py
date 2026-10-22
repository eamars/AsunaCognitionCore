import os
import subprocess
import sys

env = dict(os.environ, PYTHONPATH='src;tests')
offline = [
    ['tools/p2_offline_check.py'],
    ['tests/test_schedule_rules.py'],
    ['tools/p5_offline_check.py'],
    ['tools/outbound_image_offline_check.py'],
    ['tests/discussion_digest_cases.py'],
    ['-m', 'compileall', '-q', 'src/asuna', 'tests', 'tools'],
]
for c in offline:
    r = subprocess.run([sys.executable] + c, capture_output=True, text=True, env=env)
    out = (r.stdout or '').strip().splitlines()
    print('==', ' '.join(c), 'rc=', r.returncode)
    print('   last:', (out[-1][:220] if out else '(no stdout)'))
    if r.returncode:
        print('   stderr tail:', (r.stderr or '').strip()[-500:])
    sys.stdout.flush()
