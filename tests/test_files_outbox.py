"""ADR-092: files to a QQ group through the outbox -- registration from a task folder, the offer, speak's file part,
the claim against the adapter's declared limit, the bytes in pieces, the receipt and her record, and the 7 days the
bytes are kept. Failure paths first."""
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from asuna import capabilities, media_life, outbound_files, role_tools
from asuna.blobs import BlobStore
from asuna.channels import ChannelServer
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import Denied
from test_adr009_p2 import THINK
from test_group_admin import BOT, GROUP, SCENE, bridge, setup

LIMIT = 1024 * 1024                              # what the test adapter declares for a file
PDF = b'%PDF-1.4\n' + b'a report body line\n' * 400
DECLARED = ['image', 'sticker', 'poke', *capabilities.POINTERS, 'file:%d' % LIMIT]


def mention(key, text='@演示 发个文件'):
    return {'event_id': key, 'scene_id': SCENE, 'person_id': 'qq:20002', 'text': text,
            'group_context': {'wake_reason': 'mentioned_account', 'topic_id': key, 'mentioned_account_ids': [BOT]},
            'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': GROUP},
                        'sender_id': '20002', 'platform_event_id': 'pe-' + key}}


def world(store, declared=DECLARED):
    setup(store, 'member')
    store.config['channels']['qq']['routes']['g']['members'] = {'20002': {'person_id': 'qq:20002'}}
    capabilities.declared(store, 'qq', declared)
    return store.db.scenes.find_one({'_id': SCENE})


def register(store, folder, file='report.pdf', data=PDF, shown=None):
    (folder / file).write_bytes(data)
    task = {'_id': 'task-files', 'scope_key': store.db.scenes.find_one({'_id': SCENE})['scope_key']}
    return outbound_files.register(store, task, folder, {'path': file, **({'name': shown} if shown else {})})


