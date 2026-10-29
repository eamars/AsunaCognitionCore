"""ADR-064 B7 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): the image endpoint's fences,
and the link read at serve time."""
from types import SimpleNamespace
import json
import threading

import pytest

from asuna.records import scenes as scene_records
from asuna import outbound_media
from asuna.blobs import BlobStore
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.integration_import import import_artifact
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import Denied

from turn_parts import owner

pytestmark = pytest.mark.world                # `store` is the fixture world

LOCAL = 'dm-a'
QQ = 'dm-qq'
LOCAL_SCOPE = 'scene:' + LOCAL
PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))
JPEG = b'\xff\xd8\xff\xe0' + b'jpeg-bytes' * 4
ENDPOINTS = [{'name': 'gen', 'host': '127.0.0.1', 'port': 1}]

THINK = ('think', {'thought': '他说了一件小事，值得记下来。'})


def model(max_messages=1):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'split_marker': '---split---', 'chars_per_second': 4,
                      'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store, scene, *, person='A', target='dm', kind=None):
    """把某一侧接上通道：路由 + 场景上的 channel_id（与 p5 的 replay 通道同一套写法）。"""
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': scene, 'sender_id': 'peer', 'person_id': person,
                 'target': {'type': target, 'id': 'peer'}}}}}
    row = store.raw.scenes.find_one({'_id': scene})
    if row is None:
        scene_records.save(store, {'_id': scene, 'kind': kind or ('dm' if target == 'dm' else 'group'),
                             'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'members': [person],
                             'channel_id': 'replay', 'sequence': 0}, stream='b7')
    else:
        scene_records.save(store, {**row, 'channel_id': 'replay'}, expected=row['revision'])


def link(store, reader, target):
    """配置里那条联动边（唯一真相；删掉键就等于回滚）。"""
    store.config['context_links'] = {reader: [target]}


def unlink(store, scene_id):
    """把这条联动两边都拿掉：配置（围栏现算读它）与 scenes.readable_scenes（宿主启动／每轮
    chat 时从配置写进去的派生投影，历史与讨论整理那些读路径看的是它）。只删一边都不算「没有联动」。
    """
    row = store.raw.scenes.find_one({'_id': scene_id})
    if row is not None and row.get('readable_scenes'):
        scene_records.save(store, {**row, 'readable_scenes': []}, expected=row['revision'])
    return (row or {}).get('readable_scenes')


def import_bytes(store, scope_key, body=PNG, *, target='artifacts/pic.png', workspace, register='auto'):
    """真走 import_integration_artifact 的判定与写盘，只假「谁给字节」；登记用真 BlobStore。"""
    def fetch(endpoint, path, limit):
        return {'status': 200, 'declared': len(body), 'body': body,
                'content_type': 'image/png', 'transport_error': None}

    if register == 'foreign':
        # A picture that is not hers (someone sent it): the owner's chat takes it only from its own scopes.
        def hook(data, meta=None):
            return outbound_media.register_imported_image(store, scope_key, data, source='upload:pic')
    else:
        hook = outbound_media.import_register(store, {'scope_key': scope_key}) if register == 'auto' else register
    return import_artifact({'endpoint': 'gen', 'artifact_path': '/view/pic.png',
                            'target_relative_path': target},
                           endpoints=ENDPOINTS, workspace=workspace, fetch=fetch, register=hook)


def turn(store, *, scene=QQ, person='A', attach=None, speech='这张给你看看。', key='b7', target='dm'):
    store.config['persona_model'] = model()
    lane = FakeLane(store, [FakeTurn([THINK, *([('attach_image', attach)] if attach else [])], speech)])
    coordinator = Coordinator(store, lane)
    event = {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': '图呢',
             'channel': {'id': 'replay', 'account_id': 'bot',
                         'target': {'type': target, 'id': 'peer'}, 'platform_event_id': 'p-' + key}}
    persist_input(store, event, managed=True)
    return coordinator, coordinator.ingest(event)


def bridge(store):
    return Channels(SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(),
                                    reconfiguring=False))


def test_T_B7_4_endpoint_fences_and_the_link_is_read_at_serve_time(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    art = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path, register='foreign')['artifact']
    other = BlobStore(store).put(JPEG, LOCAL_SCOPE, 'image', media_type='image/jpeg')
    turn(store, key='b7a', attach={'artifact_id': art['artifact_id'], 'why': '给你看看'})
    turn(store, key='b7b', attach={'artifact_id': art['artifact_id'], 'why': '再给一次'})

    server = bridge(store)
    first = server.claim('replay')['items'][0]                           # 没声明 supports=image
    assert 'attachment' not in first, first
    claimed = store.raw.messages.find_one({'_id': first['publication_id']})
    assert claimed['delivery_state'] == 'SENDING' and claimed['attempt_id'] == first['attempt_id']
    assert claimed['attachment_skipped'] == outbound_media.NO_CAPABILITY, claimed.get('attachment_skipped')
    with pytest.raises(Denied) as skipped:                               # 图没跟着出去，就不给字节
        server.attachment('replay', first['publication_id'], {'attempt_id': [first['attempt_id']]})
    assert 'ATTACHMENT_NOT_DECLARED' in str(skipped.value)
    # the first line settles before the next one of this conversation is handed out (ADR-095: one chat line out each)
    server.receipt('replay', first['publication_id'], {'attempt_id': first['attempt_id'], 'status': 'platform_accepted',
                                                       'platform_message_id': 'pm-b7a', 'response': {}})

    second = server.claim('replay', supports=['image'])['items'][0]      # 下一条：声明了能力
    assert second['attachment']['artifact_id'] == art['artifact_id'], second
    assert 'base64' not in json.dumps(second, ensure_ascii=False)
    with pytest.raises(Denied) as wrong:                                 # 别人的 attempt 取不到
        bridge(store).attachment('replay', second['publication_id'], {'attempt_id': ['attempt-nope']})
    assert 'PUBLICATION_ATTEMPT_MISMATCH' in str(wrong.value)
    with pytest.raises(Denied) as foreign:                               # 只发这条自己声明的那张
        bridge(store).attachment('replay', second['publication_id'],
                                 {'attempt_id': [second['attempt_id']], 'artifact_id': [other['artifact_id']]})
    assert 'ATTACHMENT_ARTIFACT_DENIED' in str(foreign.value)

    # 先确认这条此刻确实能取到字节（围栏是开着的），再把那条边两边都删掉——删键即回滚
    assert bridge(store).attachment('replay', second['publication_id'],
                                    {'attempt_id': [second['attempt_id']]})[0] == PNG
    store.config.pop('context_links', None)
    unlink(store, QQ)                                                     # 派生投影也一起清掉
    unlink(store, LOCAL)
    row = store.raw.messages.find_one({'_id': second['publication_id']})
    with pytest.raises(Denied) as unlinked:
        bridge(store).attachment('replay', second['publication_id'], {'attempt_id': [second['attempt_id']]})
    assert 'ATTACHMENT_SCOPE_DENIED' in str(unlinked.value), \
        (str(unlinked.value), outbound_media.row_image_scopes(store, row))
