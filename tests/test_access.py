"""The access table (ADR-120 landing 1): one place for who may use what. Its defaults, the page's copy of them and
the checks of the setting; the origin of a turn and of a task; and the fences that ask it, at grant time and at call
time, on the fixture world in memory (test_whose's home: the Web chat, an agent line, g1 outside, g2 a home group)."""
import re
import time

import pytest

from asuna import access, credentials, guard, notes, role_tools, tasks, vision, whose
from asuna.config import ROOT
from asuna.records import tasks as task_records
from asuna.state import Denied
from test_whose import AGENT, LINE, LOCAL, OWNER, coordinator, home, turn  # noqa: F401  (home, coordinator: fixtures)

# §3.2 of ADR-120, as agreed with the owner on 2026-11-25.
AGREED = {'own_files': 'everywhere', 'all_files': 'home_from_outside', 'list_files': 'home_from_outside',
          'disk': 'home', 'commands': 'home', 'credentials': 'home', 'local_network': 'home', 'internet': 'everywhere',
          'integrations': 'home', 'development': 'home', 'drawing': 'everywhere', 'send_any': 'home',
          'send_to_asker': 'home_from_outside', 'send_own': 'everywhere'}
PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')


def test_the_default_table_is_the_agreed_one_and_the_page_draws_every_row():
    assert access.RESOURCES == AGREED
    client = (ROOT / 'packages/cognition-core/src/client.js').read_text(encoding='utf-8')
    rows = re.search(r'const ACCESS_ROWS = \[(.*?)\];', client, re.S).group(1)
    assert re.findall(r"\['(\w+)', '(\w+)'\]", rows) == list(AGREED.items())
    # Each row has its words in both languages of the page.
    assert [row for row in AGREED if client.count("'settings.access.row.%s'" % row) != 2] == []
    # A level allows its origin and every origin left of it, so a row is never "outside yes, home no".
    for level, reach in access.REACH.items():
        assert reach == access.ORIGINS[:len(reach)], level


@pytest.mark.parametrize('setting, words', [({'printer': 'home'}, 'printer'), ({'commands': 'sometimes'}, 'sometimes'),
                                            ({'integrations': 'everywhere'}, 'integrations'),
                                            ({'development': 'home_from_outside'}, 'development'),
                                            ('commands: none', 'table')])
def test_a_bad_setting_is_refused_with_its_name(setting, words):
    with pytest.raises(ValueError) as caught:
        access.check({'access': setting})
    assert str(caught.value).startswith('INVALID_ACCESS') and words in str(caught.value)


def test_the_setting_overlays_the_defaults_and_wider_rows_are_named():
    config = {'access': {'commands': 'none', 'disk': 'home_from_outside', 'development': 'none'}}
    access.check(config)
    assert access.table(config) == {**AGREED, **config['access']}
    assert access.wider(config) == {'disk': 'home_from_outside'} and access.wider({}) == {}
    assert not access.allowed(config, 'home', 'commands') and access.allowed(config, 'home_from_outside', 'disk')


def test_the_origin_of_a_turn(home):
    store = home
    assert access.origin_of_turn(store, turn(store, LOCAL, OWNER, 'o1')) == 'home'
    assert access.origin_of_turn(store, turn(store, 'g2', 'C', 'o2')) == 'home'           # a home group
    assert access.origin_of_turn(store, turn(store, 'g1', 'A', 'o3')) == 'outside'
    # A home turn a note from outside opened is outside; an errand turn acts with home's authority.
    writer = turn(store, 'g1', 'A', 'o4')
    store.put('notes', {'_id': 'note-out', 'from_episode': writer['_id'], 'from_scene': 'g1', 'from_class': 'public',
                        'trust': notes.UNTRUSTED, 'to_scene': LOCAL})
    opened = turn(store, LOCAL, OWNER, 'o5', kind='note', note={'id': 'note-out'}, adapter_id='note')
    assert access.origin_of_turn(store, opened) == 'outside'
    sent = turn(store, LOCAL, OWNER, 'o6')
    errand = turn(store, 'g1', 'A', 'o7', episode={'errand': {'from': sent['_id'], 'scene_id': LOCAL}})
    assert access.origin_of_turn(store, errand) == 'home'


