"""A running command does not hold the database effects lock (every outbox claim and cancellation needs it); a
cancellation during the command still keeps its result from being recorded."""
import threading

import pytest

from asuna.queue import database_effects_lock
from asuna.sandbox import Sandbox
from asuna.state import Denied
from test_engineering_m3 import task_setup


def test_a_running_command_leaves_the_lock_free_and_a_cancel_during_it_still_fences(store, monkeypatch):
    service, task, broker, work = task_setup(store)
    seen = {}

    def run(self, argv, **kwargs):
        def other():                                    # an outbox claim on another thread
            with database_effects_lock(store.name):
                seen['free'] = True
        claim = threading.Thread(target=other)
        claim.start(); claim.join(5)
        service.cancel(task['_id'], person_id='A')     # cancelled while the command runs
        return {'exit_code': 0, 'stdout': '', 'stderr': ''}
    monkeypatch.setattr(Sandbox, 'run', run)
    try:
        with pytest.raises(Denied):
            broker.call('s-test', 'long', 'sandbox_run', {'argv': ['python3', '-c', 'pass']})
        assert seen.get('free'), 'the claim got the lock while the command ran'
        row = store.db.artifacts.find_one({'task_id': task['_id'], 'tool': 'sandbox_run'})
        assert row['state'] != 'DONE', 'a command finished after the cancel is not recorded as done'
    finally:
        broker.close()
