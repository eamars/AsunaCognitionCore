"""Both brains share read_image (ADR-011 §5.3 as amended): she looks at a picture in her own turn, under the same
fences and storage as the action brain, when her own route takes images and the conversation has one to pull."""
import base64

import pytest

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused
from asuna.vision import line_refs, media_note
from test_local_images import PNG, world

THINK = ('think', {'thought': '他发了张图，我看看。'})


def sees(store, character=('text', 'image')):
    store.config.update(character={'input_modalities': list(character)})


def picture(store, tmp_path):
    scene, chat = world(store, tmp_path)
    from asuna.vision import local_uploads
    media = local_uploads(store, scene['scope_key'], [{'data': base64.b64encode(PNG).decode(), 'name': 'cat.png'}], 'm1')
    chat.submit('看这个', event_id='m1', native_session_id='s-local', native_message_ids=['m1'], media=media)
    row = store.db.messages.find_one({'event.event_id': 'm1'})
    return media_note(row, store.config)['items'][0]['ref']


def test_she_looks_herself_and_the_record_keeps_no_bytes(store, tmp_path):
    ref = picture(store, tmp_path)
    sees(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('read_image', {'ref': ref})], '看到了。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'm2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你看到了吗'})
    assert 'read_image' in lane.calls[0]['tools']
    *_, result, ok = lane.tool_results[1]
    assert ok and base64.b64decode(result['image']['data']) == PNG and result['pulled_via'] == 'blob'
    assert ep['state'] == 'COMMITTED'
    record = next(call for call in ep['tool_calls'].values() if call['tool'] == 'read_image')
    assert 'image' not in record['result'] and record['result']['inline_image']['base64_chars'] > 0
    assert store.db.artifacts.count_documents({'kind': 'image'}) == 1, 'read back, not stored again'


def test_no_tool_when_her_route_cannot_see(store, tmp_path):
    picture(store, tmp_path)
    sees(store, ('text',))
    lane = FakeLane(store, [FakeTurn([THINK], '嗯。')])
    Coordinator(store, lane).ingest({'event_id': 'm2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    assert 'read_image' not in lane.calls[0]['tools']


def test_no_tool_without_a_picture_and_an_unknown_ref_is_refused_in_words(store, tmp_path):
    world(store, tmp_path)
    sees(store)
    lane = FakeLane(store, [FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest({'event_id': 'm2', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    assert 'read_image' not in lane.calls[0]['tools']
    store.db.episodes.update_one({'_id': ep['_id']}, {'$set': {'turn_tools': ['think', 'read_image']}})
    with pytest.raises(Refused, match='照抄图旁标的 ref'):
        coordinator.tools.call(ep['_id'], 'x', 'read_image', {'ref': 'att-unknownpicture'})


def test_a_platform_line_names_its_readable_pictures(store, tmp_path):
    world(store, tmp_path)
    row = {'_id': 'in-1', 'scene_id': 'dm-a', 'event': {'event_id': 'q1', 'channel': {'id': 'qq'}, 'raw': {'asuna_media': {
        'items': [{'type': 'image', 'url': 'https://img.example.invalid/a.png', 'placeholder': '[图片]'},
                  {'type': 'image', 'url': 'https://elsewhere.invalid/b.png', 'placeholder': '[图片]'}]}}}}
    refs = line_refs(row, store.config)
    assert refs.startswith('（图 ref：att-') and refs.count('att-') == 1, 'only the picture that can be pulled'
    assert line_refs({'_id': 'in-2', 'event': {}}, store.config) == ''


# ── looking again at a stored picture (artifact_id) ────────────────────────
def stored(store, scope, source):
    from asuna.blobs import BlobStore
    return BlobStore(store).put(PNG, scope, 'image', media_type='image/png', source_ids=[source])['artifact_id']


def look(store, scope, ref, offered=()):
    from asuna.blobs import BlobStore
    from asuna.vision import read_image_for_task
    store.config.update(executor={**store.config.get('executor', {}), 'input_modalities': ['text', 'image']})
    task = {'scene_id': scope[len('scene:'):], 'scope_key': scope, 'policy_epoch': 1}
    return read_image_for_task(store, BlobStore(store), task, store.config, {'ref': ref}, offered=offered)


def test_a_picture_she_drew_can_be_looked_at_from_any_scene(store, tmp_path):
    world(store, tmp_path)
    mine = stored(store, 'scene:dm-b', 'integration:image:/view?filename=a.png')
    result = look(store, 'scene:dm-a', mine)
    assert base64.b64decode(result['image']['data']) == PNG and result['pulled_via'] == 'artifact' and result['produced']


def test_a_picture_in_the_scene_itself_can_be_looked_at_again(store, tmp_path):
    world(store, tmp_path)
    here = stored(store, 'scene:dm-a', 'in-someone')
    assert look(store, 'scene:dm-a', here)['artifact_id'] == here


def test_someone_elses_picture_answers_like_an_unknown_one(store, tmp_path):
    world(store, tmp_path)
    theirs = stored(store, 'scene:dm-b', 'in-someone-else')
    with pytest.raises(ValueError, match='IMAGE_ARTIFACT_NOT_READABLE'):
        look(store, 'scene:dm-a', theirs)
    with pytest.raises(ValueError, match='IMAGE_ARTIFACT_NOT_READABLE'):
        look(store, 'scene:dm-a', 'blob-' + '0' * 32)
    assert look(store, 'scene:dm-a', theirs, offered=(theirs,))['artifact_id'] == theirs, 'offered to send: may look'


def test_her_turn_offers_read_image_when_she_has_a_picture_to_send(store, tmp_path):
    from asuna.role_tools import her_pictures, offered_pictures
    world(store, tmp_path)
    sees(store)
    ep = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1,
          'context': {'image_artifacts_from_program': {'items': [{'artifact_id': 'blob-' + 'a' * 32}]}}}
    assert offered_pictures(ep) == ('blob-' + 'a' * 32,) and her_pictures(store, ep)