def test_the_origin_of_a_task_is_written_once_and_never_widens(coordinator):
    store = coordinator.store
    at_home = coordinator.delegate(turn(store, LOCAL, OWNER, 't1'), 'c1', '标题', '交代')
    outside = coordinator.delegate(turn(store, 'g1', 'A', 't2'), 'c2', '标题', '交代')
    named = whose.record('outside', 'g1', chosen=True)
    for_outside = coordinator.delegate(turn(store, LINE, AGENT, 't3'), 'c3', '标题', '交代', whose=named)
    assert [row['origin'] for row in (at_home, outside, for_outside)] == ['home', 'outside', 'home_from_outside']
    # Its continuation from a home turn keeps the earlier task's origin.
    done = task_records.get(store, for_outside['_id'])
    store.put('tasks', {**done, 'state': 'RETURNED'}, expected=done['revision'])
    said = coordinator.message_action(turn(store, LOCAL, OWNER, 't4'), 'c4', task_records.get(store, done['_id']), '再做')
    continued = task_records.get(store, said['task'])
    assert continued['origin'] == 'home_from_outside' and 'sandbox_run' not in continued['allowed_capabilities']
    # A row without `origin` (made before it was stored) gets it by the same rule when read, never written back.
    for row, expected in ((at_home, 'home'), (outside, 'outside'), (for_outside, 'home_from_outside'),
                          (continued, 'home_from_outside')):
        current = task_records.get(store, row['_id'])
        old = store.put('tasks', {k: v for k, v in current.items() if k != 'origin'}, expected=current['revision'])
        assert access.origin_of_task(store, old) == expected, row['_id']
        assert 'origin' not in task_records.get(store, row['_id'])
    # The result turn of work for someone outside is that work's origin, so her read_image there reads no disk path.
    result_turn = turn(store, LOCAL, OWNER, 't5', episode={'episode_kind': 'task_feedback', 'task_id': for_outside['_id']})
    assert access.origin_of_turn(store, result_turn) == 'home_from_outside'
    store.config['character'] = {**(store.config.get('character') or {}), 'input_modalities': ['text', 'image']}
    with pytest.raises(Denied) as caught:
        coordinator.tools.tool_read_image(result_turn, 'call-r', {'ref': 'C:/no/such/picture.png'})
    assert role_tools.words(caught.value) == access.FROM_OUTSIDE


def test_an_old_task_is_read_by_the_turn_that_made_it_and_by_its_place_only_when_that_turn_is_gone(home):
    store = home
    writer = turn(store, 'g1', 'A', 'm1')
    store.put('notes', {'_id': 'note-m', 'from_episode': writer['_id'], 'from_scene': 'g1', 'from_class': 'public',
                        'trust': notes.UNTRUSTED, 'to_scene': LOCAL})
    opened = turn(store, LOCAL, OWNER, 'm2', kind='note', note={'id': 'note-m'}, adapter_id='note')
    # Made in a home turn a note from outside opened: it runs in the local chat for the owner, and is outside.
    old = store.put('tasks', {'_id': 'task-old-note', 'request_key': 'task-old-note', 'scene_id': LOCAL,
                              'requester_id': OWNER, 'episode_id': opened['_id'], 'state': 'RETURNED'})
    assert access.origin_of_task(store, old) == 'outside'
    # Its turn gone, the place it runs in decides.
    store.collection('episodes').delete({'_id': opened['_id']})
    assert access.origin_of_task(store, old) == 'home'


def running(store, task):
    current = task_records.get(store, task['_id'])
    return store.put('tasks', {**current, 'state': 'RUNNING', 'lease_expires_at': time.time() + 600},
                     expected=current['revision'])


