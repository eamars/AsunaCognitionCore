"""Offline adapter -> Core -> durable-state simulator. No network or real Mongo."""
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from tempfile import TemporaryDirectory
from threading import RLock, Event
from types import SimpleNamespace

import mongomock

ROOT = Path(__file__).resolve().parents[1]
# The QQ adapter and its kind module belong to the channel package; name it explicitly.
PACKAGE = Path(sys.argv[1] if len(sys.argv) > 1 else '').resolve()
ADAPTER = PACKAGE / 'integration'
if not (ADAPTER / 'qqadapter').is_dir():
    raise SystemExit('Usage: probe_qq_admission.py <channel-package-directory, e.g. packages/channels/napcat-qq>')
sys.path.insert(0, str(ADAPTER))
from qqadapter.config import Config
from qqadapter.inbound import classify, SeenLRU
from asuna import channel_kinds, host, channel_admission
channel_kinds.load([{'python': PACKAGE / 'python', 'module': 'napcat_qq'}])
from asuna.channels import Channels
from asuna.config import load
from asuna.ingress import persist_input
from asuna.native_worker import BusinessWorker
from asuna.state import Store, Denied


def probe():
    config = load(ROOT / 'config/local.json')
    raw = {'endpoints': {e['name']: {'host': '127.0.0.1', 'port': e['port']}
                        for e in config['integration']['endpoints']},
           'adapter': deepcopy(config['integration']['adapter_config'])}
    raw['adapter'].update(admission='automatic', routes={}, allowed_private_user_ids=[], allowed_group_ids=[])
    adapter = Config(raw, 'in-memory')
    channel_id = adapter.host['channel_id']
    config['channels'] = {channel_id: {**config['channels'][channel_id], 'admission': 'automatic', 'routes': {}}}
    config.pop('canonical_persons', None)
    config.pop('context_links', None)
    store = Store.__new__(Store)
    store.config, store.name, store.fail_audit = config, 'in-memory', False
    store.client = mongomock.MongoClient()
    store.db = store.client[store.name]
    controller = SimpleNamespace(app=SimpleNamespace(store=store), ingress_lock=RLock(),
        reconfiguring=False, stopping=Event(),
        receive=lambda event: persist_input(store, event, managed=True)[0])
    channel, seen = Channels(controller), SeenLRU()
    old_host, old_admission = host.ROOT, channel_admission.ROOT
    with TemporaryDirectory(prefix='asuna-admission-') as temp:
        host.ROOT = channel_admission.ROOT = Path(temp)
        config['chat']['workspace'] = str(Path(temp) / 'local')
        def send(sender, mid, group=None):
            event = {'post_type': 'message', 'message_type': 'group' if group else 'private',
                'self_id': adapter.napcat['account_id'], 'user_id': sender, 'message_id': mid,
                'message': [{'type': 'text', 'data': {'text': 'offline admission fixture'}}]}
            if group:
                event['group_id'] = group
            pair, reason = classify(event, adapter, seen)
            assert reason == 'accepted', reason
            return pair[0], channel.receive(channel_id, pair[0])
        try:
            _, dm = send('990000000001', 'one')
            envelope, first = send('990000000001', 'two', '990000000002')
            _, second = send('990000000003', 'three', '990000000002')
            assert first['scene_id'] == second['scene_id'] != dm['scene_id']
            assert first['policy_epoch'] == second['policy_epoch'] == 1
            assert channel.receive(channel_id, envelope)['_id'] == first['_id']
            assert store.db.messages.count_documents({}) == 3
            original_routes = deepcopy(config['channels'][channel_id]['routes'])
            config['channels'][channel_id]['routes'] = {}
            channel_admission.restore_admissions(store)
            assert config['channels'][channel_id]['routes'] == original_routes
            host.prepare_channels(store)
            assert store.db.scenes.find_one({'_id': first['scene_id']})['policy_epoch'] == 1
            config['channels'][channel_id]['blocked_senders'] = ['990000000001']
            try:
                channel.receive(channel_id, envelope)
            except Denied as error:
                assert str(error) == 'CHANNEL_BLOCKED'
            else:
                raise AssertionError('blocked sender was admitted')
            for route in original_routes.values():
                from asuna.channels import route_members
                for grant in route_members(route).values():
                    assert grant.get('read_only_paths') == []
                    assert grant['workspace'] != config['chat']['workspace']
            return {'new_dm': True, 'new_group': True, 'new_group_member': True,
                'group_epoch_unchanged': True, 'duplicate_suppressed': True,
                'restart_restores_admissions': True, 'block_enforced': True,
                'owner_grants_inherited': False, 'model_calls': 0, 'network_calls': 0, 'real_database_writes': 0}
        finally:
            host.ROOT, channel_admission.ROOT = old_host, old_admission


if __name__ == '__main__':
    print(json.dumps(probe(), indent=2))
