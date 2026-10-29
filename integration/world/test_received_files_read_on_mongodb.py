"""ADR-102 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a file from another conversation
is not found from here."""

import pytest

from asuna import channel_kinds, received_files as rf, vision
from asuna.state import Denied

pytestmark = pytest.mark.world                # `store` is the fixture world

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
    row = store.raw.scenes.find_one({'_id': scene_id}, {'scope_key': 1, 'policy_epoch': 1})
    return {'scene_id': scene_id, 'scope_key': row['scope_key'], 'policy_epoch': row['policy_epoch']}


def posted(store, scene_id, n=1, name='notes.txt', size='18'):
    from datetime import datetime, timezone
    store.raw.messages.insert_one({
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


