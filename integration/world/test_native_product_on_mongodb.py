"""Product lifecycle on MongoDB: blocking a person revokes their grants and queued publications, and a new epoch
retires the old main session without carrying it over (leak). Never contacts a model or QQ."""
from types import SimpleNamespace

import pytest

from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna import config as asuna_config, host, channel_admission, native_worker, native_settings
from asuna.channels import Channels
from asuna.chat import Chat
from asuna.native_worker import BusinessWorker
from asuna.grants import workspace_grant
from asuna.state import Denied

pytestmark = pytest.mark.world                # `store` is the fixture world


@pytest.fixture
def product(store, tmp_path, monkeypatch):
    for module in (asuna_config, host, channel_admission, native_worker, native_settings):
        monkeypatch.setattr(module, 'DATA', tmp_path / '.runtime')
    config = store.config
    config.update({'chat': {'scene_id': 'local', 'person_id': 'owner', 'persona': 'demo',
                            'workspace': str(tmp_path / 'local')}, 'workflow_timeout_seconds': 1,
                   'channels': {'qq': {'account_id': '99990', 'token': 'fixture-' * 8,
                                       'admission': 'automatic', 'routes': {}}}})
    db = store
    scene_records.save(db, {'_id': 'local', 'scope_key': 'scene:local', 'policy_epoch': 1,
                     'kind': 'dm', 'members': ['owner'], 'sequence': 0})
    app = SimpleNamespace(store=db, config=config, evidence=SimpleNamespace(record=lambda *_: None))
    worker = BusinessWorker()
    worker.app, worker.controller = app, Chat(app, config['chat'])
    worker.navigation = worker.prepare_navigation([])
    worker.projection_start = {'since': '2000-01-01'}
    worker.navigation_ready.set()
    events = []
    worker.emit = events.append
    worker.controller.on_input_received = worker.project_input
    return SimpleNamespace(config=config, store=db, worker=worker,
                           channel=Channels(worker.controller), events=events, root=tmp_path)


def envelope(sender='11110', group=None, mid='one', **extra):
    kind, target = ('group', group) if group else ('dm', sender)
    return {'route_id': f'auto-{kind}-{target}', 'account_id': '99990', 'sender_id': sender,
            'event_id': mid, 'text': 'offline fixture', **({'group_id': group} if group else {}), **extra}


def test_blocking_revokes_grants_and_queued_publications(product):
    p = product
    result = p.channel.receive('qq', envelope())
    message = p.store.raw.messages.find_one({'_id': 'in-' + result['episode_id']})
    episode_records.save(p.store, {'_id': result['episode_id'], 'scene_id': message['scene_id'],
                             'source_event_id': result['episode_id'], 'episode_kind': 'external',
                             'person_id': message['author'], 'state': 'SPEAK_ACCEPTED'})
    publication = {'channel_id': 'qq', 'scene_id': message['scene_id'], 'episode_id': result['episode_id']}
    p.config['channels']['qq']['blocked_senders'] = ['11110']
    with pytest.raises(Denied, match='PUBLICATION_MEMBER_REVOKED'):
        p.channel._valid_publication(publication, 'qq')
    with pytest.raises(Denied, match='WORKSPACE_NOT_AUTHORIZED'):
        workspace_grant(p.config, message['scene_id'], message['author'])
    host.prepare_channels(p.store)
    scene = p.store.raw.scenes.find_one({'_id': message['scene_id']})
    assert scene['members'] == [] and scene['policy_epoch'] == 2
    plan = p.worker.prepare_navigation([{'id': row['_id'], 'createdAt': 1} for row in p.store.raw.sessions.find({})])
    assert p.events[0]['session_id'] in plan['archive_ids']


def test_epoch_change_retires_old_main_without_redirecting_or_importing_it(product):
    p = product
    p.channel.receive('qq', envelope(group='22220'))
    old = p.events[0]['binding']
    scene = p.store.raw.scenes.find_one({'_id': old['scene_id']})
    scene_records.save(p.store, {**scene, 'policy_epoch': 2}, expected=scene['revision'])
    plan = p.worker.prepare_navigation([{'id': old['_id'], 'createdAt': 1}])
    current = next(entry for entry in plan['entries'] if entry['workspace'] == 'QQ')
    assert current['session_id'] != old['_id']
    assert current['binding']['source_session_id'] is None
    retired = p.store.raw.sessions.find_one({'_id': old['_id']})
    assert retired['retired'] and not retired['main_conversation'] and not retired.get('successor_id')
    assert old['_id'] in plan['archive_ids']
    assert p.store.raw.sessions.count_documents({'scene_id': old['scene_id'], 'main_conversation': True}) == 1


