"""Her credential vault (owner 2026-10-07) on MongoDB: filed at home, used blind by one command of a home task; its
value never reaches the model, a receipt or the audit, and the tool is offered at home only (leak)."""
import pytest

from asuna import credentials, role_tools, sandbox_backend, visibility
from asuna.state import Denied

from turn_parts import task_setup

pytestmark = pytest.mark.world                # `store` is the fixture world

SECRET = 'Pa55!word-for-test'


@pytest.fixture
def vault():
    """DSH's credential store as the Host serves it (credentialRecords): records by name, payload {note, env}."""
    records = {}

    def host(args):
        op = args['op']
        if op == 'list':
            return [{'name': name, 'note': p['note'], 'env': list(p['env'])} for name, p in records.items()]
        if op == 'read':
            return records.get(args['name'])
        if op == 'write':
            records[args['name']] = {'note': args['note'], 'env': args['env']}
            return {'written': args['name']}
        if op == 'delete':
            records.pop(args['name'], None)
            return {'deleted': args['name']}
    credentials.attach(host)
    yield records
    credentials.attach(None)


@pytest.fixture
def host_runs_commands():
    """The Host's sandbox as the worker asks it, passing the command through: its confinement is not what this file
    guards (the unit run's DSH sandbox is not set up here), what reaches the command and the records is."""
    sandbox_backend.attach(lambda argv, root: list(argv))
    yield
    sandbox_backend.attach(None)


def test_a_home_task_runs_one_command_with_the_credential_and_never_sees_it(store, vault, host_runs_commands):
    credentials.keep('solar', '主人的光伏账号，只读', {'SOLAR_PASSWORD': SECRET})
    service, task, broker, work = task_setup(store)
    try:
        echo = ['python3', '-c', "import os; print('got', os.environ.get('SOLAR_PASSWORD'))"]
        result = broker.call('s-test', 'with', 'sandbox_run', {'argv': echo, 'credentials': ['solar']})
        assert result['exit_code'] == 0 and result['stdout'].strip() == 'got [凭据已隐藏]'      # set, and hidden
        stored = store.raw.artifacts.find_one({'_id': result['evidence_ref']})
        assert SECRET not in str(stored)                                                   # nor in the receipt
        plain = broker.call('s-test', 'without', 'sandbox_run', {'argv': echo})
        assert plain['stdout'].strip() == 'got None'                                       # only that one command
        # A task from a public conversation never gets one.
        store.raw.tasks.update_one({'_id': task['_id']}, {'$set': {'requester_id': 'stranger'}})
        original = credentials.home_task
        credentials.home_task = lambda store, task: False
        try:
            with pytest.raises(Denied, match='CREDENTIALS_HOME_ONLY'):
                broker.call('s-test', 'public', 'sandbox_run', {'argv': echo, 'credentials': ['solar']})
        finally:
            credentials.home_task = original
    finally:
        broker.close()


def test_the_vault_tool_is_offered_at_home_only(store):
    words = role_tools.TOOLS['credential']['description']
    assert '值只在 keep 这一次写' in words and 'sandbox_run' in words
    turn = lambda cls, kind='external': role_tools.exposed(store, {
        '_id': 'ep-x', 'scene_id': store.config['chat']['scene_id'], 'person_id': store.config['chat']['person_id'],
        'episode_kind': kind, 'manifest': {'session_class': cls}, 'context': {}})
    assert 'credential' in turn(visibility.OWNER_PRIVATE)
    assert 'credential' in turn(visibility.OWNER_PRIVATE, 'task_feedback')
    assert 'credential' not in turn(visibility.PUBLIC)
    assert 'credential' not in turn(visibility.OWNER_PRIVATE, 'settlement')


def test_a_credential_value_never_reaches_the_audit(store, vault):
    # Her keep call carries the values once; the audit keeps the names and the note, never a value.
    ep = store.put('episodes', {'_id': 'ep-cred', 'source_event_id': 'ep-cred', 'episode_kind': 'external',
                                'scene_id': store.config['chat']['scene_id'], 'scope_key': 'scene:local',
                                'tool_calls': {}}, stream='ep-cred')
    class Coordinator:              # what RoleTools._record uses: the store and a revision-checked write back
        def __init__(self, store):
            self.store = store

        def _update(self, ep, **changes):
            return self.store.put('episodes', {**ep, **changes}, expected=ep['revision'], stream=ep['_id'])
    handler = role_tools.RoleTools(Coordinator(store))
    args = {'op': 'keep', 'name': 'solar', 'note': '只读', 'env': {'SOLAR_PASSWORD': SECRET}}
    handler._record(ep['_id'], 'call-1', 'credential', args, result={'kept': 'solar'})
    row = store.raw.audit_events.find_one({'type': 'role_tool', 'stream_id': 'ep-cred'})
    assert SECRET not in str(row) and 'SOLAR_PASSWORD' in str(row) and '[凭据已隐藏]' in str(row)
    assert args['env']['SOLAR_PASSWORD'] == SECRET            # the call itself is untouched
