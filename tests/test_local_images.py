"""Pictures the owner attaches in her local chat (MongoDB): DSH shows each to her; the program keeps its own record —
the input row, her image in that chat, and a ref her action brain reads it by. A platform message cannot borrow it."""
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from asuna.blobs import BlobStore
from asuna.chat import Chat
from asuna.evidence import Evidence
from asuna.native_worker import BusinessWorker
from asuna.vision import attachments_of, local_uploads, media_note, read_image_for_task
from test_adr009_p2 import owner

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))


def world(store, tmp_path):
    owner(store)
    store.config.update(executor={'input_modalities': ['text', 'image']}, vision={'image_hosts': ['img.example.invalid']})
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    chat = Chat(SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence')),
                {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}, lambda _: None)
    return scene, chat


def test_a_local_picture_is_recorded_once_and_her_action_brain_reads_it(store, tmp_path):
    scene, chat = world(store, tmp_path)
    images = [{'data': base64.b64encode(PNG).decode(), 'media_type': 'image/png', 'name': 'error.png',
               'width': 8, 'height': 6, 'attachment_id': 'sha256:x'}, {'name': 'broken.png', 'error': 'ENOENT'}]
    media = local_uploads(store, scene['scope_key'], images, 'msg-1')
    assert local_uploads(store, scene['scope_key'], images, 'msg-1')['items'][0]['artifact_id'] == \
        media['items'][0]['artifact_id'], 'a retried input stores nothing twice'
    assert store.db.artifacts.count_documents({'source_ids': 'local-upload:msg-1'}) == 1
    assert [item['placeholder'] for item in media['items']] == ['[图片：error.png]', '[图片：broken.png（没能读取）]']
    chat.submit('帮我看看这个报错', event_id='msg-1', native_session_id='s-local', native_message_ids=['msg-1'],
                media=media)
    row = store.db.messages.find_one({'event.event_id': 'msg-1'})
    assert row['text'] == '[图片：error.png] [图片：broken.png（没能读取）]\n帮我看看这个报错'
    note = media_note(row, store.config)
    assert '就在对话里' in note['meaning'] and note['items'][0]['pull_via'] == 'blob'
    assert note['items'][1]['pullable'] is False and 'ENOENT' in note['items'][1]['not_pullable_because']
    task = {'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    read = read_image_for_task(store, BlobStore(store), task, store.config, {'ref': note['items'][0]['ref']})
    assert base64.b64decode(read['image']['data']) == PNG and read['pulled_via'] == 'blob'
    assert read['blob_artifact'] == media['items'][0]['artifact_id'], 'read back, not stored again'
    assert store.db.artifacts.count_documents({'kind': 'image'}) == 1


def test_a_platform_message_cannot_borrow_a_local_picture(store, tmp_path):
    scene, _ = world(store, tmp_path)
    media = local_uploads(store, scene['scope_key'], [{'data': base64.b64encode(PNG).decode(), 'name': 'a.png'}], 'm')
    forged = {'_id': 'in-forged', 'scene_id': 'dm-a', 'event': {'event_id': 'm', 'channel': {'id': 'qq'},
              'raw': {'asuna_media': media}}}
    entry = attachments_of(forged, config=store.config)[0]
    assert entry['pull_via'] != 'blob' and entry['pullable'] is False


def test_the_web_input_carries_the_pictures_to_the_queue(tmp_path, store):
    scene, _ = world(store, tmp_path)
    worker = BusinessWorker('unused')
    local = {'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(tmp_path / 'local')}
    worker.app = SimpleNamespace(config={'chat': local}, store=store)
    accepted = []
    worker.controller = SimpleNamespace(submit=lambda text, **kw: accepted.append((text, kw['media'])))
    worker.dispatch('input', {'session_id': 'new-local', 'cwd': str(tmp_path / 'local'), 'text': '',
                              'message_ids': ['m-only-picture'],
                              'images': [{'data': base64.b64encode(PNG).decode(), 'name': 'p.png'}]})
    (text, media), = accepted
    assert text == '' and media['items'][0]['placeholder'] == '[图片：p.png]'   # submit puts the placeholder in
