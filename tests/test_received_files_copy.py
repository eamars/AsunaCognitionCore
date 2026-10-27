"""ADR-102 sections 7 and 8, only what would fail silently and costly: a copy in /task/received cannot be started as
a program, a hostile name cannot leave the folder, the copies go with the bytes (expiry and erasure), and a file
forwarded from /task keeps where it came from."""
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from asuna import media_life, outbound_files, received_files as rf
from asuna.blobs import BlobStore
from test_received_files_read import files, posted, read, scene  # noqa: F401  (the fixture and helpers)


def copied(store, where, ref, task_dir):
    return rf.run(store, where, store.config, {'op': 'copy', 'ref': ref}, persona=store.config['chat']['persona'],
                  session_class='public', task_dir=task_dir)


@pytest.mark.skipif(os.name != 'nt', reason='the deny-execute entry is Windows; POSIX copies are made 0600')
def test_a_program_in_the_copies_folder_cannot_be_started(store, files, tmp_path):
    import subprocess
    here = scene(store, 'g1')
    ref = posted(store, 'g1')
    read(store, here, ref)
    out = copied(store, here, ref, tmp_path)
    assert out['path'] == '/task/received/notes.txt' and (tmp_path / 'received' / 'notes.txt').read_bytes() == files.body
    program = tmp_path / 'received' / 'tool.exe'
    shutil.copyfile(os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'whoami.exe'), program)
    with pytest.raises(PermissionError):
        subprocess.run([str(program)], capture_output=True, timeout=10)
    assert program.read_bytes()[:2] == b'MZ', 'reading it still works: an interpreter can read a script'


def test_a_hostile_name_stays_in_the_folder_and_is_never_a_device():
    assert rf.safe_name('..\\..\\Windows\\evil.txt') == 'evil.txt'
    assert rf.safe_name('../../etc/passwd') == 'passwd'
    assert rf.safe_name('CON.txt') == '_CON.txt' and rf.safe_name('nul') == '_nul'
    assert rf.safe_name('a?b:c.txt') == 'a_b_c.txt' and rf.safe_name('notes. ') == 'notes'
    long = rf.safe_name('长' * 200 + '.txt')
    assert len(long.encode('utf-8')) <= rf.NAME_BYTES and long.endswith('.txt')


def test_copies_go_with_the_bytes_and_a_kept_files_copy_stays(store, files, tmp_path):
    here = scene(store, 'g1')
    gone_ref, kept_ref, erased_ref = posted(store, 'g1', 1), posted(store, 'g1', 2), posted(store, 'g2', 3)
    there = scene(store, 'g2')
    files.body = b'first\n'
    read(store, here, gone_ref)
    files.body = b'second\n'
    read(store, here, kept_ref)
    files.body = b'third\n'
    read(store, there, erased_ref)
    for ref, where in ((gone_ref, here), (kept_ref, here), (erased_ref, there)):
        copied(store, where, ref, tmp_path)
    rf.run(store, here, store.config, {'op': 'keep', 'ref': kept_ref}, persona=store.config['chat']['persona'],
           session_class='public')
    store.db.artifacts.update_many({'kind': rf.KIND}, {'$set': {'days_from': (datetime.now(timezone.utc)
                                                                            - timedelta(days=4)).isoformat()}})
    BlobStore(store).erase_scope(there['scope_key'], 'erase-test')
    assert not (tmp_path / 'received' / 'notes (3).txt').exists(), 'the erasure took its copy at once'
    media_life.sweep(store)
    left = sorted(path.name for path in (tmp_path / 'received').iterdir())
    assert left == ['notes (2).txt'], 'the expired one went with its bytes; the kept one stays'


def test_a_file_forwarded_from_the_task_folder_keeps_where_it_came_from(store, files, tmp_path, monkeypatch):
    here = scene(store, 'g1')
    ref = posted(store, 'g1')
    read(store, here, ref)
    copied(store, here, ref, tmp_path)
    (tmp_path / 'renamed.txt').write_bytes((tmp_path / 'received' / 'notes.txt').read_bytes())   # renamed in /task
    task = {'_id': 'task-fwd', 'scene_id': 'g1', 'scope_key': here['scope_key'], 'policy_epoch': 1,
            'requester_id': 'qq:10001'}
    registered = outbound_files.register(store, task, tmp_path, {'path': 'renamed.txt'})
    row = store.db.artifacts.find_one({'_id': registered['artifact_id']})
    assert row['received_from']['ref'] == ref
    monkeypatch.setattr(outbound_files, 'sends_here', lambda store, scene: True)
    [item] = outbound_files.offer(store, {'_id': 'g1'})['items']
    assert item['from'] == rf.FORWARDED % row['received_from']['sender']
