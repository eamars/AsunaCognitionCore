"""A slow channel admission records where it waited (host.inbound_slow); a fast one records nothing, and a failure to
record never fails the admission."""
import threading
from types import SimpleNamespace

from asuna import channels as channels_module
from asuna.channels import Channels
from asuna.chat import INGRESS_TIMING


class Evidence:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def record(self, kind, payload):
        if self.fail:
            raise OSError('EVIDENCE_UNAVAILABLE')
        self.rows.append((kind, payload))


def channels_over(evidence, admit):
    controller = SimpleNamespace(ingress_lock=threading.RLock(), reconfiguring=False, stopping=threading.Event(),
                                 app=SimpleNamespace(evidence=evidence))
    channels = Channels.__new__(Channels)
    channels.controller = controller

    def _receive(channel_id, body):
        return admit(INGRESS_TIMING)
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
    INGRESS_TIMING.persist = 7.0                              # left by an earlier admission on this thread
    assert channels.receive('qq', {}) == {'kept': []}


def test_an_emit_notes_its_output_lock_wait_and_its_write(capsys):
    from asuna.native_worker import BusinessWorker
    worker = BusinessWorker()
    worker.emit({'kind': 'probe'})
    assert capsys.readouterr().out == '{"kind": "probe"}\n'
    assert set(vars(worker.emit_timing)) == {'output_lock_wait', 'output_write'}
    assert all(value >= 0 for value in vars(worker.emit_timing).values())


def test_a_slow_admission_carries_every_thread_s_stack_from_inside_it(monkeypatch):
    import re
    import time
    monkeypatch.setattr(channels_module, 'STACKS_AFTER_SECONDS', 0.01)
    monkeypatch.setattr(channels_module, 'INBOUND_SLOW_SECONDS', 0.0)
    release = threading.Event()

    def hold_the_line():
        release.wait(5)
    holder = threading.Thread(target=hold_the_line, name='holder', daemon=True)
    holder.start()
    evidence = Evidence()

    def admit_slowly(timing):
        time.sleep(0.3)
        return {'status': 'accepted'}
    try:
        channels_over(evidence, admit_slowly).receive('qq', {})
    finally:
        release.set()
    [(kind, payload)] = evidence.rows
    assert payload['stacks_at'] >= 0.01
    stacks = payload['stacks']
    assert stacks['admission'][-1].endswith(' admit_slowly')
    assert any(line.endswith(' hold_the_line') for line in stacks['holder'])
    lines = [line for stack in stacks.values() for line in stack]
    assert lines and all(re.fullmatch(r'[^:/\\]+:\d+ [\w<>.]+', line) for line in lines)   # file names and code only


def test_a_fast_admission_takes_no_snapshot(monkeypatch):
    import time
    monkeypatch.setattr(channels_module, 'STACKS_AFTER_SECONDS', 0.05)
    taken = []
    monkeypatch.setattr(channels_module, 'thread_stacks', lambda admitting: taken.append(admitting) or {})
    channels_over(Evidence(), lambda timing: {'status': 'accepted'}).receive('qq', {})
    time.sleep(0.15)
    assert taken == []