def turn(store, key, parts, **options):
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': parts, **options})])])
    ep = Coordinator(store, lane).ingest(mention(key), persona='P1')
    [(result, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    rows = list(store.db.messages.find({'episode_id': ep['_id'], 'phase': 'SPEAK'}).sort('scene_seq', 1))
    store.db.messages.update_many({'episode_id': ep['_id']}, {'$unset': {'not_before': ''}})
    return ep, result, ok, rows, lane


def expire(store, artifact_id, days_ago=8):
    """The sweep's own removal, as it runs after 7 days."""
    long_ago = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    store.db.artifacts.update_one({'_id': artifact_id}, {'$set': {'created_at': long_ago}})
    return media_life.sweep(store)


# ── the streaming put ───────────────────────────────────────────────
class Counting(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.largest = 0

    def read(self, size=-1):
        data = super().read(size)
        self.largest = max(self.largest, len(data))
        assert size is not None and size >= 0, 'read the whole file at once'
        return data


def test_the_streaming_put_hashes_while_it_copies_and_never_reads_the_whole_file(store):
    world(store)
    data = bytes(range(256)) * (3 * 4096 + 7)                   # 3 MiB and a bit: more than a few GridFS chunks
    handle = Counting(data)
    stored = BlobStore(store).put_stream(handle, 'scene:' + SCENE, 'file', fields={'name': 'x.bin'})
    assert stored['sha256'] == hashlib.sha256(data).hexdigest() and stored['size'] == len(data)
    assert handle.largest < len(data) and handle.largest <= 1024 * 1024
    row = store.db.artifacts.find_one({'_id': stored['artifact_id']})
    assert row['kind'] == 'file' and row['storage'] == 'gridfs' and row['name'] == 'x.bin'
    blobs = BlobStore(store)
    assert blobs.get_range(row['_id'], row['scope_key'], 1000, 5000, operator=True) == data[1000:6000]
    assert blobs.get_range(row['_id'], row['scope_key'], len(data) - 10, 5000, operator=True) == data[-10:]
    with pytest.raises(Denied):
        blobs.get_range(row['_id'], 'scene:elsewhere', 0, 10, operator=True)


def test_a_streaming_put_into_an_unknown_scope_stores_nothing(store):
    world(store)
    before = store.db['artifact_blobs.files'].count_documents({})
    with pytest.raises(Denied, match='ARTIFACT_SCOPE_UNKNOWN'):
        BlobStore(store).put_stream(io.BytesIO(b'abc'), 'scene:nowhere', 'file')
    assert store.db['artifact_blobs.files'].count_documents({}) == before


# ── registration ────────────────────────────────────────────────────
def test_registration_refuses_in_words_like_the_other_file_tools(store, tmp_path):
    world(store)
    task = {'_id': 't', 'scope_key': 'scene:' + SCENE}
    outside = outbound_files.register(store, task, tmp_path, {'path': '../escape.txt'})
    assert outside['error'].startswith('TASK_OPERATION_FAILED: PATH_DENIED')
    missing = outbound_files.register(store, task, tmp_path, {'path': 'nope.pdf'})
    assert missing['error'].startswith('TASK_OPERATION_FAILED: 没有 nope.pdf')
    (tmp_path / 'folder').mkdir()
    assert '是文件夹' in outbound_files.register(store, task, tmp_path, {'path': 'folder'})['error']
    (tmp_path / 'empty.txt').write_bytes(b'')
    assert 'FILE_EMPTY' in outbound_files.register(store, task, tmp_path, {'path': 'empty.txt'})['error']
    (tmp_path / 'ok.txt').write_bytes(b'hello')
    bad = outbound_files.register(store, task, tmp_path, {'path': 'ok.txt', 'name': 'a/b.txt'})
    assert 'FILE_NAME_INVALID' in bad['error'] and '不是路径' in bad['error']
    long = outbound_files.register(store, task, tmp_path, {'path': 'ok.txt', 'name': '长' * 90})
    assert 'FILE_NAME_INVALID' in long['error'] and '270 字节' in long['error']
    unbound = outbound_files.register(store, {'_id': 't'}, tmp_path, {'path': 'ok.txt'})
    assert 'FILE_SCOPE_MISSING' in unbound['error']
    assert 'offer_file 缺参数 path' in outbound_files.register(store, task, tmp_path, {})['error']
    assert store.db.artifacts.count_documents({'kind': 'file'}) == 0


def test_a_name_on_her_private_list_warns_by_category_and_line_and_does_not_block(store, tmp_path, monkeypatch):
    world(store)
    listed = tmp_path / 'words.txt'
    listed.write_text('# list\nperson|示例人名|a test entry\n', encoding='utf-8')
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(listed))
    result = register(store, tmp_path, file='a.pdf', shown='给示例人名的报告.pdf')
    assert result['registered'] is True and result['name_warning'].startswith('名字里有「别带出去」名单上的词：person 类第 2 条')
    assert '示例人名' not in result['name_warning']
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(tmp_path / 'absent.txt'))
    assert register(store, tmp_path, file='b.pdf')['name_check'] == outbound_files.NO_LIST


def test_a_task_file_becomes_a_file_artifact_in_the_tasks_scope(store, tmp_path, monkeypatch):
    world(store)
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(tmp_path / 'absent.txt'))
    result = register(store, tmp_path, file='report.pdf', shown='季度报告.pdf')
    assert result['registered'] and result['type'] == 'PDF 文档' and result['size'] == '7.4 KB'
    assert result['bytes'] == len(PDF) and 'speak 的 file' in result['note']
    row = store.db.artifacts.find_one({'_id': result['artifact_id']})
    assert row['kind'] == 'file' and row['scope_key'] == 'scene:' + SCENE and row['name'] == '季度报告.pdf'
    assert row['sha256'] == hashlib.sha256(PDF).hexdigest() and row['media_type'] == 'application/pdf'
    assert row['source_ids'] == ['task-file:task-files:report.pdf']
    assert row['source'] == {'task_id': 'task-files', 'folder': str(tmp_path.resolve()), 'path': 'report.pdf'}
    unknown = register(store, tmp_path, file='blob.bin', data=b'\x00\x01\x02binary')
    assert unknown['type'] == '类型没认出来'
    assert store.db.artifacts.find_one({'_id': unknown['artifact_id']}).get('media_type') is None


