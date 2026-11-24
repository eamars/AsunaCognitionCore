"""ADR-135 R1-R3, run at every landing: what the owner's own conversations and home keep. Commands run only in a task
the owner gives in his own conversation; in an outside group his task has that place's grant; a home turn's note to a
group is delivered as trusted. On the fixture world in memory (test_whose's home and coordinator, test_adr087_step4's
note turns)."""
from asuna import notes, places
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from test_adr087_step4 import call, her, turn as note_turn  # noqa: F401  (her: a fixture)
from test_whose import OWNER, coordinator, home, turn  # noqa: F401  (home, coordinator: fixtures)


def granted(coordinator, scene_id, key):
    task = coordinator.delegate(turn(coordinator.store, scene_id, OWNER, key), 'c-' + key, '跑个命令', '在任务目录里跑 python3 -V')
    return task_records.get(coordinator.store, task['_id'])


def test_R1_the_owner_s_task_in_his_own_chat_runs_commands(coordinator):
    task = granted(coordinator, 'dm-owner', 'r1')
    assert 'sandbox_run' in task['allowed_capabilities'] and task['network'] == 'any'


def test_R2_the_owner_s_task_in_an_outside_group_has_that_place_s_grant(coordinator):
    route = coordinator.store.config['channels']['fixture']['routes']['g1']
    route['members']['O'] = {**route['members']['A'], 'person_id': OWNER, 'workspace': route['members']['A']['workspace'] + '-o'}
    scene = scene_records.get(coordinator.store, 'g1')
    scene_records.save(coordinator.store, {**scene, 'members': [*scene['members'], OWNER]}, expected=scene['revision'])
    task = granted(coordinator, 'g1', 'r2')
    assert 'sandbox_run' not in task['allowed_capabilities'] and task['network'] == 'public'


def test_R3_a_home_turn_s_note_to_a_group_is_delivered_as_trusted(her):
    sent = call(her, note_turn(her, ['note']), 'note', {'to': places.place_id('g1'), 'text': '周末大家想去哪儿玩？'})
    row = notes.get(her.store, sent['note'])
    assert (row['to_scene'], row['trust']) == ('g1', notes.TRUSTED) and row['mode'] in (notes.WAKE, notes.NEXT_TIME)
