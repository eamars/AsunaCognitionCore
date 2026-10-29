"""Her local pictures on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a platform message
cannot borrow a local picture."""
import base64
from types import SimpleNamespace

import pytest

from asuna.chat import Chat
from asuna.evidence import Evidence
from asuna.vision import attachments_of, local_uploads

from turn_parts import owner

pytestmark = pytest.mark.world                # `store` is the fixture world

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))


def world(store, tmp_path):
    owner(store)
    store.config.update(executor={'input_modalities': ['text', 'image']}, vision={'image_hosts': ['img.example.invalid']})
    scene = store.raw.scenes.find_one({'_id': 'dm-a'})
    chat = Chat(SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence')),
                {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}, lambda _: None)
    return scene, chat


def test_a_platform_message_cannot_borrow_a_local_picture(store, tmp_path):
    scene, _ = world(store, tmp_path)
    media = local_uploads(store, scene['scope_key'], [{'data': base64.b64encode(PNG).decode(), 'name': 'a.png'}], 'm')
    forged = {'_id': 'in-forged', 'scene_id': 'dm-a', 'event': {'event_id': 'm', 'channel': {'id': 'qq'},
              'raw': {'asuna_media': media}}}
    entry = attachments_of(forged, config=store.config)[0]
    assert entry['pull_via'] != 'blob' and entry['pullable'] is False