def test_the_type_comes_from_the_bytes():
    sniff = outbound_files.sniff
    docx = b'PK\x03\x04' + b'\x00' * 26 + b'[Content_Types].xml' + b'\x00' * 40 + b'word/document.xml'
    assert sniff(docx) == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert sniff(b'PK\x03\x04' + b'\x00' * 26 + b'[Content_Types].xml xl/workbook.xml').endswith('spreadsheetml.sheet')
    assert sniff(b'PK\x03\x04' + b'\x00' * 26 + b'mimetypeapplication/epub+zip') == 'application/epub+zip'
    assert sniff(b'PK\x03\x04plain zip') == 'application/zip'
    cases = {b'%PDF-1.7': 'application/pdf', b'\x89PNG\r\n\x1a\nxx': 'image/png', b'\xff\xd8\xffxx': 'image/jpeg',
             b'GIF89a': 'image/gif', b'RIFF\x00\x00\x00\x00WEBPVP8 ': 'image/webp', b'\x1f\x8b\x08': 'application/gzip',
             b"7z\xbc\xaf\x27\x1c\x00": 'application/x-7z-compressed', b'Rar!\x1a\x07\x00': 'application/vnd.rar',
             b'ID3\x04': 'audio/mpeg', b'\xff\xfb\x90': 'audio/mpeg', b'\x00\x00\x00\x18ftypmp42': 'video/mp4',
             b'\x00\x00\x00\x18ftypM4A ': 'audio/mp4', b'OggS\x00': 'audio/ogg', b'RIFF\x00\x00\x00\x00WAVEfmt ': 'audio/wav'}
    for head, want in cases.items():
        assert sniff(head) == want, (head, sniff(head))
    assert sniff('<?xml version="1.0"?>\n<svg xmlns="x"></svg>'.encode(), whole=True) == 'image/svg+xml'
    assert sniff(b'<!DOCTYPE html><html></html>', whole=True) == 'text/html'
    assert sniff(b'{"a": [1, 2]}', whole=True) == 'application/json'
    assert sniff(b'{not json', whole=True) == 'text/plain'
    assert sniff('中文的一段话'.encode(), whole=True) == 'text/plain'
    assert sniff('中文'.encode()[:-1]) == 'text/plain'                  # a character cut at the sample's end
    assert sniff('中文'.encode()[:-1], whole=True) is None              # but not at the file's end
    assert sniff(b'\xff\xfe\x00\x00weird') is None and sniff(b'\xff\xf1\x50') is None      # AAC is not MP3


# ── what the adapter declared ───────────────────────────────────────
def test_a_declared_limit_is_kept_with_plain_names_unchanged(store):
    world(store, declared=['image', 'react', 'file:4096', 'voice:abc'])
    assert capabilities.supports(store, 'qq') == ('file', 'image', 'react')       # a bad limit is not declared
    assert capabilities.limit(store, 'qq', 'file') == 4096 and capabilities.limit(store, 'qq', 'image') is None
    assert capabilities.carries(store, {'channel_id': 'qq'}, 'react')
    capabilities.forget()                                       # a restart before the adapter's first claim
    assert capabilities.limit(store, 'qq', 'file') == 4096 and 'file' in capabilities.supports(store, 'qq')
    capabilities.declared(store, 'qq', ['image', 'file:8192'])
    assert capabilities.limit(store, 'qq', 'file') == 8192
    capabilities.declared(store, 'qq', ['image'])                   # an old adapter: plain names, no file
    assert capabilities.limit(store, 'qq', 'file') is None and capabilities.supports(store, 'qq') == ('image',)


# ── the offer and speak's part ──────────────────────────────────────
def test_no_offer_and_no_part_where_the_adapter_does_not_declare_files(store, tmp_path):
    world(store, declared=['image', 'sticker'])
    register(store, tmp_path)
    ep, result, ok, rows, lane = turn(store, 'f-undeclared', [{'kind': 'text', 'text': '在'}])
    assert 'file_artifacts_from_program' not in ep['context']
    speak = next(spec for spec in role_tools.session_specs(store, SCENE) if spec['name'] == 'speak')
    assert 'file' not in speak['parameters']['parts']['items']['properties']['kind']['enum']
    assert 'file_artifacts_from_program' not in speak['parameters']['parts']['items']['properties']['artifact_id']['description']
    _, result, ok, _, _ = turn(store, 'f-undeclared-2', [{'kind': 'file', 'artifact_id': 'blob-x'}])
    assert not ok and '第 1 条 file 这里发不了' in result


