"""ADR-120 landing 4 (D2), on the fixture world in memory (test_whose's home: the Web chat at home, g1 an outside group):
web_fetch's save through the broker, with the bytes the plugin hands over. Only what would fail silently and costly: a
saved file that lands in another conversation, overwrites another file, is kept when it should not be, loses a sent
picture's bytes, or is saved where the access table says no."""
import base64
import hashlib
import itertools

import pytest

from asuna import access, media_life, outbound_files, outbound_media, own_files, tasks, visibility
from asuna.records import artifacts as artifact_records
from asuna.records import scenes as scene_records
from asuna.state import Denied
from asuna.store.words import Set
from test_access import broker_for, running
from test_own_files import PNG, denied_rows
from test_whose import LOCAL, OWNER, coordinator, home, turn  # noqa: F401  (home, coordinator: fixtures)

PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
OLD = '2026-01-01T00:00:00+00:00'
CALLS = itertools.count(1)


def body(data, url='https://example.org/files/x'):
    """What the plugin hands over beside the call's arguments (fetch.js registerWebFetch)."""
    return {'url': url, 'status': 200, 'content_type': 'application/octet-stream',
            'data': base64.b64encode(data).decode('ascii')}


def save(broker, args, data, url='https://example.org/files/x'):
    return broker.call('session', 'call-%d' % next(CALLS), 'web_fetch',
                       {'url': url, **args}, body=body(data, url))


def a_task(coordinator, scene_id, person, key):
    return running(coordinator.store, coordinator.delegate(turn(coordinator.store, scene_id, person, key), 'c-' + key,
                                                           '标题', '交代'))


def test_a_saved_picture_and_file_are_this_conversation_s_and_offered_by_their_id(coordinator, tmp_path, monkeypatch):
    store = coordinator.store
    task = a_task(coordinator, LOCAL, OWNER, 'd1')
    broker = broker_for(store, task, tmp_path)
    picture = save(broker, {'save': True}, PNG, 'https://example.org/img/%E7%8C%AB?size=1')
    assert picture['saved'].startswith('存好了：猫.png（') and picture['saved'].endswith('，PNG 图片，记在家里·私聊）')
    assert picture['path'] == '/task/downloads/猫.png' and (tmp_path / 'downloads' / '猫.png').read_bytes() == PNG
    assert picture['sha256'] == hashlib.sha256(PNG).hexdigest()
    row = artifact_records.get(store, picture['artifact_id'])
    assert (row['kind'], row['scope_key'], row['name']) == ('image', task['scope_key'], '猫.png')
    assert row['source_ids'][0].startswith('download:') and media_life.life(row) == media_life.OFFERED
    report = save(broker, {'save': '报告.pdf'}, PDF)
    row = artifact_records.get(store, report['artifact_id'])
    assert (row['kind'], row['media_type'], row['name']) == ('file', 'application/pdf', '报告.pdf')
    assert report['saved'].startswith('存好了：报告.pdf（') and 'PDF 文档' in report['saved']
    # Read back by its id as a stored thing of this conversation; on no list until offered by its id.
    assert own_files.stored(store, 'home', picture['artifact_id'], task, None, 'read_image', 'X')['kind'] == 'image'
    monkeypatch.setattr(outbound_files, 'sends_here', lambda store, scene: True)
    local = scene_records.get(store, LOCAL)
    assert report['artifact_id'] not in [item['artifact_id'] for item in (outbound_files.offer(store, local) or {}).get(
        'items', ())]
    for saved in (picture, report):
        offered = outbound_files.register(store, task, tmp_path, {'artifact_id': saved['artifact_id']})
        artifact_records.save(store, {'_id': 'tool-offer-' + saved['artifact_id'], 'scope_key': task['scope_key'],
                                      'task_id': task['_id'], 'intent_revision': 1, 'tool': 'offer_file',
                                      'args': {}, 'input_hash': 'h', 'state': 'DONE', 'result': offered})
    picked = outbound_files.offered_by(store, task['_id'])
    files = outbound_files.offer(store, local, origin='home', picked=picked)
    pictures = outbound_media.offer(store, store.config, local, visibility.OWNER_PRIVATE, OWNER, picked=picked)
    assert files['items'][0]['artifact_id'] == report['artifact_id']
    assert pictures['items'][0]['artifact_id'] == picture['artifact_id']


