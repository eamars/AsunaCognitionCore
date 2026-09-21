"""--debug only: isolated host replay, fake cognition, real Mongo and loopback HTTP.

Does not call a model or contact a platform. Browser evidence is separate.
"""
import argparse
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx

from asuna.channels import Channels, ChannelServer
from asuna.chat import Chat
from asuna.config import ROOT, load
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.host import prepare_channels
from asuna.lanes import FakeLane, LaneResult
from asuna.router import Router
from asuna.state import Store


def probe():
    run = uuid.uuid4().hex[:12]
    config = load()
    config['channels'] = {'replay': {'token': uuid.uuid4().hex, 'account_id': 'replay-bot', 'routes': {
        'peer': {'scene_id': 'replay-dm', 'person_id': 'replay-person', 'sender_id': 'replay-peer',
                 'target': {'type': 'dm', 'id': 'replay-peer'},
                 'workspace': str(ROOT / '.runtime/channels' / run)}}}}
    store = Store(config, 'asuna_v2_test_host_' + run)
    store.migrate()
    store.seed()  # Only the isolated test database; never the configured live database.
    prepare_channels(store)
    evidence = Evidence(ROOT / 'reports' / ('host-probe-' + run))
    lane = FakeLane(store, [LaneResult('REPLAY_PRIVATE'), LaneResult(json.dumps({
        'next': 'speak', 'goal': 'replay', 'constraints': [], 'recall_query': '', 'speak_before_action': False})),
        LaneResult('REPLAY_PUBLIC')])
    coordinator = Coordinator(store, lane)
    app = SimpleNamespace(store=store, config=config, evidence=evidence, character=lane,
                          router=Router(store, coordinator))
    settings = {**config['chat'], 'persona': 'P1'}
    chat = Chat(app, settings, emit=lambda _: None)
    channel = Channels(chat)
    server = ChannelServer(channel)
    client = httpx.Client(base_url=f'http://127.0.0.1:{server.server.server_port}', trust_env=False,
                         headers={'Authorization': 'Bearer ' + config['channels']['replay']['token']})
    try:
        event = {'route_id': 'peer', 'account_id': 'replay-bot', 'sender_id': 'replay-peer',
                 'event_id': 'replay-event', 'text': 'LOCAL_HOST_REPLAY_INPUT', 'raw': {'fixture': True}}
        response = client.post('/v1/channels/replay/events', json=event)
        assert response.status_code == 200, response.text
        key = response.json()['episode_id']
        assert store.db.messages.find_one({'_id': 'in-' + key})['ingress_state'] == 'ACCEPTED'
        assert not lane.calls
        assert client.get('/v1/channels/replay/outbox', headers={'Authorization': 'Bearer invalid'}).status_code == 403
        assert client.post('/v1/channels/replay/events', json=event).json()['status'] == 'duplicate'
        assert client.post('/v1/channels/replay/events', json={**event, 'scope_key': 'operator'}).status_code == 403
        # Simulate losing the in-memory queue before starting cognition.
        recovered = Chat(app, settings, emit=lambda _: None)
        recovered.recover_inputs()
        recovered.worker.start()
        recovered.pending.join()
        assert store.db.messages.find_one({'_id': 'in-' + key})['result_state'] == 'COMMITTED'
        response = client.get('/v1/channels/replay/outbox').json()
        item = response['items'][0]
        assert item['text'] == 'REPLAY_PUBLIC' and item['reply_to'] == 'replay-event'
        assert set(item) == {'publication_id', 'attempt_id', 'target', 'text', 'reply_to'}
        message = store.db.messages.find_one({'_id': item['publication_id']})
        assert message['delivery_state'] == 'SENDING'
        assert store.db.sink_receipts.count_documents({}) == 0
        channel.recover_sending()
        assert not client.get('/v1/channels/replay/outbox').json()['items']
        receipt = {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                   'platform_message_id': 'replay-ack', 'response': {'fixture': True, 'status': 'ok'}}
        url = '/v1/channels/replay/outbox/' + item['publication_id'] + '/receipt'
        assert client.post(url, json={**receipt, 'attempt_id': 'wrong-attempt'}).status_code == 403
        assert client.post(url, json={**receipt, 'platform_message_id': ''}).status_code == 400
        assert client.post(url, json=receipt).json()['status'] == 'DELIVERED'
        assert client.post(url, json=receipt).json()['status'] == 'DELIVERED'
        assert len(lane.calls) == 3
        result = {'status': 'PASS', 'scope': 'LOCAL_HOST_REPLAY; fake cognition, no QQ',
                  'database': store.name, 'episode_id': key,
                  'checks': ['persist before queue/model', 'duplicate input', 'reject scope injection',
                             'recover lost queue', 'public-only claim', 'no local sink ack',
                             'unknown send not retried', 'late receipt', 'idempotent receipt']}
        (evidence.root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        recovered.stop()
    finally:
        server.close()
        client.close()
        store.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--debug', action='store_true', required=True)
    parser.parse_args()
    probe()
