"""Explicit noninteractive diagnostic: real WSL namespaces, no models or QQ."""
import json
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
import uuid

from asuna.config import ROOT


def linux(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def main():
    if sys.argv[1:] != ['--debug']:
        raise SystemExit('Explicit --debug required')
    directory = ROOT / 'reports' / ('integration-transport-' + uuid.uuid4().hex[:10])
    directory.mkdir(parents=True)
    (directory / 'data').mkdir()
    (directory / 'config.json').write_text('{}', encoding='utf-8')
    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.sendall(b'authorized:' + self.request.recv(100))
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Echo) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        code = '''import socket,json,pathlib,os
s=socket.create_connection(('127.0.0.1',18080),timeout=3);s.sendall(b'probe');reply=s.recv(100).decode();s.close()
denied=False
try:socket.create_connection(('127.0.0.1',PORT),timeout=1)
except OSError:denied=True
print(json.dumps({'reply':reply,'direct_network_denied':denied,'owner_home_hidden':not pathlib.Path('/home').exists(),'host_mount_hidden':not pathlib.Path('/mnt/c').exists(),'uid':os.getuid()}))
'''.replace('PORT', str(port))
        spec = {'argv': ['python3', '-c', code], 'snapshot': linux(directory), 'data': linux(directory/'data'),
                'config': linux(directory/'config.json'), 'endpoints': [{'name': 'probe', 'host': '127.0.0.1', 'target_port': port, 'port': 18080}]}
        process = subprocess.Popen(['wsl', '-d', 'Ubuntu', '--exec', 'python3', linux(ROOT/'src/asuna/integration_worker.py')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        process.stdin.write(json.dumps(spec)+'\n');process.stdin.flush()
        records = []
        try:
            for line in process.stdout:
                records.append(json.loads(line))
            process.wait(15)
        finally:
            process.stdin.close()
            server.shutdown()
        logs = ''.join(row.get('text','') for row in records if row.get('stream')=='stdout')
        value = json.loads(logs)
        assert value['reply']=='authorized:probe' and value['direct_network_denied'] and value['owner_home_hidden'] and value['host_mount_hidden'] and value['uid']!=0, records
        assert records[-1]=={'type':'exit','exit_code':0}, records
        (directory/'result.json').write_text(json.dumps({'records':records,'observed':value},indent=2),encoding='utf-8')
        print(json.dumps({'status':'PASS','evidence':str(directory/'result.json'),'observed':value}))


if __name__ == '__main__':
    main()
