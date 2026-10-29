"""ADR-105: an operator erasure deletes a conversation's stored bytes and marks each of its rows `erased`; whatever
looks one up by its id answers with the one sentence, never "not found", and a sending tool says it in the very call
that names the erased file or picture. A row outside the caller's fence is refused as before, so the sentence never
tells anyone that a row they may not see exists."""
import ast
import base64
from pathlib import Path

import pytest

from asuna import blobs as blobs_mod, local_time, media_life, outbound_files, outbound_media, stickers
from asuna.blobs import ERASED_WORDS, BlobStore
from asuna.config import ROOT
from asuna.state import Denied

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))


def scopes(store):
    rows = list(store.db.scenes.find({}, {'_id': 1, 'scope_key': 1}).sort('_id', 1))
    return rows[0], rows[1]


def picture(store, scope, source='in-ep-1', body=PNG):
    return BlobStore(store).put(body + source.encode(), scope, 'image', source_ids=[source])['artifact_id']


def sentence(store, row_id, scene_id, what):
    """The ADR-105 sentence, with the row's erased_at on the clock of the conversation it is said in."""
    row = store.db.artifacts.find_one({'_id': row_id})
    return ERASED_WORDS % (what, local_time.stamp(row['erased_at'], local_time.zone_of(store, scene_id)))


# ── marking ─────────────────────────────────────────────────────────
def test_an_erasure_marks_each_row_of_its_scope_and_no_other(store):
    here, there = scopes(store)
    blobs = BlobStore(store)
    kept_name = picture(store, here['scope_key'], 'in-ep-a')
    store.db.artifacts.update_one({'_id': kept_name}, {'$set': {'name': 'notes.md'}})
    expired = picture(store, here['scope_key'], 'in-ep-b')
    blobs_mod.delete(store, store.db.artifacts.find_one({'_id': expired})['gridfs_id'])   # as the sweep does
    store.db.artifacts.update_one({'_id': expired}, {'$set': {'storage': 'removed'}, '$unset': {'gridfs_id': ''}})
    other = picture(store, there['scope_key'], 'in-ep-c')
    store.db.artifacts.insert_one({'_id': 'not-a-blob', 'schema_version': 1, 'kind': 'channel_admission',
                                  'scope_key': here['scope_key']})
    deleted = blobs.erase_scope(here['scope_key'], 'erase-test')
    assert deleted == 1, 'the one GridFS file of the scope (the removed row had none left)'
    for row_id in (kept_name, expired):
        row = store.db.artifacts.find_one({'_id': row_id})
        assert row['storage'] == 'erased' and row['erased_at'] and row['deletion_id'] == 'erase-test'
        assert 'gridfs_id' not in row
    assert store.db.artifacts.find_one({'_id': kept_name})['name'] == 'notes.md', 'the row keeps its name (the owner)'
    assert store.db.artifacts.find_one({'_id': other})['storage'] == 'gridfs'
    assert 'storage' not in store.db.artifacts.find_one({'_id': 'not-a-blob'})
    files = store.db['artifact_blobs.files']
    assert files.count_documents({'metadata.scope_key': here['scope_key']}) == 0
    assert files.count_documents({'metadata.scope_key': there['scope_key']}) == 1


def test_an_erasure_stopped_after_the_bytes_is_finished_by_running_it_again(store):
    """Bytes gone, rows not yet marked: a reader says the bytes are missing in words; the second run marks the rows."""
    here, _ = scopes(store)
    blobs = BlobStore(store)
    row_id = picture(store, here['scope_key'])
    blobs_mod.delete(store, store.db.artifacts.find_one({'_id': row_id})['gridfs_id'])
    with pytest.raises(ValueError, match='ARTIFACT_BYTES_MISSING') as missing:
        blobs.get(row_id, here['scope_key'], operator=True)
    assert '不是没有内容' in str(missing.value)
    assert blobs.erase_scope(here['scope_key'], 'erase-again') == 0
    with pytest.raises(Denied, match='ARTIFACT_ERASED'):
        blobs.get(row_id, here['scope_key'], operator=True)


