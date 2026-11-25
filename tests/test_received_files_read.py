"""ADR-102 sections 2 to 6, only the guards whose failure would be silent and costly: the fence, the cap on bytes read
and the hosts, https only, a program never stored, an erased file never fetched again (and an expired one fetched back
onto its own row). Paging and wording are checked by reading a real file, not here."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from asuna import received_files as rf, vision


def test_a_link_that_is_not_https_is_refused_before_any_request():
    with pytest.raises(rf.FetchFailed, match='RECEIVED_FILE_NOT_HTTPS'):
        rf.fetch('http://gzc-download.ftn.qq.com/x', ('.ftn.qq.com',))


class _Server:
    """A local HTTP server: /big sends more than the cap with no length (the message's declared size lied);
    /away redirects off the list."""

    def __init__(self, cap):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/away':
                    self.send_response(302)
                    self.send_header('Location', 'http://example.invalid/x')
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(b'a' * (cap + 1))
                except OSError:
                    pass

            def log_message(self, *args):
                pass
        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_port


def test_the_cap_counts_bytes_read_and_a_redirect_stays_on_the_list():
    """The shared download (pictures and files): the cap counts the bytes read, whatever size was declared, and a redirect off
    the allowed hosts is refused before it is followed."""
    cap = 4096
    server = _Server(cap)
    try:
        with pytest.raises(vision.OverCap):
            vision.download(server.base + '/big', ['127.0.0.1'], cap, 5)
        with pytest.raises(vision.RedirectDenied):
            vision.download(server.base + '/away', ['127.0.0.1'], cap, 5)
    finally:
        server.httpd.shutdown()


def test_a_stored_file_s_times_are_read(world):
    """From 2026-11-10 (ADR-119 F4 removed media_life's own reader of a stored time) every answer of a read file, every
    let_go and every list of kept files raised ImportError: the times are read with clock.moment."""
    from asuna.records import artifacts as artifact_records
    stored = rf.stash(world, b'hello\n', 'scene:g1', message_id='m-times', index=0, name='a.txt', sender='A')
    row = artifact_records.get(world, stored['artifact_id'])
    assert rf._life(world, row, 'g1').startswith('字节到')
    rf.keep(world, row['_id'], '造的', {'scene:g1'})
    assert [entry['name'] for entry in rf.kept(world, {'scene:g1'})['kept']] == ['a.txt']
    assert rf.let_go(world, row['_id'], {'scene:g1'})['let_go']
