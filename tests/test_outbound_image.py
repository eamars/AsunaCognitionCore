"""B7 的 MongoDB／GridFS 用例：导入的图登记成本场景的 image artifact，同一主人的另一个
owner_private 场景（QQ 私聊）那一轮能合法引用它把图发出去。

离线用例（``python3 tools/outbound_image_offline_check.py``）假掉的只有存储；这里跑的是真
Mongo、真 GridFS、真 CAS 与真 claim／attachment／receipt 路径。真实 NapCat 收图仍要主人在
QQ 里发一条消息才能验，两者不互相代替。

场景对应关系：``dm-a`` 是主人的本机私聊（``config.chat`` 指到这里，生图与导入只在这一侧），
``dm-qq`` 是同一个人的另一个入口（走通道的私聊），``dm-other`` 是别人的私聊，``g1`` 是群。
"""
from types import SimpleNamespace
import hashlib
import json
import threading

import pytest

from asuna import outbound_media
from asuna.blobs import BlobStore
from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.integration_import import MAX_ARTIFACT_BYTES, import_artifact
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import Refused
from asuna.state import Denied
from test_adr009_p2 import THINK, owner

LOCAL = 'dm-a'
QQ = 'dm-qq'
OTHER = 'dm-other'
GROUP = 'g1'
LOCAL_SCOPE = 'scene:' + LOCAL
PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))
JPEG = b'\xff\xd8\xff\xe0' + b'jpeg-bytes' * 4
NOT_IMAGE = b'{"workflow":"selfie","ready":true}'
ENDPOINTS = [{'name': 'gen', 'host': '127.0.0.1', 'port': 1}]
IMPORT_FIELDS = {'imported', 'endpoint', 'artifact_path', 'target_relative_path', 'target_path',
                 'bytes', 'sha256', 'http_status', 'content_type', 'max_bytes', 'overwritten'}


def model(max_messages=1):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'split_marker': '---split---', 'chars_per_second': 4,
                      'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store, scene, *, person='A', target='dm', kind=None):
    """把某一侧接上通道：路由 + 场景上的 channel_id（与 p5 的 replay 通道同一套写法）。"""
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': scene, 'sender_id': 'peer', 'person_id': person,
                 'target': {'type': target, 'id': 'peer'}}}}}
    row = store.db.scenes.find_one({'_id': scene})
    if row is None:
        store.put('scenes', {'_id': scene, 'kind': kind or ('dm' if target == 'dm' else 'group'),
                             'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'members': [person],
                             'channel_id': 'replay', 'sequence': 0}, stream='b7')
    else:
        store.put('scenes', {**row, 'channel_id': 'replay'}, expected=row['revision'])


def link(store, reader, target):
    """配置里那条联动边（唯一真相；删掉键就等于回滚）。"""
    store.config['context_links'] = {reader: [target]}


def unlink(store, scene_id):
    """把这条联动两边都拿掉：配置（围栏现算读它）与 scenes.readable_scenes（宿主启动／每轮
    chat 时从配置写进去的派生投影，历史与讨论整理那些读路径看的是它）。只删一边都不算「没有联动」。
    """
    row = store.db.scenes.find_one({'_id': scene_id})
    if row is not None and row.get('readable_scenes'):
        store.put('scenes', {**row, 'readable_scenes': []}, expected=row['revision'])
    return (row or {}).get('readable_scenes')


def import_bytes(store, scope_key, body=PNG, *, target='artifacts/pic.png', workspace, register='auto'):
    """真走 import_integration_artifact 的判定与写盘，只假「谁给字节」；登记用真 BlobStore。"""
    def fetch(endpoint, path, limit):
        return {'status': 200, 'declared': len(body), 'body': body,
                'content_type': 'image/png', 'transport_error': None}

    hook = (outbound_media.import_register(store, {'scope_key': scope_key})
            if register == 'auto' else register)
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


def speak_rows(store, ep_id):
    return list(store.db.messages.find({'episode_id': ep_id, 'phase': 'SPEAK'}).sort('scene_seq', 1))


def attach_calls(coordinator):
    """This turn's attach_image calls as (result | refusal words | 'NOT_EXPOSED', ok)."""
    return [(row[4], row[5]) for row in coordinator.character.tool_results if row[2] == 'attach_image']


def refusal_code(words):
    """{code: detail} from a refusal's words (role_tools.words keeps the code in brackets at the end)."""
    import re
    found = re.search(r'（([A-Z_]+)(?::\s*(.*))?）$', words)
    return {found.group(1): found.group(2)} if found else {words: None}


