"""UNKNOWN (send result unconfirmed) does not cancel the later parts of a turn; FAILED still does.
Instance: 11-05 retcode 1200 image part -> UNKNOWN, two text parts cancelled although the image was on the platform.
Mocks the message-records layer only; the code under test is the real Coordinator.queue_reply / publish_queued,
PublishService.cancel_after and Channels._next.   Run: PYTHONPATH=src python3 tests/unknown_no_cascade_cases.py
"""
import sys
import types

sys.path.insert(0, 'src')
sys.path.insert(0, 'tests')
from asuna import coordinator, publish, channels, render, rhythm, persona_model, stickers   # noqa: E402

ROWS = {}


class FakeView:
    def __init__(self, rows):
        self._rows = rows

    def rows(self, fields=None):
        return [dict(r) for r in self._rows]


def fake_turn_parts(store, episode, *, states=None, not_states=None, after_segment=None, before_segment=None,
                    state=None, reply_parts=False, by=None, **kw):
    out = [r for r in ROWS.values() if r['episode_id'] == episode]
    if after_segment is not None:
        out = [r for r in out if r['segment_index'] > after_segment]
    if before_segment is not None:
        out = [r for r in out if r['segment_index'] < before_segment]
    if states is not None:
        out = [r for r in out if r['delivery_state'] in states]
    if state is not None:
        out = [r for r in out if r['delivery_state'] == state]
    if not_states is not None:
        out = [r for r in out if r['delivery_state'] not in not_states]
    return FakeView(sorted(out, key=lambda r: r['segment_index']))


def fake_save(store, row, expected=None, stream=None):
    row = {**row, 'revision': row.get('revision', 0) + 1}
    ROWS[row['_id']] = row
    return row


for name, fn in (('turn_parts', fake_turn_parts), ('save', fake_save)):
    setattr(coordinator.message_records, name, fn)
coordinator.message_records.get = lambda store, key, **kw: ROWS.get(key)
coordinator.scene_records.get = lambda *a, **k: {'channel_id': None}
_seq = iter(range(1, 100))
coordinator.scene_records.next_seq = lambda *a, **k: next(_seq)
coordinator.character_id = lambda config: 'xm'
render.model_and_policy = lambda store, persona: ({}, {})
persona_model.effective = lambda *a, **k: 12
rhythm.pacing = lambda texts, start, *a: [start] * len(texts)


class Store:
    config = {}


class ScriptedPublisher:
    """Real cancel_after; publish() returns the scripted state for each part (the platform's answer)."""

    def __init__(self, script):
        self.script, self.sent = script, []
        self.real = publish.PublishService(Store())

    def publish(self, key):
        self.sent.append(key)
        row = ROWS[key]
        state = self.script.get(row['segment_index'], 'DELIVERED')
        ROWS[key] = {**row, 'delivery_state': state}
        return dict(ROWS[key])

    def cancel_after(self, published):
        return self.real.cancel_after(published)


def make(script):
    ROWS.clear()
    c = coordinator.Coordinator.__new__(coordinator.Coordinator)
    c.store, c.crash = Store(), lambda point: None
    c.publisher = ScriptedPublisher(script)
    return c


EP = {'_id': 'ep-1', 'scene_id': 's', 'scope_key': 'k', 'policy_epoch': 1, 'persona': 'P1'}
PLANNED = [{'kind': 'picture', 'text': 'img', 'shown': 'img'}, {'kind': 'text', 'text': 'a', 'shown': 'a'},
           {'kind': 'text', 'text': 'b', 'shown': 'b'}]


def states():
    return [ROWS['ep-1:speak:%d' % i]['delivery_state'] for i in range(3)]


def scenario_AB(first_state):
    c = make({0: first_state})
    c.queue_reply(EP, PLANNED)
    return c.publisher.sent, states()


def check(label, cond, detail):
    print(('PASS ' if cond else 'FAIL ') + label, detail)
    return cond


ok = True
sent, st = scenario_AB('UNKNOWN')
ok &= check('A part0=UNKNOWN: part1/2 sent, part0 stays UNKNOWN', len(sent) == 3 and st[0] == 'UNKNOWN'
            and 'CANCELLED_AFTER_FAILURE' not in st, (len(sent), st))
