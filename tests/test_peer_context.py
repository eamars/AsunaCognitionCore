from copy import deepcopy

from asuna.peer_context import apply_peer_context, snapshot_event
from asuna.router import Router


def qq_event():
    return {
        'event_id': 'channel-test-peer',
        'scene_id': 'qq:999:group:123',
        'person_id': 'qq:42',
        'text': '@小满 我现在的群名片是什么？',
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


def test_authenticated_peer_snapshot_projects_distinct_qq_fields():
    event = qq_event()
    profile = snapshot_event(event)
    assert profile and profile['person_id'] == event['person_id']
    context = {}
    row = {'author': event['person_id'], 'event': {**event, 'raw': {'asuna_peer': profile}}}
    line, reason = apply_peer_context(context, row)
    assert not reason and line == context['sender_identity']
    assert '本群群名片 群名片' in line
    assert 'QQ 昵称 QQ昵称' in line
    assert '本群身份 管理员' in line
    assert 'QQ 平台已核实' in line


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


def test_adapter_bootstrap_time_and_count_do_not_describe_relationship():
    event = qq_event()
    event['channel']['target'] = {'type': 'dm', 'id': '42'}
    peer = event['raw']['asuna_peer']
    peer['scene'] = 'dm'
    peer.pop('group_id')
    peer['known_since'] = '2026-09-23T13:17:37Z'
    peer['seen_messages'] = 2
    profile = snapshot_event(event)
    assert profile['known_since'] == peer['known_since']
    assert profile['seen_messages'] == 2
    line, reason = apply_peer_context({}, {'author': 'qq:42', 'event': {**event, 'raw': {'asuna_peer': profile}}})
    assert not reason
    assert '自 2026-09-23 认识' not in line
    assert '这个场景里第 2 条' not in line
    assert 'QQ 平台已核实' in line


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
