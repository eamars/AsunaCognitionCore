"""ADR-102 sections 2 to 6, only the guards whose failure would be silent and costly: the fence, the cap on bytes read
and the hosts, https only, a program never stored, an erased file never fetched again (and an expired one fetched back
onto its own row). Paging and wording are checked by reading a real file, not here."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from asuna import channel_kinds, received_files as rf, vision
from asuna.blobs import BlobStore
from asuna.state import Denied

URL = 'https://gzc-download.ftn.qq.com/ftn_handler/abc'


@pytest.fixture
def files(store, monkeypatch):
    monkeypatch.setattr(channel_kinds, 'file_hosts', lambda scene_id: ('.ftn.qq.com',))
    fetched = []

    def fake_fetch(url, hosts):
        fetched.append(url)
        return files.body
    files.body, files.fetched = b'line one\nline two\n', fetched
    monkeypatch.setattr(rf, 'fetch', fake_fetch)
    return files


def scene(store, scene_id):
    """Where a call reads from: her turn's scene, as role_tools binds it."""
    row = store.db.scenes.find_one({'_id': scene_id}, {'scope_key': 1, 'policy_epoch': 1})
    return {'scene_id': scene_id, 'scope_key': row['scope_key'], 'policy_epoch': row['policy_epoch']}


def posted(store, scene_id, n=1, name='notes.txt', size='18'):
    from datetime import datetime, timezone
    store.db.messages.insert_one({
        '_id': 'in-file-%s-%d' % (scene_id, n), 'schema_version': 1, 'scene_id': scene_id, 'policy_epoch': 1,
        'direction': 'inbound', 'scene_seq': 1000 + n, 'author': 'qq:10001', 'text': '[文件:%s（未解析）]' % name,
        'received_at': datetime.now(timezone.utc).isoformat(),
        'event': {'raw': {'asuna_media': {'count': 1, 'items': [
            {'type': 'file', 'placeholder': '[文件:%s（未解析）]' % name, 'file': name, 'size': size, 'url': URL}]}}}})
    return vision.ref_of('in-file-%s-%d' % (scene_id, n), 0)


def read(store, where, ref, **args):
    return rf.run(store, where, store.config, {'op': 'read', 'ref': ref, **args},
                  persona=store.config['chat']['persona'], session_class='public')


def test_a_file_from_another_conversation_is_not_found_from_here(store, files):
    here, there = scene(store, 'g1'), scene(store, 'g2')
    ref = posted(store, 'g2')
    with pytest.raises(Denied, match='RECEIVED_FILE_NOT_FOUND'):
        read(store, here, ref)
    assert files.fetched == [], 'nothing is fetched for a ref outside the fence'
    assert read(store, there, ref)['text'] == 'line one\nline two\n'
    rf.run(store, there, store.config, {'op': 'keep', 'ref': ref}, persona=store.config['chat']['persona'],
           session_class='public')
    with pytest.raises(Denied, match='RECEIVED_FILE_NOT_FOUND'):
        read(store, here, ref)                  # a kept file is found by its own row, and only inside its fence


def test_a_program_named_as_text_is_refused_and_never_stored(store, files):
    files.body = b'MZ\x90\x00\x03\x00\x00\x00' + bytes(64)
    with pytest.raises(Denied, match='RECEIVED_FILE_NOT_TEXT: 名字是 .txt，内容却是Windows 程序'):
        read(store, scene(store, 'g1'), posted(store, 'g1'))
    assert store.db.artifacts.count_documents({'kind': rf.KIND}) == 0


def test_an_erased_file_is_never_fetched_again_and_an_expired_one_comes_back_onto_its_own_row(store, files):
    from asuna import blobs
    here = scene(store, 'g1')
    ref = posted(store, 'g1')
    read(store, here, ref)
    row = store.db.artifacts.find_one({'kind': rf.KIND})
    blobs.delete(store, row['gridfs_id'])                               # the sweep's expiry
    store.db.artifacts.update_one({'_id': row['_id']}, {'$set': {'storage': 'removed', 'bytes_removed_at': row['created_at']},
                                                        '$unset': {'gridfs_id': ''}})
    again = read(store, here, ref)
    assert again['refetched'].startswith('前一份字节在') and len(files.fetched) == 2
    assert store.db.artifacts.count_documents({'kind': rf.KIND}) == 1, 'the bytes went back onto the same row'
    BlobStore(store).erase_scope(here['scope_key'], 'erase-test')
    with pytest.raises(Denied, match='ARTIFACT_ERASED') as refused:
        read(store, here, ref)
    assert str(refused.value).endswith(rf.ERASED_LINK) and len(files.fetched) == 2, 'an erasure closes the link too'


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
