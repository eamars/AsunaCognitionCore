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
    with pytest.raises(Refused, match='IMAGE_ATTACHMENT_NOT_IN_SCENE: att-unknownpicture'):
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


def test_the_size_cap_is_the_programs_not_a_guess_in_the_call(store, tmp_path):
    """She used to pass max_bytes guesses (20 KB-200 KB) and had her own stickers refused as too large."""
    from asuna.blobs import BlobStore
    from asuna.vision import READ_IMAGE_TOOL, read_image_for_task
    world(store, tmp_path)
    big = PNG + b'x' * 5000
    ref = BlobStore(store).put(big, 'scene:dm-a', 'image', media_type='image/png', source_ids=['in-someone'])['artifact_id']
    store.config.update(executor={**store.config.get('executor', {}), 'input_modalities': ['text', 'image']})
    task = {'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1}
    result = read_image_for_task(store, BlobStore(store), task, store.config, {'ref': ref, 'max_bytes': 1024})
    assert result['bytes'] == len(big)
    assert set(READ_IMAGE_TOOL['parameters']) == {'ref'}


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


def test_at_home_where_nothing_can_be_sent_she_still_sees_and_looks_at_her_own_pictures(store, tmp_path):
    from test_engineering_m1 import event
    world(store, tmp_path)
    sees(store)
    mine = stored(store, 'scene:dm-b', 'integration:image:/view?filename=me.png')
    lane = FakeLane(store, [FakeTurn([THINK, ('read_image', {'ref': mine})], '原来我长这样')])
    ep = Coordinator(store, lane).ingest(event('look-1'))
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    listed = ep['context']['your_pictures_from_program']
    assert [item['artifact_id'] for item in listed['items']] == [mine] and 'read_image' in listed['note']
    assert 'image_artifacts_from_program' not in ep['context']                # nothing here can be sent
    assert 'read_image' in lane.calls[0]['tools'] and lane.tool_results[1][5], lane.tool_results


def test_an_expired_link_says_retrying_cannot_help_and_a_server_error_may_pass():
    from asuna.vision import _fetch_failed
    expired = str(_fetch_failed(400, '{"retcode":-5503007,"retmsg":"download url has expired"}'))
    assert expired.startswith('IMAGE_FETCH_FAILED: 图片主机回了 HTTP 400') and '重试也一样' in expired
    assert '过一会儿再试一次' in str(_fetch_failed(503))


# ── reading a picture off this machine's disk (home conversations only) ─────
def session_class_of(store, scene_id, person):
    """The program's own judgment for one conversation — the same call each entry point makes."""
    from asuna import visibility
    scene = store.db.scenes.find_one({'_id': scene_id}) or {'_id': scene_id}
    return visibility.session_class(store.config, store.db, scene, person)


def task_in(scope):
    return {'scene_id': scope[len('scene:'):], 'scope_key': scope, 'policy_epoch': 1}


def test_at_home_a_picture_on_disk_is_read_by_its_absolute_path(store, tmp_path):
    from asuna import outbound_media, visibility
    from asuna.blobs import BlobStore
    from asuna.vision import read_image_for_task
    world(store, tmp_path)
    sees(store)
    picture_file = tmp_path / 'shelf' / 'cat.png'
    picture_file.parent.mkdir()
    picture_file.write_bytes(PNG)
    cls = session_class_of(store, 'dm-a', 'A')
    assert cls == visibility.OWNER_PRIVATE, "the owner's local scene is home"
    result = read_image_for_task(store, BlobStore(store), task_in('scene:dm-a'), store.config, {'ref': str(picture_file)},
                                 route='character', session_class=cls)
    assert base64.b64decode(result['image']['data']) == PNG
    assert result['pulled_via'] == 'local_file' and result['path'] == str(picture_file.resolve())
    row = store.db.artifacts.find_one({'_id': result['blob_artifact']})
    assert row['source_ids'] == ['file:' + str(picture_file.resolve())], 'where the bytes came from is recorded'
    assert not outbound_media.produced(row), 'a picture read off disk is not one she may send in a group'


def test_a_group_turn_refuses_a_disk_path_and_says_what_to_do_instead(store, tmp_path):
    from asuna import visibility
    from asuna.blobs import BlobStore
    from asuna.role_tools import words
    from asuna.vision import read_image_for_task
    world(store, tmp_path)
    sees(store)
    picture_file = tmp_path / 'cat.png'
    picture_file.write_bytes(PNG)
    cls = session_class_of(store, 'g1', 'A')
    assert cls == visibility.PUBLIC, 'a group is not home'
    with pytest.raises(PermissionError) as refused:
        read_image_for_task(store, BlobStore(store), task_in('scene:g1'), store.config, {'ref': str(picture_file)},
                            route='character', session_class=cls)
    said = words(refused.value)
    assert 'IMAGE_PATH_HOME_ONLY' in said and '家里' in said, said
    # 群里的 read_image 本身没有被收掉：消息里的图照旧走 att- 那条路（这里只是没有那样的消息）。
    with pytest.raises(ValueError, match='IMAGE_ATTACHMENT_NOT_IN_SCENE'):
        read_image_for_task(store, BlobStore(store), task_in('scene:g1'), store.config, {'ref': 'att-000000000000'},
                            route='character', session_class=cls)


def test_a_file_that_is_not_a_picture_is_refused_by_type(store, tmp_path):
    from asuna.blobs import BlobStore
    from asuna.vision import read_image_for_task
    world(store, tmp_path)
    sees(store)
    note = tmp_path / 'notes.txt'
    note.write_bytes('这不是图，是一段字。'.encode('utf-8'))
    with pytest.raises(ValueError, match='IMAGE_TYPE_UNSUPPORTED'):
        read_image_for_task(store, BlobStore(store), task_in('scene:dm-a'), store.config, {'ref': str(note)},
                            route='character', session_class=session_class_of(store, 'dm-a', 'A'))
    assert store.db.artifacts.count_documents({'kind': 'image'}) == 0, 'nothing was stored'


def test_a_bare_file_name_still_comes_from_the_configured_image_dirs(store, tmp_path):
    """老行为钉住：裸文件名在 vision.image_dirs 里找（不需要家里），带斜杠的名字仍然不当成路径。"""
    from asuna.blobs import BlobStore
    from asuna.vision import attachments_of, read_image_for_task, ref_of
    world(store, tmp_path)
    sees(store)
    images = tmp_path / 'imgs'
    (images / 'sub').mkdir(parents=True)
    (images / 'cat.png').write_bytes(PNG)
    (images / 'sub' / 'dog.png').write_bytes(PNG)
    store.config.update(vision={'image_hosts': ['img.example.invalid'], 'image_dirs': [str(images)]})
    store.put('messages', {'_id': 'in-disk', 'scene_id': 'dm-a', 'author': 'A', 'direction': 'inbound',
                           'text': '[图片：cat.png][图片：sub/dog.png]', 'received_at': '2026-10-10T01:00:00+00:00',
                           'policy_epoch': 1, 'scene_seq': 900,
                           'event': {'event_id': 'q-disk', 'channel': {'id': 'qq'}, 'raw': {'asuna_media': {
                               'count': 2, 'items': [{'type': 'image', 'file': 'cat.png', 'placeholder': '[图片：cat.png]'},
                                                     {'type': 'image', 'file': 'sub/dog.png',
                                                      'placeholder': '[图片：sub/dog.png]'}]}}}})
    entries = attachments_of(store.db.messages.find_one({'_id': 'in-disk'}), config=store.config)
    assert [entry['pullable'] for entry in entries] == [True, False]
    assert entries[0]['pull_via'] == 'local_file'
    assert 'no_source' in entries[1]['not_pullable_because']
    read = read_image_for_task(store, BlobStore(store), task_in('scene:dm-a'), store.config, {'ref': ref_of('in-disk', 0)})
    assert base64.b64decode(read['image']['data']) == PNG and read['pulled_via'] == 'local_file'
    assert 'path' not in read['source'], 'a bare name is not reported as a path'


def test_an_action_task_reads_its_own_workspace_by_its_task_path(store, tmp_path):
    from asuna.blobs import BlobStore
    from asuna.vision import read_image_for_task
    world(store, tmp_path)
    workspace = tmp_path / 'task'
    (workspace / 'images').mkdir(parents=True)
    (workspace / 'images' / 'shot.png').write_bytes(PNG)
    cls = session_class_of(store, 'dm-a', 'A')
    result = read_image_for_task(store, BlobStore(store), task_in('scene:dm-a'), store.config,
                                 {'ref': '/task/images/shot.png'}, session_class=cls, task_dir=workspace)
    assert base64.b64decode(result['image']['data']) == PNG
    assert result['path'] == str((workspace / 'images' / 'shot.png').resolve())
    # 没有任务目录的那一轮不把 /task/ 当成一个随便的本机路径去猜。
    with pytest.raises(PermissionError, match='IMAGE_TASK_DIR_UNAVAILABLE'):
        read_image_for_task(store, BlobStore(store), task_in('scene:dm-a'), store.config,
                            {'ref': '/task/images/shot.png'}, session_class=cls)