def test_a_part_names_only_a_listed_file_within_the_declared_limit(store, tmp_path):
    world(store)
    big = register(store, tmp_path, file='big.bin', data=b'\x00' * (LIMIT + 1))
    _, result, ok, rows, _ = turn(store, 'f-forged', [{'kind': 'file', 'artifact_id': 'blob-' + '0' * 32}])
    assert not ok and 'file_artifacts_from_program' in result and rows == []
    _, result, ok, rows, _ = turn(store, 'f-big', [{'kind': 'file', 'artifact_id': big['artifact_id']}])
    assert not ok and rows == []
    assert '%d 字节' % (LIMIT + 1) in result and '最多 1.0 MB（%d 字节）' % LIMIT in result


def test_a_file_whose_bytes_expired_says_when_and_whether_the_original_is_still_there(store, tmp_path):
    world(store)
    kept = register(store, tmp_path, file='kept.pdf')
    changed = register(store, tmp_path, file='changed.pdf')
    assert expire(store, kept['artifact_id'])['files'] == 1 and expire(store, changed['artifact_id'])['files'] == 1
    (tmp_path / 'changed.pdf').write_bytes(PDF + b'more')
    from asuna import local_time
    row = store.db.artifacts.find_one({'_id': kept['artifact_id']})
    assert row['storage'] == 'removed' and row['bytes_removed_at'] and row['sha256']       # the row stays as the record
    when = local_time.stamp(row['bytes_removed_at'], local_time.zone_of(store, SCENE))
    _, result, ok, rows, _ = turn(store, 'f-old', [{'kind': 'file', 'artifact_id': kept['artifact_id']}])
    assert not ok and rows == []
    assert '这个文件的字节在%s过期了；原文件还在任务文件夹（kept.pdf），让任务重新登记一次就能发' % when in result, result
    _, result, ok, _, _ = turn(store, 'f-old-2', [{'kind': 'file', 'artifact_id': changed['artifact_id']}])
    gone = local_time.stamp(store.db.artifacts.find_one({'_id': changed['artifact_id']})['bytes_removed_at'],
                            local_time.zone_of(store, SCENE))
    assert not ok and ('这个文件的字节在%s过期了，任务文件夹里的原文件也不在了（或已改动），要再发得重新做出来' % gone
                       in result), result


def test_a_group_is_offered_her_files_and_a_file_goes_as_its_own_message(store, tmp_path):
    world(store)
    older = register(store, tmp_path, file='old.txt', data=b'plain words\n')
    newer = register(store, tmp_path, file='report.pdf', shown='季度报告.pdf')
    ep, result, ok, rows, lane = turn(store, 'f-send', [{'kind': 'text', 'text': '给'},
                                                        {'kind': 'file', 'artifact_id': newer['artifact_id']}])
    offered = ep['context']['file_artifacts_from_program']
    assert [item['artifact_id'] for item in offered['items']] == [newer['artifact_id'], older['artifact_id']]
    first = offered['items'][0]
    assert first['name'] == '季度报告.pdf' and first['size'] == '7.4 KB' and first['type'] == 'PDF 文档'
    assert offered['items'][1]['type'] == '文本' and first['registered_at']
    assert ok and '2 file「季度报告.pdf」' in result['note'], result
    assert [row['text'] for row in rows] == ['给', '[文件：季度报告.pdf，7.4 KB]']
    assert rows[1]['file'] == {'artifact_id': newer['artifact_id'], 'name': '季度报告.pdf', 'media_type': 'application/pdf',
                               'sha256': hashlib.sha256(PDF).hexdigest(), 'size': len(PDF)}
    assert 'attachment' not in rows[1] and role_tools.spoken(store, ep)[0] == 1       # a file is not one of her lines
    speak = next(spec for spec in role_tools.session_specs(store, SCENE) if spec['name'] == 'speak')
    assert 'file' in speak['parameters']['parts']['items']['properties']['kind']['enum']