sent, st = scenario_AB('FAILED')
ok &= check('B part0=FAILED: part1/2 cancelled as before', len(sent) == 1 and st == ['FAILED'] + ['CANCELLED_AFTER_FAILURE'] * 2,
            (len(sent), st))

# C: the restart-recovery path, publish_queued: rows already written READY, part0 answers UNKNOWN / FAILED
for label, first, want_sent, want in (('C part0=UNKNOWN', 'UNKNOWN', 3, ['UNKNOWN', 'DELIVERED', 'DELIVERED']),
                                      ('C2 part0=FAILED', 'FAILED', 1, ['FAILED'] + ['CANCELLED_AFTER_FAILURE'] * 2)):
    c = make({0: first})
    for i in range(3):
        ROWS['ep-1:speak:%d' % i] = {'_id': 'ep-1:speak:%d' % i, 'episode_id': 'ep-1', 'segment_index': i,
                                     'delivery_state': 'READY', 'revision': 1}
    coordinator.message_records.turn_parts = lambda store, ep, *, states=None, **kw: (
        fake_turn_parts(store, ep, state='READY', **{k: v for k, v in kw.items() if k in ('after_segment',)})
        if kw.get('speech') is False else fake_turn_parts(store, ep, states=states, **kw))
    c.publish_queued('ep-1')
    coordinator.message_records.turn_parts = fake_turn_parts
    # the part rows are READY when the loop begins, so snapshot-per-row reads see later parts READY (as in real code)
    ok &= check(label + ' via publish_queued', len(c.publisher.sent) == want_sent and states() == want,
                (len(c.publisher.sent), states()))

# D: receipt path / recover_sending: cancel_after with an UNKNOWN row cancels nothing, with FAILED cancels
for label, state, want in (('D UNKNOWN receipt cancel_after', 'UNKNOWN', ['UNKNOWN', 'READY', 'READY']),
                           ('D2 FAILED receipt cancel_after', 'FAILED', ['FAILED'] + ['CANCELLED_AFTER_FAILURE'] * 2)):
    make({})
    for i in range(3):
        ROWS['ep-1:speak:%d' % i] = {'_id': 'ep-1:speak:%d' % i, 'episode_id': 'ep-1', 'segment_index': i,
                                     'delivery_state': 'READY', 'revision': 1}
    ROWS['ep-1:speak:0']['delivery_state'] = state
    publish.PublishService(Store()).cancel_after(dict(ROWS['ep-1:speak:0']))
    ok &= check(label, states() == want, states())

# E: Channels._next: part1 queued behind an UNKNOWN part0 is handed out; behind a FAILED one it is cancelled
publish.message_records.turn_parts = fake_turn_parts
publish.message_records.save = fake_save
channels.message_records.turn_parts = fake_turn_parts
channels.message_records.save = fake_save
channels.message_records.in_flight_scenes = lambda *a, **k: set()
for label, state, want_row in (('E part0=UNKNOWN -> part1 handed out', 'UNKNOWN', 'ep-1:speak:1'),
                               ('E2 part0=FAILED -> part1 cancelled', 'FAILED', None)):
    make({})
    ROWS['ep-1:speak:0'] = {'_id': 'ep-1:speak:0', 'episode_id': 'ep-1', 'segment_index': 0, 'delivery_state': state, 'revision': 1}
    ROWS['ep-1:speak:1'] = {'_id': 'ep-1:speak:1', 'episode_id': 'ep-1', 'segment_index': 1, 'delivery_state': 'QUEUED_EXTERNAL',
                            'revision': 1, 'scene_id': 's', 'scene_seq': 2, 'queued_at': 'x'}
    ch = channels.Channels.__new__(channels.Channels)
    ch.store = Store()
    got = ch._next('c', FakeView([ROWS['ep-1:speak:1']]))
    ok &= check(label, (got or {}).get('_id') == want_row and
                bool(want_row or ROWS['ep-1:speak:1']['delivery_state'] == 'CANCELLED_AFTER_FAILURE'),
                (got and got['_id'], ROWS['ep-1:speak:1']['delivery_state']))

print('ALL PASS' if ok else 'SOME FAIL')
sys.exit(0 if ok else 1)
