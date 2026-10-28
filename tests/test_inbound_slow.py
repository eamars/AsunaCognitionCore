"""A slow channel admission records where it waited (host.inbound_slow); a fast one records nothing, and a failure to
record never fails the admission."""
import threading
from types import SimpleNamespace

from asuna import channels as channels_module
from asuna.channels import Channels


class Evidence:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def record(self, kind, payload):
        if self.fail:
            raise OSError('EVIDENCE_UNAVAILABLE')
        self.rows.append((kind, payload))


def channels_over(evidence, admit):
    controller = SimpleNamespace(ingress_lock=threading.RLock(), ingress_timing=threading.local(), reconfiguring=False,
                                 stopping=threading.Event(), app=SimpleNamespace(evidence=evidence))
    channels = Channels.__new__(Channels)
    channels.controller = controller

    def _receive(channel_id, body):
        return admit(controller.ingress_timing)
    channels._receive = _receive
    return channels


def test_a_slow_admission_records_its_stages(monkeypatch):
    clock = iter([100.0, 100.5, 104.0])
    monkeypatch.setattr(channels_module.time, 'monotonic', lambda: next(clock))
    evidence = Evidence()

    def admit(timing):
        timing.persist, timing.project, timing.channel_input, timing.output_lock_wait, timing.output_write = (
            0.2, 3.0, 0.1, 2.8, 0.05)
        return {'status': 'accepted'}
    assert channels_over(evidence, admit).receive('qq', {}) == {'status': 'accepted'}
    [(kind, payload)] = evidence.rows
    assert kind == 'host.inbound_slow'
    assert payload == {'channel_id': 'qq', 'total': 4.0, 'fence_wait': 0.5, 'persist': 0.2, 'project': 3.0,
                       'channel_input': 0.1, 'output_lock_wait': 2.8, 'output_write': 0.05, 'other': 0.3}


def test_a_fast_admission_records_nothing():
    evidence = Evidence()
    assert channels_over(evidence, lambda timing: {'status': 'accepted'}).receive('qq', {}) == {'status': 'accepted'}
    assert evidence.rows == []


def test_a_failure_to_record_is_not_the_admission_s(monkeypatch):
    clock = iter([0.0, 0.0, 9.0])
    monkeypatch.setattr(channels_module.time, 'monotonic', lambda: next(clock))
    assert channels_over(Evidence(fail=True), lambda timing: {'status': 'duplicate'}).receive('qq', {}) == {
        'status': 'duplicate'}


def test_the_timing_of_one_admission_does_not_carry_into_the_next():
    evidence = Evidence()
    channels = channels_over(evidence, lambda timing: {'kept': sorted(vars(timing))})
    channels.controller.ingress_timing.persist = 7.0          # left by an earlier admission on this thread
    assert channels.receive('qq', {}) == {'kept': []}
