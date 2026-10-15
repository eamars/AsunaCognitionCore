"""Where an edited picture may go (owner 2026-10-15): an edit of her own drawing stays hers; an edit of anyone else's
picture goes back only to the conversation that picture came from."""
import pytest

from asuna import outbound_media, vision
from asuna.blobs import BlobStore
from asuna.state import Denied

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))
DRAWN = {'endpoint': 'image', 'artifact_path': '/view?filename=e.png'}


def scenes(store):
    for scene in ('eg1', 'eg2', 'ehome'):
        store.put('scenes', {'_id': scene, 'kind': 'group', 'scope_key': 'scene:' + scene, 'policy_epoch': 1,
                             'members': ['A'], 'sequence': 0}, stream='edit')


def test_an_edit_of_someone_elses_picture_goes_back_only_where_it_came_from(store):
    scenes(store)
    blobs = BlobStore(store)
    # Drawn in a home task from a group picture: kept with the task, marked to go back to g1.
    made = outbound_media.edit_register(store, {'scope_key': 'scene:ehome'}, 'scene:eg1')(PNG, DRAWN)
    row = store.db.artifacts.find_one({'_id': made['artifact_id']})
    assert made['registered'] and row['scope_key'] == 'scene:ehome' and 'read_image' in made['note']
    assert not outbound_media.produced(row) and outbound_media.returns_to(row) == 'scene:eg1'

    outbound_media.accept_artifact(store, blobs, made['artifact_id'], [], produced_only=True, here='scene:eg1')
    with pytest.raises(Denied, match='ATTACHMENT_NOT_HER_OWN'):
        outbound_media.accept_artifact(store, blobs, made['artifact_id'], [], produced_only=True, here='scene:eg2')

    listed = outbound_media.edits_back_to(store, 'scene:eg1')
    assert [item['artifact_id'] for item in listed] == [made['artifact_id']] and listed[0]['edited_from_here']
    assert outbound_media.edits_back_to(store, 'scene:eg2') == []
    assert made['artifact_id'] not in {item['artifact_id'] for item in outbound_media.produced_images(store)}

    declared = {'artifact_id': made['artifact_id'], 'sha256': row['sha256'], 'media_type': 'image/png'}
    data, _type = outbound_media.serve(store, blobs, {'scene_id': 'eg1', 'scope_key': 'scene:eg1'}, declared)
    assert data == PNG
    with pytest.raises(Denied, match='ATTACHMENT_NOT_HER_OWN'):
        outbound_media.serve(store, blobs, {'scene_id': 'eg2', 'scope_key': 'scene:eg2'}, declared)


def test_a_picture_to_edit_says_whether_its_edit_stays_hers_or_goes_back(store):
    scenes(store)
    blobs = BlobStore(store)
    task = {'_id': 't1', 'scene_id': 'eg1', 'scope_key': 'scene:eg1', 'policy_epoch': 1}
    hers = outbound_media.import_register(store, {'scope_key': 'scene:eg2'})(PNG, DRAWN)
    theirs = outbound_media.register_imported_image(store, 'scene:eg1', PNG + b'x', source='upload:pic')
    again = outbound_media.edit_register(store, {'scope_key': 'scene:eg1'}, 'scene:eg1')(PNG + b'y', DRAWN)

    own = vision.picture_to_edit(store, blobs, task, store.config, hers['artifact_id'])
    assert own['own'] and own['data'] == PNG                 # her drawing, from another conversation: still hers
    other = vision.picture_to_edit(store, blobs, task, store.config, theirs['artifact_id'])
    assert not other['own'] and other['back_to'] == 'scene:eg1'
    chained = vision.picture_to_edit(store, blobs, task, store.config, again['artifact_id'])
    assert not chained['own'] and chained['back_to'] == 'scene:eg1'      # an edit of an edit keeps where it goes back

    # The fence is read_image's: a picture of another conversation that is not hers cannot be edited here.
    elsewhere = outbound_media.register_imported_image(store, 'scene:eg2', PNG + b'z', source='upload:pic')
    with pytest.raises(ValueError, match='IMAGE_ARTIFACT_NOT_READABLE'):
        vision.picture_to_edit(store, blobs, task, store.config, elsewhere['artifact_id'])
