"""Her plans' time arithmetic (schedule_rules), on the real module: the four timings, time zones, daylight saving.
Dates and DST transitions are real (an example northern-hemisphere zone unrelated to any deployment), never 86400 s
standing in for a day. The service that applies these decisions (`ScheduleService`) has no test of its own: the
decisions are the functions tested here.

Standard library only, so it also runs where there is no pytest (her sandbox before a publish):
  PYTHONPATH=src python3 tests/test_schedule_rules.py
"""
from datetime import datetime, timedelta, timezone

from asuna import schedule_rules as rules

ZONE = 'Europe/Berlin'  # personal-scan: ok (unrelated demo DST zone)
OTHER_ZONE = 'Etc/GMT-9'
T0 = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)            # 2026-09-24 07:00 in ZONE (a Thursday)
DST_START = datetime(2027, 3, 28, 1, 0, tzinfo=timezone.utc)     # local 02:00 -> 03:00


def her(name=ZONE):
    return rules.her_zone({'timezone': name})


def tz():
    return her()['tz']


def refused(code, action):
    """The refusal's words, asserting it carries `code`."""
    try:
        action()
    except ValueError as exc:
        assert code in str(exc), str(exc)
        return str(exc)
    raise AssertionError('not refused: expected ' + code)


def test_after_seconds_is_relative_and_native():
    fire = rules.next_fire(rules.normalize_rule({'intent': 'x', 'after_seconds': 600}), tz(), T0)
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
        rules.normalize_rule({'intent': 'x', 'at': '2026-09-23T09:00'}), tz(), T0))


def test_an_absolute_time_with_an_offset_is_that_instant():
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-25T02:00:00Z'})
    assert rule.get('at_utc') is True
    assert rules.next_fire(rule, tz(), T0) == datetime(2026, 9, 25, 2, tzinfo=timezone.utc)


def test_a_local_time_that_does_not_exist_is_asked_about_not_guessed():
    rule = rules.normalize_rule({'intent': 'x', 'at': '2027-03-28T02:30'})
    assert '03:00' in refused('SCHEDULE_LOCAL_TIME_MISSING', lambda: rules.next_fire(rule, tz(), T0))


def test_daily_follows_the_local_clock():
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    first = rules.next_fire(rule, tz(), T0)
    second = rules.next_fire(rule, tz(), first + timedelta(seconds=1))
    assert first == datetime.fromisoformat('2026-09-24T07:00:00+00:00')
    assert second == datetime.fromisoformat('2026-09-25T07:00:00+00:00')


def test_daily_across_a_dst_change_stays_at_the_local_hour():
    zone = tz()
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    for start, hours in ((datetime(2027, 3, 27, 3, tzinfo=timezone.utc), 23),      # clocks go forward
                         (datetime(2026, 10, 24, 3, tzinfo=timezone.utc), 25)):    # and back
        before = rules.next_fire(rule, zone, start)
        after = rules.next_fire(rule, zone, before + timedelta(seconds=1))
        assert after - before == timedelta(hours=hours)
        assert before.astimezone(zone).strftime('%H:%M') == after.astimezone(zone).strftime('%H:%M') == '09:00'


def test_weekly_fires_only_on_the_named_weekdays():
    zone = tz()
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '21:30', 'weekdays': [0, 2]}})
    local = rules.next_fire(rule, zone, T0).astimezone(zone)
    assert local.weekday() in (0, 2) and local.strftime('%H:%M') == '21:30'


def test_a_clock_on_the_gap_day_moves_to_the_first_valid_moment_and_says_so():
    zone = her()
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '02:30', 'weekdays': [6]}})
    eve = DST_START - timedelta(days=1, hours=13)
    assert rules.next_fire(rule, zone['tz'], eve) == DST_START
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': rule}, zone, eve)
    assert '02:30' in row['dst_note']


def test_an_ambiguous_clock_takes_the_earlier_instant():
    utc, kind = rules.wall_to_utc(datetime(2026, 10, 25, 2, 30), tz())
    assert kind == 'ambiguous' and utc == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)


def test_a_wall_time_appointment_is_pinned_to_the_moment_it_names():
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-25T09:00'})
    assert rules.has_wall_zone(rule)
    fire = rules.next_fire(rule, tz(), T0)
    pinned = rules.pin_at(rule, fire)
    assert pinned == {'at': '2026-09-25T07:00+00:00', 'at_utc': True} and not rules.has_wall_zone(pinned)
    other = her(OTHER_ZONE)['tz']
    assert rules.next_fire(pinned, other, T0) == fire, 'a moment does not move when the clock it is read on changes'
    assert rules.pin_at(pinned, fire) == pinned
    for kept in ({'after_seconds': 600}, {'every_seconds': 600}, {'clock': {'time': '09:00'}}):
        assert rules.pin_at(kept, fire) == kept
    assert [rules.has_wall_zone(r) for r in ({'after_seconds': 600}, {'every_seconds': 600}, {'clock': {'time': '09:00'}},
                                              {'at': '2026-09-25T09:00'}, {'at': '2026-09-25T07:00+00:00', 'at_utc': True})
            ] == [False, False, True, True, False]


