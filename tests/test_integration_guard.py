"""Test runs reach a messaging platform read-only (integration_worker guard, channel kind test_guards)."""
import json
import os
import socket
import threading

from asuna import integration_worker as worker
from asuna.integration import HELD_BY_RELAY, guard_test_run

TOKEN = 'placeholder-napcat-token'
GUARD = {'field': 'action', 'allow': ['get_*', 'can_*'], 'deny': ['get_cookies'], 'correlate': 'echo',
         'refusal': {'status': 'failed', 'retcode': 1403}, 'credential': TOKEN}


def adapter():
    return {'napcat': {'transport': 'websocket_forward', 'url': 'ws://127.0.0.1:9001', 'token': TOKEN},
            'host': {'base_url': 'http://127.0.0.1:9002', 'token': 'placeholder-host-token-abcdefghijklmnop'}}


def endpoints():
    return [{'name': 'napcat', 'host': '192.0.2.10', 'port': 9001, 'target_port': 5001},
            {'name': 'napcat-again', 'host': '192.0.2.10', 'port': 9003, 'target_port': 5001},
            {'name': 'host', 'host': '127.0.0.1', 'port': 9002, 'target_port': 8766}]


def test_test_runs_carry_a_placeholder_and_every_platform_alias_is_guarded():
    config, guarded = guard_test_run(adapter(), endpoints())
    assert config['napcat']['token'] == HELD_BY_RELAY
    assert config['host']['token'] != HELD_BY_RELAY
    by_name = {e['name']: e for e in guarded}
    for name in ('napcat', 'napcat-again'):
        guard = by_name[name]['guard']
        assert guard['credential'] == TOKEN and guard['field'] == 'action'
        assert 'get_*' in guard['allow'] and 'get_cookies' in guard['deny']
    assert 'guard' not in by_name['host']
    assert all('guard' not in e for e in endpoints())       # the profile's own list is not changed


def test_an_adapter_without_a_platform_url_gets_no_guard():
    config, guarded = guard_test_run({'host': {}}, endpoints())
    assert all('guard' not in e for e in guarded)


class Platform:
    """A WebSocket server that records the upgrade request and every text message it receives."""

    def __init__(self, sock):
        self.sock, self.head, self.messages = sock, None, []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        reader = worker.Reader(self.sock)
        try:
            self.head = reader.head()
            if 'upgrade: websocket' not in self.head.lower():
                return
            self.sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
            while True:
                fin, rsv, opcode, masked, payload, raw = worker.read_frame(reader)
                assert masked
                if opcode == 9:
                    self.messages.append(('ping', payload))
                    continue
                self.messages.append(json.loads(payload))
                self.sock.sendall(worker.encode_frame(1, json.dumps({'status': 'ok', 'echo': self.messages[-1]['echo']}).encode(), mask=False))
        except (EOFError, OSError, ValueError):
            pass


def session(head=None):
    client, relay_client = socket.socketpair()
    relay_server, server = socket.socketpair()
    platform, log = Platform(server), []
    threading.Thread(target=worker.guarded_session, args=(relay_client, relay_server, GUARD, log.append), daemon=True).start()
    client.settimeout(5)
    client.sendall((head or 'GET /api?access_token=from-the-adapter&x=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n'
                    'Upgrade: websocket\r\nConnection: Upgrade\r\nAuthorization: Bearer from-the-adapter\r\n'
                    'Sec-WebSocket-Extensions: permessage-deflate\r\n\r\n').encode('latin-1'))
    return client, worker.Reader(client), platform, log


def request(client, action, echo, *, fragments=1):
    data = json.dumps({'action': action, 'params': {}, 'echo': echo}).encode()
    if fragments == 1:
        return client.sendall(worker.encode_frame(1, data, mask=True))
    half = len(data) // 2
    for index, (opcode, part) in enumerate(((1, data[:half]), (0, data[half:]))):
        frame = bytearray(worker.encode_frame(opcode, part, mask=True))
        if index == 0:
            frame[0] &= 0x7f                                   # not final
        client.sendall(bytes(frame))


def reply(reader):
    return json.loads(worker.read_frame(reader)[4])


def test_the_relay_holds_the_credential_and_strips_the_clients():
    client, reader, platform, log = session()
    assert reader.head().startswith('HTTP/1.1 101')
    head = platform.head
    assert 'Authorization: Bearer ' + TOKEN in head
    assert 'from-the-adapter' not in head and 'permessage-deflate' not in head
    assert head.startswith('GET /api?x=1 HTTP/1.1')
    client.close()


def test_reads_pass_and_writes_are_answered_with_the_refusal_and_logged():
    client, reader, platform, log = session()
    reader.head()
    request(client, 'get_login_info', 'e1')
    assert reply(reader) == {'status': 'ok', 'echo': 'e1'}
    request(client, 'send_group_msg', 'e2')
    assert reply(reader) == {'status': 'failed', 'retcode': 1403, 'echo': 'e2'}
    request(client, 'get_cookies', 'e3')
    assert reply(reader)['echo'] == 'e3'
    request(client, 'get_group_list', 'e4', fragments=2)
    assert reply(reader) == {'status': 'ok', 'echo': 'e4'}
    client.sendall(worker.encode_frame(9, b'hi', mask=True))
    request(client, 'can_send_image', 'e5')
    assert reply(reader)['status'] == 'ok'
    assert [m['action'] if isinstance(m, dict) else m[0] for m in platform.messages] == \
        ['get_login_info', 'get_group_list', 'ping', 'can_send_image']
    assert any('send_group_msg' in line and 'INTEGRATION_TEST_REFUSED' in line for line in log)
    assert any('get_cookies' in line for line in log)
    client.close()


def test_a_frame_that_is_not_a_request_never_reaches_the_platform():
    client, reader, platform, log = session()
    reader.head()
    client.sendall(worker.encode_frame(1, b'not json', mask=True))
    client.sendall(worker.encode_frame(2, os.urandom(8), mask=True))
    request(client, 'get_status', 'e1')
    assert reply(reader)['echo'] == 'e1'
    assert [m['action'] for m in platform.messages] == ['get_status']
    assert sum('INTEGRATION_TEST_REFUSED' in line for line in log) == 2
    client.close()


def test_a_plain_http_request_is_refused():
    client, reader, platform, log = session('POST /send_private_msg HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
    assert reader.head().startswith('HTTP/1.1 403')
    platform.thread.join(2)
    assert platform.head is None and platform.messages == []
    assert any('not a WebSocket upgrade' in line for line in log)


def test_a_device_may_serve_on_a_low_port_but_the_relay_binds_high():
    import pytest
    from asuna.integration import validate_profile

    def profile(port, target):
        return {'chat': {'scene_id': 'local', 'person_id': 'owner'},
                'integration': {'enabled': True, 'scene_id': 'local', 'person_id': 'owner',
                                'endpoints': [{'name': 'gateway', 'host': '192.0.2.20', 'port': port, 'target_port': target}]}}
    validate_profile(profile(9022, 22))
    for port, target in ((22, 22), (9022, 0), (9022, 70000)):
        with pytest.raises(ValueError, match='INVALID_INTEGRATION_PORT'):
            validate_profile(profile(port, target))
