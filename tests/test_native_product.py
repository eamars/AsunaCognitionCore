"""Product lifecycle probes against in-memory Mongo; never contact a model or QQ."""
from copy import deepcopy
from types import SimpleNamespace
import json

import mongomock
import pytest

from asuna import host, channel_admission, native_worker, native_settings
from asuna.channels import Channels
from asuna.chat import Chat
from asuna.native_worker import BusinessWorker
from asuna.grants import workspace_grant
from asuna.state import Store, Denied


@pytest.fixture
def product(tmp_path, monkeypatch):
    for module in (host, channel_admission, native_worker, native_settings):
        monkeypatch.setattr(module, 'ROOT', tmp_path)
    config = {'chat': {'scene_id': 'local', 'person_id': 'owner', 'persona': 'xiaoman',
                      'workspace': str(tmp_path / 'local')}, 'workflow_timeout_seconds': 1,
              'channels': {'qq': {'account_id': '99990000', 'token': 'fixture-' * 8,
                                 'admission': 'automatic', 'routes': {}}}}
    db = Store.__new__(Store)
    db.config, db.name, db.fail_audit = config, 'in-memory', False
    db.client = mongomock.MongoClient()
    db.db = db.client[db.name]
    db.put('scenes', {'_id': 'local', 'scope_key': 'scene:local', 'policy_epoch': 1,
                     'kind': 'dm', 'members': ['owner'], 'sequence': 0})
    app = SimpleNamespace(store=db, config=config, evidence=SimpleNamespace(record=lambda *_: None))
    worker = BusinessWorker('unused')
    worker.app, worker.controller = app, Chat(app, config['chat'])
    worker.navigation = worker.prepare_navigation([])
    worker.projection_start = {'since': '2000-01-01'}
    worker.navigation_ready.set()
    events = []
    worker.emit = events.append
    worker.controller.on_input_received = worker.project_input
    return SimpleNamespace(config=config, store=db, worker=worker,
                           channel=Channels(worker.controller), events=events, root=tmp_path)


def envelope(sender='11110000', group=None, mid='one', **extra):
    kind, target = ('group', group) if group else ('dm', sender)
    return {'route_id': f'auto-{kind}-{target}', 'account_id': '99990000', 'sender_id': sender,
            'event_id': mid, 'text': 'offline fixture', **({'group_id': group} if group else {}), **extra}


def test_receipt_is_visible_before_processing_and_replayed_until_native_ack(product):
    p = product
    result = p.channel.receive('qq', envelope(group='22220000'))
    assert p.worker.controller.pending.qsize() == 1
    assert p.store.db.episodes.count_documents({}) == 0
    receipt = p.events[0]
    assert receipt['binding']['main_conversation']
    assert receipt['binding']['native_title'] == '22220000'
    assert receipt['binding']['scope_key'] == 'scene:qq:99990000:group:22220000'
    assert receipt['input']['id'] == 'in-' + result['episode_id']
    p.worker.dispatch('navigation.ready', {})
    assert len(p.events) == 2  # unacknowledged durable input, no model execution
    p.worker.dispatch('channel_input.ack', {'input_id': receipt['input']['id'], 'session_id': receipt['session_id']})
    p.worker.dispatch('navigation.ready', {})
    assert len(p.events) == 2
    assert p.channel.receive('qq', envelope(group='22220000'))['status'] == 'duplicate'
    assert len(p.events) == 2


def test_new_group_member_continues_the_same_named_session_and_restores(product):
    p = product
    p.channel.receive('qq', envelope(group='22220000'))
    p.channel.receive('qq', envelope(sender='33330000', group='22220000', mid='two'))
    first, second = p.events
    assert first['session_id'] == second['session_id']
    assert first['binding']['policy_epoch'] == second['binding']['policy_epoch'] == 1
    assert p.store.db.sessions.count_documents({'scene_id': 'qq:99990000:group:22220000', 'main_conversation': True}) == 1
    for route in p.config['channels']['qq']['routes'].values():
        for grant in route.get('members', {}).values():
            assert grant['workspace'] != p.config['chat']['workspace']
            assert grant['read_only_paths'] == []
    routes = deepcopy(p.config['channels']['qq']['routes'])
    p.config['channels']['qq']['routes'] = {}
    channel_admission.restore_admissions(p.store)
    host.prepare_channels(p.store)
    assert routes == p.config['channels']['qq']['routes']


