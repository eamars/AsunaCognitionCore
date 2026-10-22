"""A Host taken away from outside (her ask, 2026-10-08): the next start finds the lease the old one left behind, and
her home turns for a day say so in words, with about when it was last alive and when it came back."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from asuna import host_stops
from asuna.host_lease import LEASE_SECONDS, mark_planned
from test_host_lease import lease

ZONE = {'tz': ZoneInfo('UTC'), 'name': 'UTC', 'source': 'config'}


def test_a_lease_left_behind_is_found_and_a_clean_stop_leaves_none(store, tmp_path):
    with lease(store, tmp_path / 'h') as clean:
        assert clean.left_behind is None
    with lease(store, tmp_path / 'h') as again:
        assert again.left_behind is None, 'a clean stop deleted the lease'
    killed = lease(store, tmp_path / 'h').acquire()                 # dies without releasing
    killed.client.close()
    held = store.db.host_leases.find_one({'_id': 'host'})['expires_at']
    with lease(store, tmp_path / 'h') as next_start:
        assert next_start.left_behind == held - timedelta(seconds=LEASE_SECONDS) and not next_start.planned
    killed = lease(store, tmp_path / 'h').acquire()
    killed.client.close()
    assert mark_planned({'mongo_uri': store.config['mongo_uri'], 'database': store.name}, 'developer')
    with lease(store, tmp_path / 'h') as after_deploy:
        assert after_deploy.planned, 'a deploy marked its restart before killing the Host'
        assert 'planned_stop' not in store.db.host_leases.find_one({'_id': 'host'}), 'the new Host starts unmarked'


def test_a_planned_restart_is_recorded_and_not_shown(store):
    host_stops.record(store, datetime.now(timezone.utc) - timedelta(minutes=2), planned=True)
    assert store.db.host_stops.find_one()['how'] == 'planned'
    assert host_stops.block(store, ZONE) is None


def test_her_home_turns_say_it_for_a_day_in_words(store):
    moment = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    assert host_stops.block(store, ZONE, moment) is None
    host_stops.record(store, datetime(2026, 10, 8, 9, 7), back_at='2026-10-08T11:15:00+00:00')
    said = host_stops.block(store, ZONE, moment)
    assert said['what'] == '宿主上次是被外部终止的（不是正常停下）'
    assert said['when'] == '最后确认还在运行约是 10/8 09:07，重新起来是 10/8 11:15，中间约 2 小时 8 分钟宿主没有运行'
    assert host_stops.block(store, ZONE, moment + timedelta(hours=24)) is None


def test_a_host_that_exited_on_its_own_is_recorded_as_a_crash_with_its_code(store, tmp_path):
    """Her finding (2026-10-22): a crash was recorded and shown as an outside kill. The supervisor's record of the
    start under way says the Host exited on its own, with its code; the next start reads it."""
    import json
    alive = datetime(2026, 10, 22, 9, 3, 20, tzinfo=timezone.utc)
    folder = tmp_path / 'restart'
    folder.mkdir()
    def supervisor(**record):
        (folder / 'last.json').write_text(json.dumps({'asked': 'nobody', 'down_at': '2026-10-22T09:03:52.165Z',
                                                      'exit_code': 3221225477, 'result': 'not_back', **record}))
    supervisor()
    assert host_stops.crash_code(alive, tmp_path) == 3221225477
    for other in ({'back_at': '2026-10-22T09:04:16Z'},              # an earlier restart already back: not this one
                  {'asked': 'home'}, {'exit_code': None},
                  {'down_at': '2026-10-22T10:30:00Z'}):              # far from the lease's last renewal
        supervisor(**other)
        assert host_stops.crash_code(alive, tmp_path) is None, other
    (folder / 'last.json').unlink()
    assert host_stops.crash_code(alive, tmp_path) is None
    host_stops.record(store, alive, back_at='2026-10-22T09:04:16+00:00', exit_code=3221225477)
    row = store.db.host_stops.find_one()
    assert (row['how'], row['exit_code']) == ('crashed', 3221225477)
    said = host_stops.block(store, ZONE, datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc))
    assert said['what'] == '宿主上次是自己崩掉退出的（不是被谁停的，也不是正常停下）'
    assert said['when'].startswith('最后确认还在运行约是 10/22 09:03，重新起来是 10/22 09:04')


def test_failed_gate_looks_are_counted_for_a_day_and_kept_a_week(store):
    moment = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    store.db.missed_looks.insert_many([{'_id': 'ep-a', 'scene_id': 'g1', 'at': '2026-10-14T09:00:00+00:00', 'cause': 'clash'},
                                       {'_id': 'ep-b', 'scene_id': 'g1', 'at': '2026-10-14T10:00:00+00:00'},
                                       {'_id': 'ep-c', 'scene_id': 'g1', 'at': '2026-10-12T10:00:00+00:00'},
                                       {'_id': 'ep-d', 'scene_id': 'g1', 'at': '2026-10-01T10:00:00+00:00'}])
    said = host_stops.block(store, ZONE, moment)
    # Each with its cause in words; one recorded before causes were kept reads as an error.
    assert list(said) == ['missed_looks'] and said['missed_looks'].endswith(
        ' 2 次（%s 1，%s 1）' % (host_stops.MISSED_CAUSES['clash'], host_stops.MISSED_CAUSES['error']))
    assert host_stops.missed_cause(error=RuntimeError('session "x" is already owned by an active write handle')) == 'clash'
    assert host_stops.missed_cause(error=TimeoutError('NATIVE_STAGE_TIMEOUT')) == 'timeout'
    assert host_stops.missed_cause(finish_reason='length') == 'cut'
    assert store.db.missed_looks.count_documents({}) == 3, 'older than a week is gone'


def test_a_home_turn_carries_it(store, tmp_path):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_local_images import world
    world(store, tmp_path)
    host_stops.record(store, datetime.now(timezone.utc) - timedelta(hours=1))
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '嗯。'})], '在。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'm1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    assert ep['context']['host_from_program']['what'].startswith('宿主上次是被外部终止的')
