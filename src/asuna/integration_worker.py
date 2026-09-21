"""Trusted WSL supervisor and namespace bootstrap. Invoked only by IntegrationRunner.

The outer process owns fixed-destination Unix relays. The inner process has a
private network namespace and can reach only the explicitly mounted relays.
No model-supplied shell command is evaluated by the outer process.
"""
import json
import os
from pathlib import Path
import select
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading


def pump(left, right):
    with left, right:
        while True:
            ready, _, _ = select.select([left, right], [], [], 1)
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (right if source is left else left).sendall(data)


class Relay(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    slots = threading.BoundedSemaphore(32)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        pass  # Connection errors are returned to the adapter as socket closure.


def relay_handler(connect):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            pump(self.request, connect())
    return Handler


def launch_relay(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def bootstrap():
    spec = json.loads(sys.argv[2])
    for endpoint in spec['endpoints']:
        def connect(path='/relay/' + endpoint['name']):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
            return sock
        # This listener is visible only inside the private network namespace.
        class TCPRelay(Relay):
            address_family = socket.AF_INET
        launch_relay(TCPRelay(('127.0.0.1', endpoint['port']), relay_handler(connect)))
    os.environ['ASUNA_INTEGRATION_CONFIG'] = '/integration/config.json'
    process = subprocess.Popen(spec['argv'], cwd='/app')
    raise SystemExit(process.wait())


def supervise():
    spec = json.loads(sys.stdin.readline())
    output_lock = threading.Lock()

    def emit(value):
        with output_lock:
            print(json.dumps(value, ensure_ascii=True), flush=True)

    with tempfile.TemporaryDirectory(prefix='asuna-relay-') as relay_dir:
        servers = []
        for endpoint in spec['endpoints']:
            def connect(host=endpoint['host'], port=endpoint['target_port']):
                return socket.create_connection((host, port), timeout=10)
            servers.append(launch_relay(Relay(relay_dir + '/' + endpoint['name'], relay_handler(connect))))
        inside = {'argv': spec['argv'], 'endpoints': [{'name': e['name'], 'port': e['port']} for e in spec['endpoints']]}
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
                   '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                   '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--ro-bind', spec['snapshot'], '/app', '--bind', spec['data'], '/data',
                   '--ro-bind', spec['config'], '/integration/config.json', '--ro-bind', relay_dir, '/relay',
                   '--ro-bind', str(Path(__file__).resolve()), '/runner.py', '--chdir', '/app',
                   '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'PYTHONUNBUFFERED', '1',
                   '/usr/bin/prlimit', '--as=536870912', '--fsize=8388608', '--nofile=128', '--',
                   'python3', '/runner.py', 'bootstrap', json.dumps(inside)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def control():
            # EOF also arrives when the owning Windows host exits unexpectedly.
            sys.stdin.readline()
            if process.poll() is None:
                process.terminate()

        threading.Thread(target=control, daemon=True).start()
        def stop(*_):
            if process.poll() is None:
                process.terminate()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        def drain(stream, name):
            total = 0
            while data := os.read(stream.fileno(), 4096):
                total += len(data)
                if total > 8*1024*1024:
                    emit({'type': 'log', 'stream': 'stderr', 'text': 'INTEGRATION_OUTPUT_LIMIT: 8 MiB per stream per run\n'})
                    process.kill()
                    return
                emit({'type': 'log', 'stream': name, 'text': data.decode('utf-8', 'replace')})

        readers = [threading.Thread(target=drain, args=(stream, name), daemon=True)
                   for stream, name in [(process.stdout, 'stdout'), (process.stderr, 'stderr')]]
        for reader in readers:
            reader.start()
        emit({'type': 'started', 'pid': process.pid})
        code = process.wait()
        for reader in readers:
            reader.join(2)
        for server in servers:
            server.shutdown()
            server.server_close()
        emit({'type': 'exit', 'exit_code': code})


if __name__ == '__main__':
    bootstrap() if len(sys.argv) > 1 and sys.argv[1] == 'bootstrap' else supervise()