def test_privacy_erasure_marks_the_rows_with_its_own_deletion_id(store):
    from asuna.privacy import PrivacyService
    from test_engineering_m6 import event, normal
    c, _ = normal(store)
    c.ingest(event())
    memory = store.db.memory_units.find_one({'_id': 'M09'})
    row_id = picture(store, memory['scope_key'])
    store.db.artifacts.update_one({'_id': row_id}, {'$set': {'name': 'a.png'}})
    store.db.artifacts.insert_one({'_id': 'task-output', 'schema_version': 1, 'scope_key': memory['scope_key'],
                                   'kind': 'task_report', 'state': 'DONE', 'text': 'a paraphrase of the chat'})
    result = PrivacyService(store).delete_memory('M09', operator=True)
    row = store.db.artifacts.find_one({'_id': row_id})
    assert row['storage'] == 'erased' and row['deletion_id'] == result['deletion_id']
    assert row['name'] == 'a.png' and row['kind'] == 'image' and row['size'] and row['created_at'], \
        'the marked row keeps its name, size and when (ADR-105)'
    other = store.db.artifacts.find_one({'_id': 'task-output'})
    assert other['state'] == 'INVALIDATED' and other['text'] == '[deleted]', 'any other row of the scope is redacted'


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


def test_the_same_bytes_after_an_erasure_are_stored_anew_never_matched_to_the_erased_row(store):
    here, _ = scopes(store)
    blobs = BlobStore(store)
    first = blobs.put_once(PNG, here['scope_key'], 'image', source_ids=['in-ep-1'])['artifact_id']
    blobs.erase_scope(here['scope_key'], 'erase-test')
    again = blobs.put_once(PNG, here['scope_key'], 'image', source_ids=['in-ep-2'])
    assert again['artifact_id'] != first and not again.get('deduplicated')


def test_the_sweep_passes_an_erased_row(store):
    from datetime import datetime, timedelta, timezone
    here, _ = scopes(store)
    row_id = picture(store, here['scope_key'])
    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store.db.artifacts.update_one({'_id': row_id}, {'$set': {'created_at': long_ago}})
    BlobStore(store).erase_scope(here['scope_key'], 'erase-test')
    removed = media_life.sweep(store)
    assert not media_life.worth_recording(removed), removed
    assert store.db.artifacts.find_one({'_id': row_id})['storage'] == 'erased'


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


def test_a_local_picture_whose_bytes_were_erased_says_so_when_read(store, tmp_path):
    from asuna.vision import local_uploads, media_note, read_image_for_task
    from test_local_images import world
    scene, chat = world(store, tmp_path)
    media = local_uploads(store, scene['scope_key'], [{'data': base64.b64encode(PNG).decode(), 'name': 'a.png'}],
                          'msg-e')
    chat.submit('看看', event_id='msg-e', native_session_id='s-e', native_message_ids=['msg-e'], media=media)
    note = media_note(store.db.messages.find_one({'event.event_id': 'msg-e'}), store.config)
    BlobStore(store).erase_scope(scene['scope_key'], 'erase-test')
    task = {'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    with pytest.raises(Denied) as erased:
        read_image_for_task(store, BlobStore(store), task, store.config, {'ref': note['items'][0]['ref']})
    assert str(erased.value) == 'ARTIFACT_ERASED: ' + sentence(store, media['items'][0]['artifact_id'], 'dm-a', '张图')


# ── sending a picture ───────────────────────────────────────────────
def imported(store, tmp_path, register='foreign'):
    """A picture in the owner's local chat, readable from his QQ chat; by default not one she made, so the fences
    of the conversation apply to it."""
    from test_adr009_p2 import owner
    from test_outbound_image import LOCAL, LOCAL_SCOPE, QQ, channel_scene, import_bytes, link
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    made = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path, register=register)
    return made['artifact']['artifact_id'], LOCAL_SCOPE, QQ


def another_offered(store, qq):
    """One more picture, in the QQ chat's own scope, so this turn offers a picture and attach_image is there."""
    return outbound_media.register_imported_image(store, 'scene:' + qq, PNG + b'other', source='upload:other')


def test_attach_image_names_an_erased_picture_and_hears_the_sentence_in_that_call(store, tmp_path):
    from test_outbound_image import attach_calls, turn
    art, scope, qq = imported(store, tmp_path)
    another_offered(store, qq)
    BlobStore(store).erase_scope(scope, 'erase-test')
    offer = outbound_media.offer(store, store.config, store.db.scenes.find_one({'_id': qq}), 'owner_private', 'A')
    assert art not in {item['artifact_id'] for item in offer['items']}, 'an erased picture leaves the offer by itself'
    coordinator, ep = turn(store, attach={'artifact_id': art, 'why': '给你看看'})
    [(result, ok)] = attach_calls(coordinator)
    assert not ok and sentence(store, art, qq, '张图') in str(result), result
    assert not (store.db.episodes.find_one({'_id': ep['_id']}) or {}).get('attachment')


