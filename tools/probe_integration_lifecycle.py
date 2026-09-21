"""Crash an isolated diagnostic owner; verify real WSL service loses its parent."""
import json
import subprocess
import sys
import time
import uuid

from asuna.config import ROOT


def main():
    if sys.argv[1:] != ['--debug']:
        raise SystemExit('Explicit --debug required')
    root = ROOT/'.runtime/integration'/('crash-probe-'+uuid.uuid4().hex[:10])
    config = {'chat': {'scene_id': 'crash-probe', 'person_id': 'owner'},
              'integration': {'enabled': True, 'scene_id': 'crash-probe', 'person_id': 'owner', 'endpoints': []}}
    code = '''import json,sys,os
from asuna.integration import IntegrationRunner
r=IntegrationRunner(json.loads(sys.argv[1]),root=sys.argv[2])
script="from pathlib import Path\\nimport time\\nwhile True:\\n Path('/data/heartbeat').write_text(str(time.time()))\\n time.sleep(.05)\\n"
(r.dev/'service.py').write_text(script)
value=r.call('integration_start',{'argv':['python3','service.py']})
print(json.dumps(value),flush=True)
os._exit(0)
'''
    value = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, json.dumps(config), str(root)],
                           capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert value.returncode == 0, value.stderr
    started = json.loads(value.stdout)
    assert started['state'] == 'RUNNING', started
    time.sleep(2)
    heartbeat = root/'service-data/heartbeat'
    first = heartbeat.read_text()
    time.sleep(.5)
    assert heartbeat.read_text() == first, 'orphan integration still writes heartbeat'
    evidence = ROOT/'reports'/root.name/'result.json'; evidence.parent.mkdir(parents=True)
    result = {'status': 'PASS', 'probe': 'owner os._exit without cleanup', 'started': started,
              'heartbeat_stopped': True, 'root': str(root)}
    evidence.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'evidence': str(evidence)}))


if __name__ == '__main__':
    main()
