from copy import deepcopy

from asuna.peer_context import apply_peer_context, snapshot_event
from asuna.router import Router


def qq_event():
    return {
        'event_id': 'channel-test-peer',
        'scene_id': 'qq:999:group:123',
        'person_id': 'qq:42',
        'text': '@演示 我现在的群名片是什么？',
        'group_context': {'wake_reason': 'mention'},
        'channel': {'sender_id': '42', 'target': {'type': 'group', 'id': '123'}},
        'raw': {
            'asana_untrusted': 'do not copy this into context',
            'asuna_peer': {
                'person_id': 'qq:42', 'account_id': '42', 'scene': 'group:123',
                'group_id': '123', 'display': '群名片', 'card': '群名片',
                'nickname': 'QQ昵称', 'role': 'admin', 'source': 'api',
                'verified': True, 'profile_at': '2026-09-24T01:00:00Z',
            },
        },
    }


def test_peer_snapshot_rejects_mismatched_sender_and_group():
    for change in (
        lambda event: event['raw']['asuna_peer'].update(person_id='qq:77'),
        lambda event: event['raw']['asuna_peer'].update(account_id='77'),
        lambda event: event['raw']['asuna_peer'].update(group_id='456'),
        lambda event: event['channel']['target'].update(id='456'),
    ):
        event = qq_event()
        change(event)
        assert snapshot_event(event) is None
    row = {'author': 'qq:77', 'event': qq_event()}
    context = {}
    assert apply_peer_context(context, row)[0] is None
    assert 'sender_identity' not in context


def test_router_persists_only_verified_peer_slot_for_awake_input():
    class Store:
        def authorize(self, scene_id, person_id):
            return {'_id': scene_id, 'kind': 'group', 'scope_key': 'scope:123'}

        def audit(self, *args):
            pass

    class Coordinator:
        received = None

        def ingest(self, event, *, persona='P1'):
            self.received = event
            return {'state': 'COMMITTED'}

    coordinator = Coordinator()
    router = Router(Store(), coordinator)
    router.receive(qq_event())
    assert coordinator.received['channel']['sender_id'] == '42'
    assert set(coordinator.received['raw']) == {'asuna_peer'}
    assert coordinator.received['raw']['asuna_peer']['person_id'] == 'qq:42'

    forged = deepcopy(qq_event())
    forged['raw']['asuna_peer']['group_id'] = '456'
    router.receive(forged)
    assert 'raw' not in coordinator.received