def broker_for(store, task, tmp_path):
    from test_data_child import Recorded
    broker = tasks.ToolBroker(tasks.TaskService(store), Recorded())
    broker.bindings['session'] = (task, type('Sandbox', (), {'task_dir': tmp_path, 'protected_paths': []})())
    return broker


def refused(broker, tool, args):
    with pytest.raises(Denied) as caught:
        broker.call('session', 'call-%d' % time.monotonic_ns(), tool, args)
    return str(caught.value)


def test_work_from_outside_done_at_home_has_no_commands_keys_home_network_or_disk(coordinator, tmp_path):
    store = coordinator.store
    named = whose.record('outside', 'g1', chosen=True)
    task = running(store, coordinator.delegate(turn(store, LINE, AGENT, 'h1'), 'c1', '标题', '交代', whose=named))
    assert task['origin'] == 'home_from_outside' and task['network'] == 'public'
    assert 'sandbox_run' not in task['allowed_capabilities'] and 'web_fetch' in task['allowed_capabilities']
    assert not credentials.home_task(store, task) and not guard.task_outside(store, task)
    broker = broker_for(store, task, tmp_path)
    words = 'ACCESS_DENIED_COMMANDS: ' + access.FROM_OUTSIDE
    assert refused(broker, 'sandbox_run', {'argv': ['python3', '-V']}) == words
    assert refused(broker, 'sandbox_run', {'argv': ['python3', '-V'], 'credentials': ['x']}) == words
    # Its fetch of a local address ends with the same sentence (the binding's words), not the outside one.
    from asuna.native_worker import BusinessWorker
    worker = BusinessWorker.__new__(BusinessWorker)
    worker.app = type('App', (), {'store': store, 'config': store.config})()
    assert worker.task_access(task)['network_refused'] == access.FROM_OUTSIDE
    assert 'network_refused' not in worker.task_access(running(store, coordinator.delegate(
        turn(store, 'g1', 'A', 'h2'), 'c2', '标题', '交代')))


def test_a_disk_path_is_read_only_where_the_table_allows_it_in_her_words(home, tmp_path):
    picture = tmp_path / 'p.png'
    picture.write_bytes(PNG)
    where = {'scene_id': LOCAL, 'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1}

    def read(origin, config=home.config):
        return vision.read_image_for_task(home, None, where, config, {'ref': str(picture)}, look=False, origin=origin)
    assert read('home')['bytes'] == len(PNG)
    for origin, words in (('home_from_outside', access.FROM_OUTSIDE), ('outside', access.DISK_AT_HOME),
                          ('home', access.NOT_HERE)):
        with pytest.raises(Denied) as caught:
            read(origin, {**home.config, 'access': {'disk': 'none'}} if origin == 'home' else home.config)
        assert str(caught.value) == 'ACCESS_DENIED_DISK: ' + words
        # Her character brain reads the sentence as written, with no code.
        assert role_tools.words(caught.value) == words


def test_a_narrowed_table_refuses_a_running_task_what_it_was_given(coordinator, tmp_path):
    store = coordinator.store
    task = running(store, coordinator.delegate(turn(store, LOCAL, OWNER, 'n1'), 'c1', '标题', '交代'))
    assert 'sandbox_run' in task['allowed_capabilities'] and task['network'] == 'any'
    store.config['access'] = {'commands': 'none', 'local_network': 'none', 'internet': 'none'}
    assert refused(broker_for(store, task, tmp_path), 'sandbox_run', {'argv': ['python3', '-V']}) == \
        'ACCESS_DENIED_COMMANDS: ' + access.NOT_HERE
    assert not {'sandbox_run', 'web_fetch', 'web_search'} & set(tasks.granted(store, task))
    assert tasks.refusal(store, task, 'web_fetch') == 'ACCESS_DENIED_INTERNET: ' + access.NOT_HERE


def test_the_dead_guard_row_is_gone():
    assert not hasattr(guard, '_image_path')
    assert 'IMAGE_PATH_HOME_ONLY' not in {rule for rule, _, _ in guard.RULES}
