"""A Host taken away from outside (her ask, 2026-10-08): the next start finds the lease the old one left behind, and
her home turns for a day say so in words, with about when it was last alive and when it came back."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from asuna import host_stops
from asuna.host_lease import LEASE_SECONDS
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
        assert next_start.left_behind == held - timedelta(seconds=LEASE_SECONDS)


def test_her_home_turns_say_it_for_a_day_in_words(store):
    moment = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    assert host_stops.block(store, ZONE, moment) is None
    host_stops.record(store, datetime(2026, 10, 8, 9, 7), back_at='2026-10-08T11:15:00+00:00')
    said = host_stops.block(store, ZONE, moment)
    assert said['what'] == '宿主上次是被外部终止的（不是正常停下）'
    assert said['when'] == '最后确认还在运行约是 10/8 09:07，重新起来是 10/8 11:15，中间约 2 小时 8 分钟宿主没有运行'
    assert host_stops.block(store, ZONE, moment + timedelta(hours=24)) is None


def test_a_home_turn_carries_it(store, tmp_path):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_local_images import world
    world(store, tmp_path)
    host_stops.record(store, datetime.now(timezone.utc) - timedelta(hours=1))
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '嗯。'})], '在。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'm1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    assert ep['context']['host_from_program']['what'].startswith('宿主上次是被外部终止的')