def test_the_offer_lists_the_newest_eight_with_bytes(store, tmp_path):
    world(store)
    made = [register(store, tmp_path, file='f%d.txt' % n, data=b'n%d\n' % n)['artifact_id'] for n in range(10)]
    for n, artifact in enumerate(made):
        store.db.artifacts.update_one({'_id': artifact}, {'$set': {'created_at': '2026-10-01T00:%02d:00+00:00' % n}})
    store.db.artifacts.update_one({'_id': made[9]}, {'$set': {'storage': 'removed'}})
    scene = store.db.scenes.find_one({'_id': SCENE})
    listed = [item['artifact_id'] for item in outbound_files.offer(store, scene, 'public')['items']]
    assert listed == made[8::-1][:8]


def test_files_go_to_groups_only(store):
    world(store)
    store.put('scenes', {'_id': 'qq:%s:dm:20002' % BOT, 'kind': 'dm', 'scope_key': 'scene:dm-file',
                         'channel_id': 'qq', 'policy_epoch': 1, 'sequence': 0})
    store.config['channels']['qq']['routes']['d'] = {'scene_id': 'qq:%s:dm:20002' % BOT, 'sender_id': '20002',
                                                     'person_id': 'qq:20002', 'target': {'type': 'dm', 'id': '20002'}}
    dm = store.db.scenes.find_one({'_id': 'qq:%s:dm:20002' % BOT})
    assert 'file' not in role_tools.speak_kinds(store, dm)
    assert outbound_files.offer(store, dm, 'public') is None
    assert 'file' in role_tools.speak_kinds(store, store.db.scenes.find_one({'_id': SCENE}))


# ── the claim, the bytes and the receipt ────────────────────────────
def queued_file(store, tmp_path, key, **register_args):
    registered = register(store, tmp_path, **register_args)
    _, _, ok, rows, _ = turn(store, key, [{'kind': 'file', 'artifact_id': registered['artifact_id']},
                                          {'kind': 'text', 'text': '看看'}])
    assert ok
    return registered, rows


def test_a_file_row_on_an_adapter_that_does_not_declare_files_fails_and_cancels_the_rest(store, tmp_path):
    world(store)
    _, rows = queued_file(store, tmp_path, 'f-claim-undeclared')
    assert bridge(store).claim('qq', supports=['image', 'sticker'])['items'] == []
    first, second = [store.db.messages.find_one({'_id': row['_id']}) for row in rows]
    assert first['delivery_state'] == 'FAILED' and first['failure'] == 'CHANNEL_DOES_NOT_DECLARE_FILE'
    assert second['delivery_state'] == 'CANCELLED_AFTER_FAILURE'


def test_a_file_over_the_limit_declared_at_claim_time_fails_with_both_numbers(store, tmp_path):
    world(store)
    _, rows = queued_file(store, tmp_path, 'f-claim-limit')
    assert bridge(store).claim('qq', supports=['file:100'])['items'] == []
    row = store.db.messages.find_one({'_id': rows[0]['_id']})
    assert row['delivery_state'] == 'FAILED' and row['failure'] == 'FILE_OVER_CHANNEL_LIMIT'
    assert row['file_limit'] == {'bytes': len(PDF), 'limit': 100} and '最多 100 字节（100 字节）' in row['failure_detail']


@pytest.mark.parametrize('present', [True, False])
def test_a_claimed_file_whose_bytes_vanished_fails_as_expired_saying_whether_the_original_is_there(store, tmp_path,
                                                                                                    present):
    world(store)
    registered, rows = queued_file(store, tmp_path, 'f-claim-gone-%s' % present)
    item = store.db.artifacts.find_one({'_id': registered['artifact_id']})
    from bson import ObjectId
    BlobStore(store).bucket.delete(ObjectId(item['gridfs_id']))
    store.db.artifacts.update_one({'_id': item['_id']}, {'$set': {'storage': 'removed', 'bytes_removed_at': '2026-10-20T01:00:00+00:00'}})
    if not present:
        (tmp_path / 'report.pdf').unlink()
    assert bridge(store).claim('qq', supports=DECLARED)['items'] == []
    row = store.db.messages.find_one({'_id': rows[0]['_id']})
    assert row['delivery_state'] == 'FAILED' and row['failure'] == 'FILE_BYTES_EXPIRED'
    assert row['source_present'] is present
    assert ('原文件还在任务文件夹（report.pdf）' if present else '原文件也不在了') in row['failure_detail']


