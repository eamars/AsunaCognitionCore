"""Trusted WSL supervisor and namespace bootstrap. Invoked only by IntegrationRunner.

The outer process owns fixed-destination Unix relays. The inner process has a
private network namespace and can reach only the explicitly mounted relays.
No model-supplied shell command is evaluated by the outer process.

A relay may carry a guard (test runs of an unreviewed adapter against a live
platform, see IntegrationRunner._launch): it accepts only a WebSocket upgrade,
holds the platform credential itself, and forwards only the JSON requests whose
named field matches the guard's read-only patterns. Anything else is answered
with the guard's refusal and logged, so a platform write never leaves a test run.
"""
import fnmatch
import json
import os
from pathlib import Path
import select
import signal
import socket
import socketserver
import struct
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


# It runs under WSL only; the fallback just lets the guard's tests import this module on Windows.
class Relay(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
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


HEAD_LIMIT = 16 * 1024
MESSAGE_LIMIT = 16 * 1024 * 1024
DROPPED_HEADERS = {'authorization', 'cookie', 'sec-websocket-extensions'}   # no compression: frames stay readable


class Reader:
    def __init__(self, sock):
        self.sock, self.buffer = sock, bytearray()

    def _fill(self):
        piece = self.sock.recv(65536)
        if not piece:
            raise EOFError
        self.buffer += piece

    def exact(self, n):
        while len(self.buffer) < n:
            self._fill()
        value = bytes(self.buffer[:n])
        del self.buffer[:n]
        return value

    def head(self):
        while b'\r\n\r\n' not in self.buffer:
            if len(self.buffer) > HEAD_LIMIT:
                raise ValueError('HEAD_TOO_LARGE')
            self._fill()
        index = self.buffer.index(b'\r\n\r\n')
        value = bytes(self.buffer[:index]).decode('latin-1')
        del self.buffer[:index + 4]
        return value


def unmask(payload, key):
    if not payload:
        return payload
    stream = (key * (len(payload) // 4 + 1))[:len(payload)]
    return (int.from_bytes(payload, 'big') ^ int.from_bytes(stream, 'big')).to_bytes(len(payload), 'big')


def read_frame(reader):
    """(fin, rsv, opcode, masked, unmasked payload, raw bytes) of one WebSocket frame."""
    first = reader.exact(2)
    raw = [first]
    length = first[1] & 0x7f
    if length == 126:
        raw.append(reader.exact(2)); length = struct.unpack('!H', raw[-1])[0]
    elif length == 127:
        raw.append(reader.exact(8)); length = struct.unpack('!Q', raw[-1])[0]
    if length > MESSAGE_LIMIT:
        raise ValueError('FRAME_TOO_LARGE')
    key = reader.exact(4) if first[1] & 0x80 else None
    if key:
        raw.append(key)
    raw.append(reader.exact(length))
    payload = unmask(raw[-1], key) if key else raw[-1]
    return first[0] & 0x80, first[0] & 0x70, first[0] & 0x0f, key is not None, payload, b''.join(raw)


def encode_frame(opcode, payload, *, mask):
    head = bytearray([0x80 | opcode])
    bit = 0x80 if mask else 0
    if len(payload) < 126:
        head.append(bit | len(payload))
    elif len(payload) < 65536:
        head += bytes([bit | 126]) + struct.pack('!H', len(payload))
    else:
        head += bytes([bit | 127]) + struct.pack('!Q', len(payload))
    if mask:
        key = os.urandom(4)
        head += key
        payload = unmask(payload, key)
    return bytes(head) + payload


def guarded_request(head, guard):
    """The client's upgrade request with its own credentials removed and the guard's added; None if not an upgrade."""
    lines = head.split('\r\n')
    parts = lines[0].split(' ')
    headers = [line for line in lines[1:] if ':' in line]
    named = {line.split(':', 1)[0].strip().lower(): line.split(':', 1)[1].strip() for line in headers}
    if len(parts) != 3 or parts[0] != 'GET' or named.get('upgrade', '').lower() != 'websocket':
        return None
    path, _, query = parts[1].partition('?')
    query = '&'.join(item for item in query.split('&') if item and item.split('=', 1)[0] != 'access_token')
    kept = [line for line in headers if line.split(':', 1)[0].strip().lower() not in DROPPED_HEADERS]
    if guard.get('credential'):
        kept.append('Authorization: Bearer ' + guard['credential'])
    return '\r\n'.join(['GET %s %s' % (path + ('?' + query if query else ''), parts[2]), *kept]) + '\r\n\r\n'


def guarded_session(client, server, guard, log):
    lock = threading.Lock()

    def to_client(data):
        with lock:
            client.sendall(data)

    def refuse(what, request=None):
        log('INTEGRATION_TEST_REFUSED %s: this test run reaches the platform read-only; '
            'sending goes through the outbox and the published adapter\n' % what[:120])
        if isinstance(request, dict) and guard.get('refusal') is not None:
            reply = dict(guard['refusal'])
            if guard.get('correlate') in request:
                reply[guard['correlate']] = request[guard['correlate']]
            to_client(encode_frame(1, json.dumps(reply).encode('utf-8'), mask=False))

    def decide(opcode, message):
        try:
            request = json.loads(message.decode('utf-8')) if opcode == 1 else None
        except ValueError:
            request = None
        value = request.get(guard['field']) if isinstance(request, dict) else None
        if not isinstance(value, str):
            return refuse('a frame that is not a JSON request with "%s"' % guard['field'], request)
        if any(fnmatch.fnmatchcase(value, p) for p in guard['allow']) and \
                not any(fnmatch.fnmatchcase(value, p) for p in guard.get('deny', ())):
            server.sendall(encode_frame(opcode, message, mask=True))
        else:
            refuse('%s=%s' % (guard['field'], value), request)

    server.settimeout(None)                    # the connect timeout must not end an idle WebSocket
    with client, server:
        inbound, outbound = Reader(client), Reader(server)
        try:
            request = guarded_request(inbound.head(), guard)
            if request is None:
                log('INTEGRATION_TEST_REFUSED a request that is not a WebSocket upgrade\n')
                return to_client(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            server.sendall(request.encode('latin-1'))
            response = outbound.head()
            to_client((response + '\r\n\r\n').encode('latin-1'))
            if response.split(' ')[1:2] != ['101']:
                return
        except (EOFError, ValueError, OSError):
            return

        def downstream():
            try:
                while True:
                    to_client(read_frame(outbound)[5])
            except (EOFError, ValueError, OSError):
                pass
            finally:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        threading.Thread(target=downstream, daemon=True).start()
        opcode, message = None, bytearray()
        try:
            while True:
                fin, rsv, op, masked, payload, raw = read_frame(inbound)
                if rsv or not masked:
                    return refuse('an extension or unmasked frame')
                if op >= 8:                        # close, ping, pong
                    server.sendall(raw)
                    continue
                if op:
                    opcode, message = op, bytearray()
                elif opcode is None:
                    return
                message += payload
                if len(message) > MESSAGE_LIMIT:
                    return
                if fin:
                    decide(opcode, bytes(message))
                    opcode = None
        except (EOFError, ValueError, OSError):
            pass


def guarded_http(client, server, guard, log):
    """One HTTP request per connection: forwarded only when "METHOD path" matches the guard, with its credential.

    With `tls` the relay speaks TLS to the device (a LAN service behind its own local CA, so the certificate is not
    verified) while the run speaks plain HTTP to the relay, which is what lets the guard read the request.
    """
    if guard.get('tls'):
        import ssl
        context = ssl.create_default_context()
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        server = context.wrap_socket(server, server_hostname=guard.get('host'))
    server.settimeout(None)
    with client, server:
        inbound = Reader(client)
        try:
            head = inbound.head()
            lines = head.split('\r\n')
            parts = lines[0].split(' ')
            headers = [line for line in lines[1:] if ':' in line]
            named = {line.split(':', 1)[0].strip().lower(): line.split(':', 1)[1].strip() for line in headers}
            length = int(named.get('content-length') or 0)
            if len(parts) != 3 or 'transfer-encoding' in named or 'upgrade' in named or not 0 <= length <= MESSAGE_LIMIT:
                request = None
            else:
                request = '%s %s' % (parts[0], parts[1].partition('?')[0])
            body = inbound.exact(length) if request else b''
        except (EOFError, ValueError, OSError):
            return
        if not request or not any(fnmatch.fnmatchcase(request, p) for p in guard['allow']):
            log('INTEGRATION_REFUSED %s: %s\n' % ((request or 'a malformed request')[:120],
                (guard.get('refusal') or {}).get('detail', 'read-only here')))
            refusal = json.dumps(guard.get('refusal') or {'error': 'INTEGRATION_TEST_READ_ONLY'}).encode('utf-8')
            client.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\nContent-Length: %d\r\n'
                           b'Connection: close\r\n\r\n' % len(refusal) + refusal)
            return
        dropped = DROPPED_HEADERS | {'connection'} | ({'host'} if guard.get('host') else set())
        kept = [line for line in headers if line.split(':', 1)[0].strip().lower() not in dropped]
        if guard.get('host'):
            kept.append('Host: ' + guard['host'])          # the device's own name, not the relay's
        if guard.get('credential'):
            kept.append('Authorization: Bearer ' + guard['credential'])
        try:
            server.sendall(('\r\n'.join([lines[0], *kept, 'Connection: close']) + '\r\n\r\n').encode('latin-1') + body)
            while data := server.recv(65536):
                client.sendall(data)
        except OSError:
            pass


def guarded_handler(connect, guard, log):
    session = guarded_http if guard.get('protocol') == 'http' else guarded_session
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            session(self.request, connect(), guard, log)
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
            handler = (guarded_handler(connect, endpoint['guard'], lambda text: emit({'type': 'log', 'stream': 'relay', 'text': text}))
                       if endpoint.get('guard') else relay_handler(connect))
            servers.append(launch_relay(Relay(relay_dir + '/' + endpoint['name'], handler)))
        inside = {'argv': spec['argv'], 'endpoints': [{'name': e['name'], 'port': e['port']} for e in spec['endpoints']]}
        # Clients such as ssh refuse to run when their uid has no passwd entry; the namespace has no /etc of its own.
        identity = Path(relay_dir) / '.identity'           # removed with the relay directory
        identity.mkdir()
        (identity / 'passwd').write_text('integration:x:%d:%d::/tmp:/usr/sbin/nologin\n' % (os.getuid(), os.getgid()))
        (identity / 'group').write_text('integration:x:%d:\n' % os.getgid())
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
                   '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                   '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--ro-bind', spec['snapshot'], '/app', '--bind', spec['data'], '/data',
                   '--ro-bind', spec['config'], '/integration/config.json', '--ro-bind', relay_dir, '/relay',
                   '--ro-bind', str(Path(__file__).resolve()), '/runner.py', '--chdir', '/app',
                   '--ro-bind', str(identity / 'passwd'), '/etc/passwd', '--ro-bind', str(identity / 'group'), '/etc/group',
                   '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'PYTHONUNBUFFERED', '1', '--setenv', 'HOME', '/tmp',
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
