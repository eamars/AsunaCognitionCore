"""Her plans' time arithmetic (schedule_rules), on the real module: the four timings, time zones, daylight saving.
Dates and DST transitions are real (an example northern-hemisphere zone unrelated to any deployment), never 86400 s
standing in for a day. The service around it runs against Mongo in test_p3_schedule.py.

Standard library only, so it also runs where there is no pytest (her sandbox before a publish):
  PYTHONPATH=src python3 tests/test_schedule_rules.py
"""
from datetime import datetime, timedelta, timezone

from asuna import schedule_rules as rules

ZONE = 'Europe/Berlin'  # personal-scan: ok (unrelated demo DST zone)
OTHER_ZONE = 'Etc/GMT-9'
T0 = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)            # 2026-09-24 07:00 in ZONE (a Thursday)
DST_START = datetime(2027, 3, 28, 1, 0, tzinfo=timezone.utc)     # local 02:00 -> 03:00
SCENE_ID = 'qq:bot:group:9'
SCENE = {'_id': SCENE_ID, 'scene_id': SCENE_ID, 'kind': 'group', 'channel_id': 'napcat'}


def config_with(block=None, top=None):
    route = {'scene_id': SCENE_ID, 'target': {'type': 'group', 'id': '9'}, 'members': {'qq:1': {'person_id': 'qq:1'}}}
    if block is not None:
        route['schedule'] = block
    config = {'channels': {'napcat': {'account_id': 'bot', 'routes': {'g': route}}}}
    config.update(top or {})
    return config


def tz(block=None):
    return rules.scene_timezone(config_with(block), SCENE)['tz']


def refused(code, action):
    """The refusal's words, asserting it carries `code`."""
    try:
        action()
    except ValueError as exc:
        assert code in str(exc), str(exc)
        return str(exc)
    raise AssertionError('not refused: expected ' + code)


def test_after_seconds_is_relative_and_native():
    fire = rules.next_fire(rules.normalize_rule({'intent': 'x', 'after_seconds': 600}), tz({'timezone': ZONE}), T0)
    assert fire == T0 + timedelta(seconds=600)
    assert rules.native_payload({'after_seconds': 600}, fire, T0) == {'after_seconds': 600}


def test_an_interval_below_the_native_minimum_is_refused():
    rules.normalize_rule({'intent': 'x', 'every_seconds': 60})
    refused('INVALID_SCHEDULE_INTERVAL', lambda: rules.normalize_rule({'intent': 'x', 'every_seconds': 59}))


def test_every_uses_the_native_repeat():
    rule = rules.normalize_rule({'intent': 'x', 'every_seconds': 1800})
    fire = rules.next_fire(rule, tz(), T0)
    assert rule == {'every_seconds': 1800} and rules.native_payload(rule, fire, T0) == {'every_seconds': 1800}
    assert rules.rearms_after_fire(rule) is False


def test_a_past_absolute_time_is_refused():
    refused('SCHEDULE_TIME_ALREADY_PAST', lambda: rules.next_fire(
        rules.normalize_rule({'intent': 'x', 'at': '2026-09-23T09:00'}), tz({'timezone': ZONE}), T0))


def test_an_absolute_time_with_an_offset_is_that_instant():
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-25T02:00:00Z'})
    assert rule.get('at_utc') is True
    assert rules.next_fire(rule, tz({'timezone': ZONE}), T0) == datetime(2026, 9, 25, 2, tzinfo=timezone.utc)


def test_a_local_time_that_does_not_exist_is_asked_about_not_guessed():
    rule = rules.normalize_rule({'intent': 'x', 'at': '2027-03-28T02:30'})
    assert '03:00' in refused('SCHEDULE_LOCAL_TIME_MISSING', lambda: rules.next_fire(rule, tz({'timezone': ZONE}), T0))