def piece_url(server, item, offset, length, artifact=None):
    return 'http://127.0.0.1:%d/v1/channels/qq/outbox/%s/attachment?attempt_id=%s&artifact_id=%s&offset=%d&length=%d' % (
        server.server.server_address[1], item['publication_id'], item['attempt_id'],
        artifact or item['file']['artifact_id'], offset, length)


def fetch(url):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + 'x' * 24})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers.get('Content-Type'), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get('Content-Type'), exc.read()


def test_the_bytes_go_in_pieces_under_the_publication_fences(store, tmp_path):
    world(store)
    data = bytes(range(256)) * 300                                  # 76,800 bytes
    registered, rows = queued_file(store, tmp_path, 'f-pieces', file='data.bin', data=data)
    channels = bridge(store)
    [item] = channels.claim('qq', supports=DECLARED)['items']
    assert item['text'] == '' and item['file']['artifact_id'] == registered['artifact_id']
    assert item['file']['size'] == len(data) and item['file']['name'] == 'data.bin' and item['file']['media_type'] is None
    server = ChannelServer(channels)
    try:
        refused = {
            'attempt': fetch(piece_url(server, {**item, 'attempt_id': 'other'}, 0, 10)),
            'artifact': fetch(piece_url(server, item, 0, 10, artifact='blob-other')),
            'too_long': fetch(piece_url(server, item, 0, outbound_files.PIECE_MAX + 1)),
            'past_end': fetch(piece_url(server, item, len(data), 10)),
        }
        assert {name: code for name, (code, _, _) in refused.items()} == {'attempt': 403, 'artifact': 403,
                                                                         'too_long': 400, 'past_end': 400}
        assert b'PUBLICATION_ATTEMPT_MISMATCH' in refused['attempt'][2] and b'FILE_PIECE_INVALID' in refused['past_end'][2]
        got = []
        for offset in range(0, len(data), 30000):
            code, kind, body = fetch(piece_url(server, item, offset, 30000))
            assert code == 200 and kind == 'application/octet-stream'
            got.append(body)
        assert b''.join(got) == data and [len(part) for part in got] == [30000, 30000, 16800]
        store.db.artifacts.update_one({'_id': registered['artifact_id']}, {'$set': {'storage': 'removed'}})
        code, _, body = fetch(piece_url(server, item, 0, 10))
        assert code == 403 and b'FILE_BYTES_EXPIRED' in body
    finally:
        server.close()


def test_a_delivered_file_needs_no_message_id_and_keeps_its_bytes_seven_days_from_then(store, tmp_path):
    world(store)
    registered, rows = queued_file(store, tmp_path, 'f-receipt')
    channels = bridge(store)
    [item] = channels.claim('qq', supports=DECLARED)['items']
    done = channels.receipt('qq', item['publication_id'], {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                                                           'response': {'group_file': {'retcode': 0, 'data': {'file_id': '/x'}}}})
    assert done == {'status': 'DELIVERED'}
    row = store.db.messages.find_one({'_id': item['publication_id']})
    assert row['platform_message_id'] is None and row['platform_receipt']['response']['group_file']['data']['file_id'] == '/x'
    artifact = store.db.artifacts.find_one({'_id': registered['artifact_id']})
    assert artifact['last_sent_at'] >= artifact['created_at']
    # Registered 10 days ago but sent just now: kept.
    store.db.artifacts.update_one({'_id': artifact['_id']}, {'$set': {'created_at': '2026-01-01T00:00:00+00:00'}})
    assert media_life.sweep(store)['files'] == 0
    assert store.db.artifacts.find_one({'_id': artifact['_id']})['storage'] == 'gridfs'
    # Her next turn reads her record line like her other lines.
    ep, _, _, _, _ = turn(store, 'f-after', [{'kind': 'text', 'text': '发了'}])
    assert '[文件：report.pdf，7.4 KB]' in json.dumps(ep['context'], ensure_ascii=False)