def test_a_second_save_of_a_name_gets_a_suffix_and_never_overwrites(coordinator, tmp_path):
    store = coordinator.store
    broker = broker_for(store, a_task(coordinator, LOCAL, OWNER, 'd2'), tmp_path)
    first, second = save(broker, {'save': 'a.pdf'}, PDF), save(broker, {'save': 'a.pdf'}, PDF + b'%second\n')
    assert (first['path'], second['path']) == ('/task/downloads/a.pdf', '/task/downloads/a (2).pdf')
    assert (tmp_path / 'downloads' / 'a.pdf').read_bytes() == PDF
    # A name with a path in it is only its last part; one without an extension gets its type's.
    assert save(broker, {'save': '../../x/b'}, PNG)['path'] == '/task/downloads/b.png'


def test_an_outside_task_saves_into_its_own_conversation(coordinator, tmp_path):
    store = coordinator.store
    task = a_task(coordinator, 'g1', 'A', 'd3')
    assert access.origin_of_task(store, task) == 'outside'
    saved = save(broker_for(store, task, tmp_path), {'save': True}, PNG)
    row = artifact_records.get(store, saved['artifact_id'])
    assert row['scope_key'] == 'scene:g1' and '记在' in saved['saved'] and '家里' not in saved['saved']
    assert own_files.holds(row, own_files.scopes(store.config, scene_records.get(store, 'g1')))
    assert not own_files.holds(row, own_files.scopes(store.config, scene_records.get(store, LOCAL)))


def test_the_table_refuses_a_save_without_the_network_or_the_conversation_s_files(coordinator, tmp_path):
    store = coordinator.store
    task = a_task(coordinator, 'g1', 'A', 'd4')
    broker = broker_for(store, task, tmp_path)
    store.config['access'] = {'own_files': 'home_from_outside'}
    with pytest.raises(Denied) as caught:
        save(broker, {'save': True}, PNG)
    assert str(caught.value) == access.refusal('outside', 'own_files')
    assert not (tmp_path / 'downloads').exists() and denied_rows(store)[-1]['resource'] == 'own_files'
    assert 'web_fetch' in tasks.granted(store, task)            # without save it is still given
    store.config['access'] = {'internet': 'home'}
    assert tasks.barred(store.config, 'outside', 'web_fetch', {'save': True}) == 'internet'
    assert 'web_fetch' not in tasks.granted(store, task)
    assert tasks.refusal(store, task, 'web_fetch') == 'ACCESS_DENIED_INTERNET: ' + access.NOT_HERE


def test_a_body_over_20_mb_is_refused_and_nothing_is_kept(coordinator, tmp_path):
    store = coordinator.store
    broker = broker_for(store, a_task(coordinator, LOCAL, OWNER, 'd5'), tmp_path)
    rows = len(list(artifact_records.of_kind(store, 'file').rows()))
    with pytest.raises(ValueError, match='WEB_SAVE_BODY_INVALID'):
        save(broker, {'save': 'big.bin'}, b'\0' * (20 * 1024 * 1024 + 1))
    assert not list((tmp_path / 'downloads').glob('*')) and len(list(artifact_records.of_kind(store, 'file').rows())) == rows


def test_a_saved_picture_s_bytes_live_as_a_task_file_s_and_a_sent_one_keeps_them(coordinator, tmp_path):
    store = coordinator.store
    broker = broker_for(store, a_task(coordinator, LOCAL, OWNER, 'd6'), tmp_path)
    unsent, sent = (save(broker, {'save': True}, PNG)['artifact_id'] for _ in range(2))
    store.collection('artifacts').update({'_id': unsent}, Set({'created_at': OLD}))
    store.collection('artifacts').update({'_id': sent}, Set({'created_at': OLD}))
    store.put('messages', {'_id': 'out-d6', 'direction': 'outbound', 'scene_id': LOCAL, 'delivery_state': 'DELIVERED',
                           'attachment': {'artifact_id': sent}})
    media_life.sweep(store)
    assert artifact_records.get(store, unsent)['storage'] == artifact_records.REMOVED     # the row stays, its bytes go
    assert artifact_records.get(store, sent)['storage'] == artifact_records.STORED
