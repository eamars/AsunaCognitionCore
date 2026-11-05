"""UNKNOWN (send result unconfirmed) does not cancel the later parts of a turn; FAILED still does (ADR-009 §11.1, addendum).

The records are real: the in-memory store (`store` fixture, asuna.store.memory) holds the scene and the part rows, and the
code under test is the real Coordinator.queue_reply / publish_queued, PublishService.cancel_after and Channels._next.
Only the platform's answer is scripted: ScriptedPublisher.publish settles each part in the state the script names.
"""
import pytest

from asuna import channels, coordinator, publish
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records

EP_ID, SCENE_ID, SCOPE, CHANNEL = 'ep-1', 'scene-1', 'scope-1', 'chan-1'
CANCELLED = 'CANCELLED_AFTER_FAILURE'
EP = {'_id': EP_ID, 'scene_id': SCENE_ID, 'scope_key': SCOPE, 'policy_epoch': 1, 'persona': 'P1'}
PLANNED = [{'kind': 'picture', 'text': 'img', 'shown': 'img'}, {'kind': 'text', 'text': 'a', 'shown': 'a'},
           {'kind': 'text', 'text': 'b', 'shown': 'b'}]


class ScriptedPublisher:
    """publish() settles a part in the state the script names for its segment (the platform's answer); cancel_after is the real one."""

    def __init__(self, store, script):
        self.store, self.script, self.sent = store, script, []
        self.real = publish.PublishService(store)

    def publish(self, key):
        self.sent.append(key)
        row = message_records.get(self.store, key)
        state = self.script.get(row['segment_index'], 'DELIVERED')
        return message_records.save(self.store, {**row, 'delivery_state': state}, expected=row['revision'], stream=EP_ID)

    def cancel_after(self, published):
        return self.real.cancel_after(published)


def _scene(store):
    scene_records.save(store, {'_id': SCENE_ID, 'scope_key': SCOPE, 'policy_epoch': 1, 'sequence': 0})


def _coordinator(store, script):
    _scene(store)
    c = coordinator.Coordinator.__new__(coordinator.Coordinator)
    c.store, c.crash = store, lambda point: None
    c.publisher = ScriptedPublisher(store, script)
    return c


def _part(store, index, state, **more):
    key = '%s:speak:%d' % (EP_ID, index)
    return message_records.save(store, {'_id': key, 'publication_key': key, 'episode_id': EP_ID, 'scene_id': SCENE_ID,
                                        'scope_key': SCOPE, 'policy_epoch': 1, 'direction': 'outbound', 'phase': 'SPEAK',
                                        'segment_index': index, 'reply_part': True, 'delivery_state': state, **more},
                                stream=EP_ID)


def _states(store):
    return [message_records.get(store, '%s:speak:%d' % (EP_ID, i))['delivery_state'] for i in range(3)]


@pytest.mark.parametrize('first, sent, want', [
    ('UNKNOWN', 3, ['UNKNOWN', 'DELIVERED', 'DELIVERED']),                    # A
    ('FAILED', 1, ['FAILED', CANCELLED, CANCELLED]),                          # B: FAILED still cancels the rest
], ids=['A-queue_reply-part0-UNKNOWN', 'B-queue_reply-part0-FAILED'])
def test_queue_reply(store, first, sent, want):
    c = _coordinator(store, {0: first})
    queued = c.queue_reply(EP, PLANNED)
    assert len(c.publisher.sent) == sent
    assert _states(store) == want
    assert [item['state'] for item in queued] == want


@pytest.mark.parametrize('first, sent, want', [
    ('UNKNOWN', 3, ['UNKNOWN', 'DELIVERED', 'DELIVERED']),                    # C
    ('FAILED', 1, ['FAILED', CANCELLED, CANCELLED]),                          # C2
], ids=['C-publish_queued-part0-UNKNOWN', 'C2-publish_queued-part0-FAILED'])
def test_publish_queued(store, first, sent, want):
    c = _coordinator(store, {0: first})
    for i in range(3):
        _part(store, i, 'READY')
    c.publish_queued(EP_ID)
    assert len(c.publisher.sent) == sent
    assert _states(store) == want


@pytest.mark.parametrize('state, want', [
    ('UNKNOWN', ['UNKNOWN', 'READY', 'READY']),                               # D: the receipt path cancels nothing
    ('FAILED', ['FAILED', CANCELLED, CANCELLED]),                             # D2
], ids=['D-cancel_after-UNKNOWN', 'D2-cancel_after-FAILED'])
def test_cancel_after(store, state, want):
    _scene(store)
    for i in range(3):
        _part(store, i, state if i == 0 else 'READY')
    publish.PublishService(store).cancel_after(message_records.get(store, EP_ID + ':speak:0'))
    assert _states(store) == want


@pytest.mark.parametrize('state, handed_out, part1', [
    ('UNKNOWN', True, 'QUEUED_EXTERNAL'),                                     # E: handed out behind an UNKNOWN part
    ('FAILED', False, CANCELLED),                                             # E2: cancelled behind a FAILED one
    ('SENDING', False, 'QUEUED_EXTERNAL'),                                    # E3: still on its way holds it (unchanged)
], ids=['E-next-part0-UNKNOWN', 'E2-next-part0-FAILED', 'E3-next-part0-SENDING'])
def test_next(store, state, handed_out, part1):
    _part(store, 0, state, channel_id=CHANNEL, scene_seq=1)
    _part(store, 1, 'QUEUED_EXTERNAL', channel_id=CHANNEL, scene_seq=2, queued_at='2026-11-05T00:00:00+00:00')
    ch = channels.Channels.__new__(channels.Channels)
    ch.store = store
    got = ch._next(CHANNEL, message_records.queued(store, CHANNEL))
    assert (got or {}).get('_id') == (EP_ID + ':speak:1' if handed_out else None)
    assert message_records.get(store, EP_ID + ':speak:1')['delivery_state'] == part1