def test_a_failed_upload_shows_the_platforms_reason_in_her_next_turn(store, tmp_path):
    world(store)
    _, rows = queued_file(store, tmp_path, 'f-failed')
    channels = bridge(store)
    [item] = channels.claim('qq', supports=DECLARED)['items']
    assert channels.receipt('qq', item['publication_id'], {
        'attempt_id': item['attempt_id'], 'status': 'failed',
        'response': {'reason': 'file_upload_failed', 'retcode': 1200, 'platform': '群文件空间不足'}}) == {'status': 'FAILED'}
    assert store.db.messages.find_one({'_id': rows[1]['_id']})['delivery_state'] == 'CANCELLED_AFTER_FAILURE'
    ep, _, _, _, _ = turn(store, 'f-failed-next', [{'kind': 'text', 'text': '嗯'}])
    said = json.dumps(ep['context'], ensure_ascii=False)
    assert '没发出去：平台说：群文件空间不足' in said
    assert outbound_files.failure_words({'failure': 'FILE_BYTES_EXPIRED', 'failure_detail': '字节过期了'}) == '字节过期了'
    assert outbound_files.failure_words({'failure': 'CHANNEL_DOES_NOT_DECLARE_FILE'}) == '这条腿发不了文件'


# ── retention ───────────────────────────────────────────────────────
def test_the_sweep_removes_a_files_bytes_after_seven_days_and_keeps_its_row(store, tmp_path):
    world(store)
    old = register(store, tmp_path, file='old.pdf')['artifact_id']
    fresh = register(store, tmp_path, file='fresh.pdf')['artifact_id']
    going = register(store, tmp_path, file='going.pdf')['artifact_id']
    long_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    store.db.artifacts.update_many({'_id': {'$in': [old, going]}}, {'$set': {'created_at': long_ago}})
    store.db.messages.insert_one({'_id': 'out-going', 'schema_version': 1, 'direction': 'outbound',
                                  'delivery_state': 'QUEUED_EXTERNAL', 'file': {'artifact_id': going}})
    gridfs_id = store.db.artifacts.find_one({'_id': old})['gridfs_id']
    removed = media_life.sweep(store)
    assert removed['files'] == 1 and removed['bytes'] == len(PDF)
    from bson import ObjectId
    row = store.db.artifacts.find_one({'_id': old})
    assert row['storage'] == 'removed' and row['bytes_removed_at'] and 'gridfs_id' not in row
    assert store.db['artifact_blobs.files'].count_documents({'_id': ObjectId(gridfs_id)}) == 0
    assert store.db.artifacts.find_one({'_id': fresh})['storage'] == 'gridfs'
    assert store.db.artifacts.find_one({'_id': going})['storage'] == 'gridfs'       # a message on its way keeps it
    assert media_life.sweep(store)['files'] == 0                                       # once
    assert media_life.life({'source_ids': ['task-file:t:x.pdf']}) == media_life.OFFERED


# ── the action brain's tool ─────────────────────────────────────────
def test_offer_file_is_a_tool_of_every_task_and_registers_in_the_tasks_own_scope(store):
    from test_engineering_m3 import task_setup
    from asuna.tasks import ToolFailed
    service, task, broker, work = task_setup(store)
    try:
        assert 'offer_file' in task['allowed_capabilities']
        result = broker.call('s-test', 'offer', 'offer_file', {'path': 'a.txt', 'name': '原件.txt'})
        row = store.db.artifacts.find_one({'_id': result['artifact_id']})
        assert row['kind'] == 'file' and row['scope_key'] == task['scope_key'] and row['name'] == '原件.txt'
        assert result['type'] == '文本' and result['bytes'] == len('controlled original')
        with pytest.raises(ToolFailed, match='PATH_DENIED'):
            broker.call('s-test', 'escape', 'offer_file', {'path': '../outside.txt'})
    finally:
        broker.close()