@pytest.mark.parametrize('body', [envelope(group='22220000', mentioned_account_ids='invalid'),
    envelope(group='22220000', reply_to=123), envelope(mentioned_account_ids=[]),
    envelope(sender='99990000'), envelope(account_id='another-bot'), envelope(text='')])
def test_invalid_input_does_not_admit_a_contact_or_group(product, body):
    with pytest.raises((Denied, ValueError)):
        product.channel.receive('qq', body)
    assert product.store.db.artifacts.count_documents({}) == 0
    assert product.config['channels']['qq']['routes'] == {}


def test_blocking_revokes_grants_and_queued_publications(product):
    p = product
    result = p.channel.receive('qq', envelope())
    message = p.store.db.messages.find_one({'_id': 'in-' + result['episode_id']})
    p.store.put('episodes', {'_id': result['episode_id'], 'person_id': message['author'], 'state': 'SPEAK_ACCEPTED'})
    publication = {'channel_id': 'qq', 'scene_id': message['scene_id'], 'episode_id': result['episode_id']}
    p.config['channels']['qq']['blocked_senders'] = ['11110000']
    with pytest.raises(Denied, match='PUBLICATION_MEMBER_REVOKED'):
        p.channel._valid_publication(publication, 'qq')
    with pytest.raises(Denied, match='WORKSPACE_NOT_AUTHORIZED'):
        workspace_grant(p.config, message['scene_id'], message['author'])
    host.prepare_channels(p.store)
    scene = p.store.db.scenes.find_one({'_id': message['scene_id']})
    assert scene['members'] == [] and scene['policy_epoch'] == 2
    plan = p.worker.prepare_navigation([{'id': row['_id'], 'createdAt': 1} for row in p.store.db.sessions.find({})])
    assert p.events[0]['session_id'] in plan['archive_ids']


def test_epoch_change_retires_old_main_without_redirecting_or_importing_it(product):
    p = product
    p.channel.receive('qq', envelope(group='22220000'))
    old = p.events[0]['binding']
    scene = p.store.db.scenes.find_one({'_id': old['scene_id']})
    p.store.put('scenes', {**scene, 'policy_epoch': 2}, expected=scene['revision'])
    plan = p.worker.prepare_navigation([{'id': old['_id'], 'createdAt': 1}])
    current = next(entry for entry in plan['entries'] if entry['workspace'] == 'QQ')
    assert current['session_id'] != old['_id']
    assert current['binding']['source_session_id'] is None
    retired = p.store.db.sessions.find_one({'_id': old['_id']})
    assert retired['retired'] and not retired['main_conversation'] and not retired.get('successor_id')
    assert old['_id'] in plan['archive_ids']
    assert p.store.db.sessions.count_documents({'scene_id': old['scene_id'], 'main_conversation': True}) == 1


def test_native_settings_preserve_secret_refs_and_derive_one_adapter_policy(product):
    p = product
    config = {**p.config, 'database': 'existing', 'allowed_databases': ['existing'],
        'mongo_uri': 'mongodb://fixture-user:fixture-password@127.0.0.1',
        'dsh_home': str(p.root / '.runtime/dsh'), 'workdir': str(p.root / '.runtime/work'),
        'embedding': {'base_url': 'http://127.0.0.1:9999/v1', 'model': 'fixture', 'api_key': 'fixture-key'},
        'integration': {'adapter_config': {'host': {'channel_id': 'qq'}, 'napcat': {}}}}
    exported = native_settings.export_settings(config)
    assert 'fixture-password' not in json.dumps(exported['deployment'])
    assert exported['deployment']['embedding']['api_key'] == {'$secret': 'embedding/api_key'}
    models = {'character': {'model': 'same-model'}, 'action': {'model': 'same-model'}}
    resolved = native_settings.runtime_settings(**exported, models=models, admission='automatic')
    assert resolved['channels']['qq']['admission'] == 'automatic'
    adapter = resolved['integration']['adapter_config']
    assert adapter['admission'] == 'automatic'
    assert adapter['host']['token'] == config['channels']['qq']['token']
    assert resolved['character']['model'] == resolved['executor']['model']
    assert 'character' not in exported['deployment']
    assert not (p.root / '.runtime/dsh').exists()