def test_a_plan_reads_on_the_clock_it_was_written_on_only_when_its_rule_has_one():
    mine = her()
    clock = {'_id': 'p', 'rule': {'clock': {'time': '09:00'}}, 'timezone': OTHER_ZONE}
    assert rules.plan_zone(clock, mine)['name'] == OTHER_ZONE
    assert rules.plan_zone({**clock, 'timezone': ZONE}, mine)['name'] == ZONE
    assert rules.plan_zone({**clock, 'timezone': None}, mine)['name'] == ZONE, 'a plan with no zone of its own is on hers'
    for moment_rule in ({'after_seconds': 600}, {'every_seconds': 600}, {'at': '2026-09-25T07:00+00:00', 'at_utc': True}):
        assert rules.plan_zone({'_id': 'p', 'rule': moment_rule, 'timezone': OTHER_ZONE}, mine)['name'] == ZONE, \
            'an old row that stored a zone for a rule with no wall zone reads on her clock'
    unreadable = rules.plan_zone({**clock, 'timezone': 'Mars/Olympus'}, mine)
    assert unreadable['name'] == ZONE and unreadable['unreadable'] is True


def test_a_plan_on_another_clock_says_so_and_only_a_rule_with_a_wall_zone_can():
    mine = her()
    plan = {'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': {'clock': {'time': '09:00'}}, 'timezone': OTHER_ZONE}
    row = rules.project(plan, mine, T0)
    assert row['description'].endswith('09:00（本地钟点）') and '比你的钟快 7 小时' in row['clock_note'], row   # +9 vs +2 in September
    assert 'clock_note' not in rules.project({**plan, 'timezone': ZONE}, mine, T0), 'same clock, no note'
    assert 'clock_note' not in rules.project({**plan, 'rule': {'every_seconds': 600}}, mine, T0), \
        'a rule with no wall zone never carries it, whatever zone its row stored'
    behind = rules.project({**plan, 'timezone': 'Etc/GMT+5'}, mine, T0)['clock_note']
    assert '慢 7 小时' in behind, behind
    assert rules.plan_brief(plan, mine, T0).keys() <= set(rules.BRIEF) and 'clock_note' in rules.plan_brief(plan, mine, T0)
    unreadable = rules.project({**plan, 'timezone': 'Mars/Olympus'}, mine, T0)
    assert 'timezone_note' in unreadable and 'Mars' not in str(unreadable), 'the note never names the zone'


def test_a_moment_and_its_next_fire_read_on_one_face():
    mine = her()
    moment = rules.normalize_rule({'intent': 'x', 'at': '2026-09-25T09:00+09:00'})      # 00:00 UTC, 02:00 in ZONE
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': moment,
                         'next_fire_at': '2026-09-25T00:00:00+00:00'}, mine, T0)
    assert row['description'] == '一次性：9/25 02:00', row['description']          # not the UTC face, 9/25 00:00
    assert rules.local_clock(mine, T0) == {'now_local': '2026/9/24 07:00', 'weekday': '周四'}, 'no zone name'


def test_a_timing_moves_a_plan_off_another_clock_and_new_wording_does_not():
    mine = her()
    clock = {'_id': 'p', 'rule': {'clock': {'time': '09:00'}}, 'timezone': OTHER_ZONE}
    assert rules.moved_from(clock, mine, True) == OTHER_ZONE
    assert rules.moved_from(clock, mine, False) is None, 'new wording keeps the plan as it is'
    assert rules.moved_from({**clock, 'timezone': ZONE}, mine, True) is None
    assert rules.moved_from({'_id': 'p', 'rule': {'at': '2026-09-25T09:00'}, 'timezone': OTHER_ZONE}, mine, True) == OTHER_ZONE, \
        'an old wall-time appointment is pinned and moved by a restated time'
    assert rules.moved_from({'_id': 'p', 'rule': {'every_seconds': 600}, 'timezone': OTHER_ZONE}, mine, True) is None
    note = rules.moved_note({'last_update': {'from_timezone': OTHER_ZONE}, 'next_fire_at': '2026-09-24T07:00:00+00:00'}, mine)
    assert '比你的钟快 7 小时' in note and rules.moved_note({'last_update': {}}, mine) is None


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


def test_at_takes_the_clock_face_she_reads():
    """What she reads she may write back: 10/19 21:05 and 2026/10/19 21:05 are local wall times like the ISO form."""
    from datetime import datetime, timezone
    from asuna.schedule_rules import _wall_shape
    year = datetime.now(timezone.utc).year
    assert _wall_shape('2026/10/19 21:05') == {'at': '2026-10-19T21:05'}
    assert _wall_shape('2026-10-19 21:05') == _wall_shape('2026-10-19T21:05') == {'at': '2026-10-19T21:05'}
    shown = _wall_shape('12/31 23:59')['at']
    assert shown in ('%d-12-31T23:59' % year, '%d-12-31T23:59' % (year + 1)), 'without a year: the next such date'
    try:
        _wall_shape('13/40 09:00')
    except ValueError as exc:
        assert 'SCHEDULE_AT_INVALID' in str(exc)
    else:
        raise AssertionError('an impossible date is refused')
