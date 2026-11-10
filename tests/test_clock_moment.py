"""One reading of a stored instant (clock.moment), and one wording where she reads a time that cannot be read."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import clock, local_time, schedule_rules

UTC = timezone.utc
ZONE = {'tz': UTC, 'name': 'UTC'}
AT = datetime(2026, 11, 10, 1, 2, 3, 456789, tzinfo=UTC)


@pytest.mark.parametrize('value', ['2026-11-10T01:02:03.456789Z', '2026-11-10T01:02:03.456789+00:00',
                                   '2026-11-10T14:02:03.456789+13:00', '2026-11-10T01:02:03.456789',
                                   ' 2026-11-10T01:02:03.456789Z ', datetime(2026, 11, 10, 1, 2, 3, 456789),
                                   datetime(2026, 11, 10, 14, 2, 3, 456789, tzinfo=timezone(timedelta(hours=13)))])
def test_every_form_of_an_instant_reads_as_one_aware_utc_moment(value):
    moment = clock.moment(value)
    assert moment == AT and moment.utcoffset() == timedelta(0)


@pytest.mark.parametrize('value', ['not a time', '2026-13-40T00:00:00Z', '', '   ', None, 0, 1731200000.0, []])
def test_anything_else_raises_bad_time(value):
    with pytest.raises(clock.BadTime):
        clock.moment(value)
    assert issubclass(clock.BadTime, ValueError)


@pytest.mark.parametrize('value', ['2026-13-40T00:00:00Z', 'garbage'])
def test_a_time_she_reads_that_cannot_be_read_says_one_thing(value):
    assert local_time.stamp(value, ZONE) == local_time.UNKNOWN == '时间不详'
    assert schedule_rules.line_stamp(ZONE, value) == local_time.UNKNOWN


@pytest.mark.parametrize('value', ['', '  ', None])
def test_a_time_there_is_none_of_shows_nothing_not_unknown(value):
    assert local_time.stamp(value, ZONE) == '' and schedule_rules.line_stamp(ZONE, value) == ''


def test_a_time_field_that_cannot_be_read_says_one_thing_and_a_good_one_its_face():
    shown = local_time.for_model({'at': '2026-13-40T00:00:00Z', 'until': '2026-11-10T01:02:03Z'}, ZONE, now=AT)
    assert shown == {'at': local_time.UNKNOWN, 'until': '11/10 01:02'}


def test_a_time_shown_without_a_zone_names_its_offset():
    assert local_time.utc_face('2026-11-10T01:02:03.4+00:00') == '2026-11-10 01:02（UTC）'
    assert local_time.utc_face('2026-11-10T14:02:03+13:00') == '2026-11-10 01:02（UTC）'
    assert local_time.utc_face('garbage') == local_time.UNKNOWN and local_time.utc_face(None) == ''