def test_daily_follows_the_local_clock():
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    first = rules.next_fire(rule, tz({'timezone': ZONE}), T0)
    second = rules.next_fire(rule, tz({'timezone': ZONE}), first + timedelta(seconds=1))
    assert first == datetime.fromisoformat('2026-09-24T07:00:00+00:00')
    assert second == datetime.fromisoformat('2026-09-25T07:00:00+00:00')


def test_daily_across_a_dst_change_stays_at_the_local_hour():
    zone = tz({'timezone': ZONE})
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    for start, hours in ((datetime(2027, 3, 27, 3, tzinfo=timezone.utc), 23),      # clocks go forward
                         (datetime(2026, 10, 24, 3, tzinfo=timezone.utc), 25)):    # and back
        before = rules.next_fire(rule, zone, start)
        after = rules.next_fire(rule, zone, before + timedelta(seconds=1))
        assert after - before == timedelta(hours=hours)
        assert before.astimezone(zone).strftime('%H:%M') == after.astimezone(zone).strftime('%H:%M') == '09:00'


def test_weekly_fires_only_on_the_named_weekdays():
    zone = tz({'timezone': ZONE})
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '21:30', 'weekdays': [0, 2]}})
    local = rules.next_fire(rule, zone, T0).astimezone(zone)
    assert local.weekday() in (0, 2) and local.strftime('%H:%M') == '21:30'


def test_a_clock_on_the_gap_day_moves_to_the_first_valid_moment_and_says_so():
    zone = rules.scene_timezone(config_with({'timezone': ZONE}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '02:30', 'weekdays': [6]}})
    eve = DST_START - timedelta(days=1, hours=13)
    assert rules.next_fire(rule, zone['tz'], eve) == DST_START
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': rule}, zone, eve)
    assert '02:30' in row['dst_note']


def test_an_ambiguous_clock_takes_the_earlier_instant():
    utc, kind = rules.wall_to_utc(datetime(2026, 10, 25, 2, 30), tz({'timezone': ZONE}))
    assert kind == 'ambiguous' and utc == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)


def test_time_zone_precedence_route_scene_config_unset_and_plan():
    scene = dict(SCENE, timezone=OTHER_ZONE)
    route = rules.scene_timezone(config_with({'timezone': ZONE}), scene)
    from_scene = rules.scene_timezone(config_with(None), scene)
    from_config = rules.scene_timezone(config_with(None, {'timezone': OTHER_ZONE}), SCENE)
    unset = rules.scene_timezone(config_with(None), SCENE)
    plan = rules.scene_timezone(config_with({'timezone': ZONE}), scene, {'timezone': OTHER_ZONE})
    assert (route['name'], route['source']) == (ZONE, 'route')
    assert (from_scene['name'], from_scene['source']) == (OTHER_ZONE, 'scene')
    assert from_config['source'] == 'config'
    assert (unset['name'], unset['source']) == ('UTC', 'unset')            # the core carries nobody's default zone
    assert plan['name'] == OTHER_ZONE


def test_a_zone_missing_from_the_database_says_so():
    zone = rules.scene_timezone(config_with({'timezone': 'Mars/Olympus', 'utc_offset_minutes': 720}), SCENE)
    plain = rules.scene_timezone(config_with({'timezone': 'Mars/Olympus'}), SCENE)
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': {'clock': {'time': '09:00'}}}, zone, T0)
    assert zone['source'] == 'fixed_offset' and zone['zone_unavailable'] == 'Mars/Olympus'
    assert plain['source'] == 'host_local' and 'timezone_note' in row


if __name__ == '__main__':
    tests = [(name, test) for name, test in sorted(globals().items()) if name.startswith('test_') and callable(test)]
    failed = []
    for name, test in tests:
        try:
            test()
            print('PASS', name)
        except Exception as exc:                 # the next one still runs
            failed.append(name)
            print('FAIL', name, '->', type(exc).__name__, exc)
    print('schedule_rules: %d/%d passed' % (len(tests) - len(failed), len(tests)))
    raise SystemExit(1 if failed else 0)