def test_speak_with_an_erased_picture_hears_the_sentence_in_that_call(store, tmp_path, monkeypatch):
    from asuna import channel_kinds
    from test_outbound_image import model, turn
    art, scope, qq = imported(store, tmp_path)
    monkeypatch.setattr(channel_kinds, 'reply_parts', lambda scene_id: ('text', 'picture') if scene_id == qq else ())
    BlobStore(store).erase_scope(scope, 'erase-test')
    from asuna.coordinator import Coordinator
    from asuna.ingress import persist_input
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr009_p2 import THINK
    store.config['persona_model'] = model()
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'picture', 'artifact_id': art}]})])])
    event = {'event_id': 'pic-e', 'scene_id': qq, 'person_id': 'A', 'text': '图呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': {'type': 'dm', 'id': 'peer'},
                         'platform_event_id': 'p-pic-e'}}
    persist_input(store, event, managed=True)
    Coordinator(store, lane).ingest(event)
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert not ok and sentence(store, art, qq, '张图') in str(result), result


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


def test_a_picture_erased_after_it_was_claimed_is_refused_at_the_byte_endpoint_with_the_sentence(store, tmp_path):
    from test_outbound_image import attach_calls, bridge, speak_rows, turn
    art, scope, qq = imported(store, tmp_path)
    coordinator, ep = turn(store, attach={'artifact_id': art, 'why': '给你看看'})
    assert attach_calls(coordinator)[0][1] and speak_rows(store, ep['_id'])
    server = bridge(store)
    item = server.claim('replay', supports=['image'])['items'][0]
    BlobStore(store).erase_scope(scope, 'erase-test')
    with pytest.raises(Denied) as erased:
        server.attachment('replay', item['publication_id'], {'attempt_id': [item['attempt_id']]})
    assert sentence(store, art, qq, '张图') in str(erased.value)


# ── sending a file ──────────────────────────────────────────────────
def test_speak_with_an_erased_file_hears_the_sentence_in_that_call(store, tmp_path):
    from test_files_outbox import SCENE, register, turn, world
    scene = world(store)
    registered = register(store, tmp_path)
    BlobStore(store).erase_scope(scene['scope_key'], 'erase-test')
    assert outbound_files.offer(store, store.db.scenes.find_one({'_id': SCENE})) is None, \
        'an erased file leaves the offer by itself'
    _, result, ok, rows, _ = turn(store, 'f-erased', [{'kind': 'file', 'artifact_id': registered['artifact_id']}])
    assert not ok and rows == []
    assert sentence(store, registered['artifact_id'], SCENE, '个文件') in result, result


def test_a_file_erased_on_its_way_fails_its_claim_with_the_sentence_as_its_detail(store, tmp_path):
    from test_files_outbox import DECLARED, SCENE, bridge, queued_file, world
    scene = world(store)
    registered, rows = queued_file(store, tmp_path, 'f-erased-claim')
    BlobStore(store).erase_scope(scene['scope_key'], 'erase-test')
    assert bridge(store).claim('qq', supports=DECLARED, lane='bulk')['items'] == []
    row = store.db.messages.find_one({'_id': rows[0]['_id']})
    words = sentence(store, registered['artifact_id'], SCENE, '个文件')
    assert row['delivery_state'] == 'FAILED' and row['failure'] == 'FILE_ERASED' and row['failure_detail'] == words
    assert words in outbound_files.failure_words(row)


def test_the_file_byte_endpoint_answers_the_sentence_for_an_erased_file(store, tmp_path):
    from test_files_outbox import SCENE, queued_file, world
    scene = world(store)
    registered, rows = queued_file(store, tmp_path, 'f-erased-piece')
    row = store.db.messages.find_one({'_id': rows[0]['_id']})
    BlobStore(store).erase_scope(scene['scope_key'], 'erase-test')
    with pytest.raises(Denied) as erased:
        outbound_files.serve_piece(store, row, {'offset': ['0'], 'length': ['16']})
    assert str(erased.value) == 'ARTIFACT_ERASED: ' + sentence(store, registered['artifact_id'], SCENE, '个文件')


