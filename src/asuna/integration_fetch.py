"""Trusted one-shot artifact fetcher, run only inside the managed integration namespace.

The model supplies an endpoint alias and a path; this script supplies everything
else. It reads the endpoint table the supervisor mounted at
/integration/config.json, connects to the 127.0.0.1 relay port for that alias
(the only address the namespace can reach), performs one plain HTTP/1.1 GET and
writes the body to /data/artifact.bin. No URL is ever accepted, no redirect is
followed, and at most limit+1 bytes are kept. Stdlib only.

The report on stdout is one JSON line; the host re-reads the file and verifies
the byte count and SHA-256 itself instead of trusting this process.
"""
import hashlib
import json
import os
from pathlib import Path
import sys


CONFIG_PATH = os.environ.get('ASUNA_INTEGRATION_CONFIG', '/integration/config.json')
BODY_PATH = '/data/artifact.bin'
CHUNK = 65536


def http_get(host, port, path, limit, timeout, connect=None):
    """One GET over a configured relay. Returns a plain dict; never raises."""
    import http.client
    out = {'status': None, 'declared': None, 'content_type': None, 'location': None,
           'transport_error': None, 'body': b''}
    connection = None
    try:
        connection = (connect or http.client.HTTPConnection)(host, port, timeout=timeout)
        connection.request('GET', path, headers={'Host': '%s:%d' % (host, port), 'Accept': '*/*',
                                                 'Connection': 'close',
                                                 'User-Agent': 'asuna-integration-import/1'})
        response = connection.getresponse()
        out['status'] = response.status
        out['content_type'] = response.getheader('Content-Type')
        out['location'] = response.getheader('Location')
        declared = (response.getheader('Content-Length') or '').strip()
        if declared.isdigit():
            out['declared'] = int(declared)
        if out['status'] == 200 and out['declared'] is not None and out['declared'] > limit:
            return out          # Declared size is already over the cap: do not read the body.
        chunks = []
        total = 0
        while total < limit + 1:          # 读满上限就停：超限的体不会整份拖回宿主
            piece = response.read(CHUNK)
            if not piece:
                break
            chunks.append(piece)
            total += len(piece)
        out['body'] = b''.join(chunks)[:limit + 1]
    except (OSError, http.client.HTTPException, ValueError) as exc:
        out['transport_error'] = (type(exc).__name__ + ': ' + str(exc))[:200]
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
    return out


def main(argv):
    try:
        request = json.loads(argv[1]) if len(argv) > 1 else {}
        endpoint = request.get('endpoint')
        path = request.get('path')
        limit = request['limit']
        timeout = request.get('timeout', 15)
        if not isinstance(endpoint, str) or not isinstance(path, str) or not path.startswith('/') \
                or type(limit) is not int or not 1 <= limit <= 8 * 1024 * 1024:
            raise ValueError('INVALID_FETCH_REQUEST')
        timeout = float(timeout)
        if not 0 < timeout <= 60:
            raise ValueError('INVALID_FETCH_TIMEOUT')
        configured = json.loads(Path(CONFIG_PATH).read_text(encoding='utf-8')).get('endpoints') or {}
        entry = configured.get(endpoint)
        if not isinstance(entry, dict) or type(entry.get('port')) is not int:
            # Second fence: even a wrong alias cannot turn this into a URL fetch.
            raise ValueError('ENDPOINT_NOT_CONFIGURED: ' + str(endpoint)[:80])
        result = http_get(entry.get('host') or '127.0.0.1', entry['port'], path, limit, timeout)
        body = result.pop('body')
        if result['status'] == 200 and not result['transport_error']:
            Path(BODY_PATH).write_bytes(body)
        result.update({'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        print(json.dumps(result))
    except Exception as exc:                       # 任何意外都报成传输失败，不冒充成功
        print(json.dumps({'status': None, 'declared': None, 'content_type': None, 'location': None,
                          'bytes': 0, 'sha256': None,
                          'transport_error': (type(exc).__name__ + ': ' + str(exc))[:200]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