def forced_attach(store, coordinator, ep, attach):
    """Defence in depth: were attach_image offered in this turn anyway, the tool itself refuses, in words."""
    row = store.db.episodes.find_one({'_id': ep['_id']})
    store.put('episodes', {**row, 'state': 'TURN', 'turn_tools': [*row['turn_tools'], 'attach_image']},
              expected=row['revision'], stream=ep['_id'])
    with pytest.raises(Refused) as refused:
        coordinator.tools.call(ep['_id'], 'forced-attach', 'attach_image', attach)
    assert not store.db.episodes.find_one({'_id': ep['_id']}).get('attachment')
    return refusal_code(str(refused.value))


def bridge(store):
    return Channels(SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(),
                                    reconfiguring=False))


def delivered(server, item, meta):
    """平台回执带上适配器真的取到并发了图的那份证据。"""
    body = {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
            'platform_message_id': 'm-' + item['publication_id'],
            'response': {'message_id': 'm-' + item['publication_id'],
                         'attachment': {'artifact_id': meta['artifact_id'],
                                        'media_type': meta['media_type'], 'sha256': meta['sha256'],
                                        'declared_size': meta['size'], 'bytes': meta['size'],
                                        'sha256_verified': True, 'sniffed_media_type': meta['media_type'],
                                        'content_type': meta['media_type'], 'base64_chars': 128}}}
    return server.receipt('replay', item['publication_id'], body)


def test_T_B7_1_imported_image_is_registered_in_its_own_scene(store, tmp_path):
    owner(store)                                          # dm-a 是主人的本机私聊
    result = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path)
    assert result.get('imported') is True, result
    art = result['artifact']
    assert art['registered'] is True and art['artifact_id'].startswith('blob-'), art
    assert art['sha256'] == hashlib.sha256(PNG).hexdigest(), '哈希不是宿主从字节重算的那一份'
    assert art['media_type'] == 'image/png' and art['bytes'] == len(PNG), art
    row = store.db.artifacts.find_one({'_id': art['artifact_id']})
    assert (row['scope_key'], row['kind'], row['state'], row['storage']) == (
        LOCAL_SCOPE, 'image', 'DONE', 'gridfs'), row
    assert row['media_type'] == 'image/png' and row['size'] == len(PNG) and row['created_at'], row
    assert row['source_ids'] and row['source_ids'][0].startswith('integration:gen:'), row['source_ids']
    assert (tmp_path / 'artifacts/pic.png').read_bytes() == PNG
    assert BlobStore(store).get(art['artifact_id'], LOCAL_SCOPE, operator=True) == PNG, '真 GridFS 里的字节不对'

    named = import_bytes(store, LOCAL_SCOPE, JPEG, target='artifacts/named.png', workspace=tmp_path)
    assert named['artifact']['media_type'] == 'image/jpeg', '格式按文件名或 Content-Type 定了'

    text = import_bytes(store, LOCAL_SCOPE, NOT_IMAGE, target='artifacts/job.json', workspace=tmp_path)
    assert 'artifact' not in text, text                                  # 非图片：结果与改动前逐字一致
    assert set(text) == IMPORT_FIELDS, sorted(text)
    assert store.db.artifacts.count_documents({'kind': 'image', 'scope_key': LOCAL_SCOPE}) == 2

    # 出站上限之上就不登记：导入工具自己的 4 MiB 上限本来就在出站上限之内，这条围栏是防以后放宽
    assert MAX_ARTIFACT_BYTES <= outbound_media.MAX_ATTACHMENT_BYTES
    over = outbound_media.register_imported_image(
        store, LOCAL_SCOPE, PNG + b'x' * outbound_media.MAX_ATTACHMENT_BYTES)
    assert over['registered'] is False and over['reason'] == 'ATTACHMENT_OVER_LIMIT', over
    assert store.db.artifacts.count_documents({'kind': 'image', 'scope_key': LOCAL_SCOPE}) == 2


def test_T_B7_2_local_image_is_offered_attached_and_delivered_in_the_qq_turn(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    art = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path)['artifact']

    offer = outbound_media.offer(store, store.config, store.db.scenes.find_one({'_id': QQ}),
                                 'owner_private', 'A')
    assert offer, 'QQ 私聊那一轮没看到本机登记的图'
    listed = {item['artifact_id']: item for item in offer['items']}
    assert art['artifact_id'] in listed and listed[art['artifact_id']]['from_linked_scene'] is True
    assert listed[art['artifact_id']]['scene_id'] == LOCAL, listed[art['artifact_id']]

    coordinator, ep = turn(store, attach={'artifact_id': art['artifact_id'], 'why': '给你看看'})
    assert 'attach_image' in coordinator.character.calls[0]['tools']
    [(result, ok)] = attach_calls(coordinator)
    assert ok and result['attached'] == art['artifact_id'], result
    assert ep['state'] == 'COMMITTED' and ep['attachment']['artifact_id'] == art['artifact_id']
    rows = speak_rows(store, ep['_id'])
    assert rows and rows[0]['attachment']['artifact_id'] == art['artifact_id'], rows[0].get('attachment')
    assert rows[0]['attachment']['sha256'] == art['sha256']

    server = bridge(store)
    item = server.claim('replay', supports=['image'])['items'][0]
    assert item['attachment'] == rows[0]['attachment'], item
    assert 'base64' not in json.dumps(item, ensure_ascii=False), 'claim 里不该有 base64'

    data, media_type = server.attachment('replay', item['publication_id'],
                                         {'attempt_id': [item['attempt_id']]})
    assert (data, media_type) == (PNG, 'image/png'), (len(data), media_type)
    assert delivered(server, item, rows[0]['attachment']) == {'status': 'DELIVERED'}
    slot = outbound_media.history_slot(store.db.messages.find_one({'_id': item['publication_id']}), store)
    assert slot['sent'] is True and slot['attested'] is True and '我发过这张图' in slot['note'], slot


