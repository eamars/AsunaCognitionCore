"""ADR-105 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): an erased picture is said to be
erased only inside its fence: speak naming another conversation's erased picture hears only the offer's refusal, and
reading, the blob store and accepting a picture check the fence before the sentence."""

import pytest

from asuna import blobs as blobs_mod, local_time, outbound_media
from asuna.blobs import ERASED_WORDS, BlobStore
from asuna.state import Denied

pytestmark = pytest.mark.world                # `store` is the fixture world

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))


def scopes(store):
    rows = list(store.raw.scenes.find({}, {'_id': 1, 'scope_key': 1}).sort('_id', 1))
    return rows[0], rows[1]


def picture(store, scope, source='in-ep-1', body=PNG):
    return BlobStore(store).put(body + source.encode(), scope, 'image', source_ids=[source])['artifact_id']


def sentence(store, row_id, scene_id, what):
    """The ADR-105 sentence, with the row's erased_at on the clock of the conversation it is said in."""
    row = store.raw.artifacts.find_one({'_id': row_id})
    return ERASED_WORDS % (what, local_time.stamp(row['erased_at'], local_time.zone_of(store, scene_id)))


# ── the blob store ──────────────────────────────────────────────────
def test_the_blob_store_answers_the_sentence_in_its_scope_and_refuses_as_before_outside_it(store):
    here, there = scopes(store)
    blobs = BlobStore(store)
    row_id = picture(store, here['scope_key'])
    blobs.erase_scope(here['scope_key'], 'erase-test')
    words = sentence(store, row_id, here['_id'], '张图')
    for read in (lambda scope: blobs.get(row_id, scope, operator=True),
                 lambda scope: blobs.get_range(row_id, scope, 0, 4, operator=True)):
        with pytest.raises(Denied) as erased:
            read(here['scope_key'])
        assert str(erased.value) == 'ARTIFACT_ERASED: ' + words
        with pytest.raises(Denied) as outside:
            read(there['scope_key'])
        assert 'ARTIFACT_SCOPE_DENIED' in str(outside.value) and '隐私清除' not in str(outside.value)


# ── reading a picture ───────────────────────────────────────────────
def test_reading_a_stored_picture_says_it_was_erased_only_inside_her_fence(store):
    from asuna.vision import stored_image
    here, there = scopes(store)
    row_id = picture(store, here['scope_key'])
    BlobStore(store).erase_scope(here['scope_key'], 'erase-test')
    task = {'scene_id': here['_id'], 'scope_key': here['scope_key']}
    with pytest.raises(Denied) as erased:
        stored_image(store, BlobStore(store), task, store.config, row_id)
    assert str(erased.value) == 'ARTIFACT_ERASED: ' + sentence(store, row_id, here['_id'], '张图')
    elsewhere = {'scene_id': there['_id'], 'scope_key': there['scope_key']}
    with pytest.raises(ValueError, match='IMAGE_ARTIFACT_NOT_READABLE'):
        stored_image(store, BlobStore(store), elsewhere, store.config, row_id)


# ── sending a picture ───────────────────────────────────────────────
def imported(store, tmp_path, register='foreign'):
    """A picture in the owner's local chat, readable from his QQ chat; by default not one she made, so the fences
    of the conversation apply to it."""
    from test_outbound_image_on_mongodb import LOCAL, LOCAL_SCOPE, QQ, channel_scene, import_bytes, link
    from turn_parts import owner
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    made = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path, register=register)
    return made['artifact']['artifact_id'], LOCAL_SCOPE, QQ


def test_accepting_a_picture_checks_the_fence_before_saying_it_was_erased(store, tmp_path):
    art, scope, qq = imported(store, tmp_path)
    BlobStore(store).erase_scope(scope, 'erase-test')
    with pytest.raises(Denied) as erased:
        outbound_media.accept_artifact(store, BlobStore(store), art, [scope], scene_id=qq)
    assert str(erased.value) == 'ARTIFACT_ERASED: ' + sentence(store, art, qq, '张图')
    with pytest.raises(Denied, match='ATTACHMENT_SCOPE_DENIED'):
        outbound_media.accept_artifact(store, BlobStore(store), art, ['scene:elsewhere'], scene_id=qq)
    with pytest.raises(Denied, match='ATTACHMENT_NOT_HER_OWN'):
        outbound_media.accept_artifact(store, BlobStore(store), art, [], produced_only=True, scene_id=qq)


def test_speak_naming_another_conversations_erased_picture_hears_only_the_offer_refusal(store, tmp_path,
                                                                                        monkeypatch):
    """A picture of a conversation this one may not use: erased or not, the answer is the offer's own refusal, so the
    sentence never tells this conversation that the row exists."""
    from asuna import channel_kinds
    from asuna.coordinator import Coordinator
    from asuna.ingress import persist_input
    from asuna.lanes import FakeLane, FakeTurn
    from test_outbound_image_on_mongodb import model
    THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})
    _, _, qq = imported(store, tmp_path)
    other = store.raw.scenes.find_one({'_id': {'$nin': [qq, 'dm-a']}, 'scope_key': {'$exists': True}})
    foreign = outbound_media.register_imported_image(store, other['scope_key'], PNG + b'b', source='upload:b')
    foreign = foreign['artifact_id'] if isinstance(foreign, dict) else foreign
    BlobStore(store).erase_scope(other['scope_key'], 'erase-test')
    assert blobs_mod.erased(store.raw.artifacts.find_one({'_id': foreign}))
    monkeypatch.setattr(channel_kinds, 'reply_parts', lambda scene_id: ('text', 'picture') if scene_id == qq else ())
    store.config['persona_model'] = model()
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'picture', 'artifact_id': foreign}]})])])
    event = {'event_id': 'pic-x', 'scene_id': qq, 'person_id': 'A', 'text': '图呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': {'type': 'dm', 'id': 'peer'},
                         'platform_event_id': 'p-pic-x'}}
    persist_input(store, event, managed=True)
    Coordinator(store, lane).ingest(event)
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert not ok and '不在 image_artifacts_from_program 里' in str(result), result
    assert '隐私清除' not in str(result)