# ── her shelf ───────────────────────────────────────────────────────
def test_keeping_her_own_erased_drawing_as_a_sticker_says_it_was_erased(store):
    here, _ = scopes(store)
    row_id = picture(store, here['scope_key'], outbound_media.PRODUCED_SOURCE + 'image:x')
    BlobStore(store).erase_scope(here['scope_key'], 'erase-test')
    ep = {'scene_id': here['_id'], 'scope_key': here['scope_key'], 'policy_epoch': 1}
    with pytest.raises(Denied) as erased:
        stickers.keep(store, BlobStore(store), ep, 'P1', {'ref': row_id, 'name': '画的', 'when': '开心'}, store.config)
    assert str(erased.value) == 'ARTIFACT_ERASED: ' + sentence(store, row_id, here['_id'], '张图')


# ── every lookup by id ──────────────────────────────────────────────
def _stored_mark(side):
    """'gridfs', or the owner's name for it (records.artifacts.STORED)."""
    return (isinstance(side, ast.Constant) and side.value == 'gridfs') or (
        isinstance(side, ast.Attribute) and side.attr == 'STORED')


def _judges_storage(fn):
    """Whether a function compares a value with 'gridfs' (or the owner's STORED), or looks an artifacts row up by
    `_id` filtered on storage (the owner's `get` with a storage, or a direct read)."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and any(_stored_mark(side) for side in (node.left, *node.comparators)):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'artifact_records'
                and any(keyword.arg == 'storage' for keyword in node.keywords)):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'find_one'
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'artifacts'
                and node.args and isinstance(node.args[0], ast.Dict)):
            keys = {key.value for key in node.args[0].keys if isinstance(key, ast.Constant)}
            if {'_id', 'storage'} <= keys:
                return True
    return False


def lookups_without_the_mark(sources):
    """(path, function) for each function that judges a row's storage by its id but never names the erased mark.
    A list of everything (offers, the sweep) reads `gridfs` with `find` and is not a lookup by id."""
    marks = {'erased', 'refuse_erased', 'erased_words', 'refuse_erased_named'}
    missing = []
    for path, text in sources:
        for fn in ast.walk(ast.parse(text)):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _judges_storage(fn):
                names = {getattr(node, 'id', None) or getattr(node, 'attr', None) for node in ast.walk(fn)}
                if not names & marks:
                    missing.append((path, fn.name))
    return missing


def test_every_lookup_by_id_that_judges_storage_handles_the_erased_mark():
    sources = [(path.relative_to(ROOT).as_posix(), path.read_text(encoding='utf-8'))
               for path in sorted((ROOT / 'src' / 'asuna').rglob('*.py'))]
    assert len(sources) > 50
    assert lookups_without_the_mark(sources) == []
    forgot = ("def look(store, key):\n"
              "    row = store.db.artifacts.find_one({'_id': key})\n"
              "    if row.get('storage') != 'gridfs':\n"
              "        raise ValueError('gone')\n")
    filtered = "def look(store, key):\n    return store.db.artifacts.find_one({'_id': key, 'storage': 'gridfs'})\n"
    owned = ("def look(store, key):\n"
             "    row = artifact_records.get(store, key)\n"
             "    if row.get('storage') != artifact_records.STORED:\n"
             "        raise ValueError('gone')\n")
    asked = "def look(store, key):\n    return artifact_records.get(store, key, storage=artifact_records.STORED)\n"
    assert lookups_without_the_mark([('a.py', forgot), ('b.py', filtered), ('c.py', owned), ('d.py', asked)]) == [
        ('a.py', 'look'), ('b.py', 'look'), ('c.py', 'look'), ('d.py', 'look')], 'the test itself bites'


# ── two sentences, by a fact on the row ─────────────────────────────
def test_the_two_shapes_of_one_kind_read_differently_and_say_whose_cause_is_whose(store):
    """Bytes the erasure deleted, and bytes that had expired before it, get two different sentences: merged into one,
    the expired row would be told the erasure took its bytes (Xiaoman's review of 94bb3ea3a92d)."""
    here, _ = scopes(store)
    blobs = BlobStore(store)
    deleted, expired = picture(store, here['scope_key'], 'in-ep-d'), picture(store, here['scope_key'], 'in-ep-x')
    blobs_mod.delete(store, store.db.artifacts.find_one({'_id': expired})['gridfs_id'])
    store.db.artifacts.update_one({'_id': expired}, {'$set': {'storage': 'removed',
                                                              'bytes_removed_at': '2026-10-20T01:00:00+00:00'},
                                                     '$unset': {'gridfs_id': ''}})
    blobs.erase_scope(here['scope_key'], 'erase-test')
    first, second = (blobs_mod.erased_words(store, store.db.artifacts.find_one({'_id': row_id}), here['_id'])
                     for row_id in (deleted, expired))
    zone = local_time.zone_of(store, here['_id'])
    erased_at = local_time.stamp(store.db.artifacts.find_one({'_id': expired})['erased_at'], zone)
    assert first != second
    assert first == sentence(store, deleted, here['_id'], '张图') and '被隐私清除删掉' in first
    assert second == blobs_mod.ERASED_AFTER_EXPIRY_WORDS % (
        '张图', local_time.stamp('2026-10-20T01:00:00+00:00', zone), erased_at)
    assert '到期删掉' in second and '被隐私清除删掉' not in second, 'the expiry, not the erasure, took those bytes'
    assert first.endswith('这一份不会再变回可读。') and second.endswith('这一份不会再变回可读。'), \
        'what the erasure closes is this row, never the file: a task may register its copy again'
    assert not {'你', '我'} & set(first + second), 'neither sentence speaks as or to anyone'


def test_speak_naming_another_conversations_erased_picture_hears_only_the_offer_refusal(store, tmp_path,
                                                                                        monkeypatch):
    """A picture of a conversation this one may not use: erased or not, the answer is the offer's own refusal, so the
    sentence never tells this conversation that the row exists."""
    from asuna import channel_kinds
    from asuna.coordinator import Coordinator
    from asuna.ingress import persist_input
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr009_p2 import THINK
    from test_outbound_image import model
    _, _, qq = imported(store, tmp_path)
    other = store.db.scenes.find_one({'_id': {'$nin': [qq, 'dm-a']}, 'scope_key': {'$exists': True}})
    foreign = outbound_media.register_imported_image(store, other['scope_key'], PNG + b'b', source='upload:b')
    foreign = foreign['artifact_id'] if isinstance(foreign, dict) else foreign
    BlobStore(store).erase_scope(other['scope_key'], 'erase-test')
    assert blobs_mod.erased(store.db.artifacts.find_one({'_id': foreign}))
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


# ── a sticker she drew ──────────────────────────────────────────────
def drawn_sticker(store, ep_scene='dm-a'):
    """A picture she drew in dm-a, kept on her shelf as 画的; then dm-a's bytes are erased."""
    scene = store.db.scenes.find_one({'_id': ep_scene})
    row_id = picture(store, scene['scope_key'], outbound_media.PRODUCED_SOURCE + 'image:drawn')
    ep = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    stickers.keep(store, BlobStore(store), ep, 'P1', {'ref': row_id, 'name': '画的', 'when': '开心'}, store.config)
    BlobStore(store).erase_scope(scene['scope_key'], 'erase-test')
    return row_id, scene


def test_speak_with_a_sticker_whose_drawing_was_erased_hears_the_sentence_and_sends_nothing(store, monkeypatch):
    from test_adr009_p5_speak import channel_scene, model, outbound, turn
    store.config['persona_model'] = model(2)
    channel_scene(store, monkeypatch)
    row_id, scene = drawn_sticker(store)
    _, ep, lane = turn(store, calls=[('speak', {'parts': [{'kind': 'sticker', 'name': '画的'}]})])
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak'][:1]
    assert not ok and sentence(store, row_id, scene['_id'], '张图') in str(result), result
    assert outbound(store, ep['_id']) == []


def test_the_shelf_and_the_review_mark_an_erased_drawing_in_a_field_of_its_own_and_keep_it(store):
    from datetime import datetime, timezone
    row_id, scene = drawn_sticker(store)
    listed = stickers.block(store, 'P1', scene, at_home=True)
    [item] = [item for item in listed['items'] if item['sticker'] == '画的']
    assert item['picture'] == sentence(store, row_id, scene['_id'], '张图') and 'ref' not in item
    assert listed['gone'] == stickers.GONE_WORDS
    review = stickers.review_block(store, 'P1', datetime.now(timezone.utc))
    assert review['items'][0]['sticker'] == '画的' and '被隐私清除删掉' in review['items'][0]['why']
    assert review['gone'] == stickers.GONE_WORDS
    assert stickers.find(store, 'P1', '画的'), 'the program never drops it: that is hers'
    assert stickers.send_block(store, 'P1')['names'] == '画的', 'the names she copies stay as she wrote them'