def test_T_B7_3_group_other_person_and_unlinked_scenes_are_refused(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    art = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path)['artifact']
    attach = {'artifact_id': art['artifact_id'], 'why': '给你看看'}

    def refused_turn(**where):
        """The turn has no attach_image (nothing listed or the direction is not allowed): her words still go
        out, without an image row; the tool itself would refuse with the fence's reason."""
        coordinator, ep = turn(store, attach=attach, **where)
        assert ep['state'] == 'COMMITTED', ep.get('failure')
        assert 'attach_image' not in coordinator.character.calls[0]['tools']
        assert attach_calls(coordinator) == [('NOT_EXPOSED', False)]
        rows = speak_rows(store, ep['_id'])
        assert rows and not any(row.get('attachment') for row in rows)
        return forced_attach(store, coordinator, ep, attach)

    # 没有那条边：清单里就没有这张图，这一回合根本没有 attach_image（真实流水线的第一道闸），
    # 行上也不写元数据；工具自己再按「本轮没列出」退回。scope 围栏本身（列出了但 scope 不在可引用集合里）
    # 在离线套件里逐条覆盖：python3 tools/outbound_image_offline_check.py
    assert outbound_media.offer(store, store.config, store.db.scenes.find_one({'_id': QQ}),
                                'owner_private', 'A') is None
    assert refused_turn(key='nolink') == {'ATTACH_ARTIFACT_NOT_IN_CONTEXT': art['artifact_id']}

    # 群：群永远不是 owner_private，先撞 session_class 闸门，不静默降级成「只发文字却报平台已送达」
    channel_scene(store, GROUP, person='A', target='group')
    link(store, GROUP, LOCAL)
    assert refused_turn(scene=GROUP, key='group', target='group') == {
        'ATTACH_TARGET_NOT_ALLOWED': 'session_class_not_owner_private'}

    # 别人的私聊：不是同一个人的私人空间
    channel_scene(store, OTHER, person='B')
    link(store, OTHER, LOCAL)
    assert refused_turn(scene=OTHER, person='B', key='other') == {
        'ATTACH_TARGET_NOT_ALLOWED': 'session_class_not_owner_private'}

    # 主人自己的 dm 场景却把路由目标配成群：确定性撞 target_not_dm（配置错了也不静默发）
    channel_scene(store, QQ, person='A', target='group', kind='dm')
    link(store, QQ, LOCAL)
    assert refused_turn(key='misroute', target='group') == {'ATTACH_TARGET_NOT_ALLOWED': 'target_not_dm'}


def test_T_B7_4_endpoint_fences_and_the_link_is_read_at_serve_time(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    art = import_bytes(store, LOCAL_SCOPE, workspace=tmp_path)['artifact']
    other = BlobStore(store).put(JPEG, LOCAL_SCOPE, 'image', media_type='image/jpeg')
    turn(store, key='b7a', attach={'artifact_id': art['artifact_id'], 'why': '给你看看'})
    turn(store, key='b7b', attach={'artifact_id': art['artifact_id'], 'why': '再给一次'})

    server = bridge(store)
    first = server.claim('replay')['items'][0]                           # 没声明 supports=image
    assert 'attachment' not in first, first
    claimed = store.db.messages.find_one({'_id': first['publication_id']})
    assert claimed['delivery_state'] == 'SENDING' and claimed['attempt_id'] == first['attempt_id']
    assert claimed['attachment_skipped'] == outbound_media.NO_CAPABILITY, claimed.get('attachment_skipped')
    with pytest.raises(Denied) as skipped:                               # 图没跟着出去，就不给字节
        server.attachment('replay', first['publication_id'], {'attempt_id': [first['attempt_id']]})
    assert 'ATTACHMENT_NOT_DECLARED' in str(skipped.value)

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
    row = store.db.messages.find_one({'_id': second['publication_id']})
    with pytest.raises(Denied) as unlinked:
        bridge(store).attachment('replay', second['publication_id'], {'attempt_id': [second['attempt_id']]})
    assert 'ATTACHMENT_SCOPE_DENIED' in str(unlinked.value), \
        (str(unlinked.value), outbound_media.row_image_scopes(store, row))
