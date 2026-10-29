"""asuna.dbread: her task scripts read the database without guessing (owner 2026-10-13, her four asks): every answer
says what it asked and how many rows it found, an empty answer says 零行, her local times become UTC bounds, a wrong
collection or field name is answered with the real ones, and nothing writes."""
import pytest

from asuna import dbread


def test_her_local_hour_becomes_utc_bounds_that_match_both_stored_forms():
    window = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00', 'Pacific/Auckland')
    assert window == {'$gte': '2026-10-12T08:00:00', '$lt': '2026-10-12T09:00:00'}
    assert window.asked['zone'] == 'Pacific/Auckland' and window.asked['utc'] == ['2026-10-12T08:00:00', '2026-10-12T09:00:00']
    assert '2026-10-12T08:30:00Z' >= window['$gte'] and '2026-10-12T08:59:59.9+00:00' < window['$lt']
    day = dbread.local_window('2026-10-12', zone='Pacific/Auckland')
    assert day == {'$gte': '2026-10-11T11:00:00', '$lt': '2026-10-12T11:00:00'}
    with pytest.raises(ValueError, match='不是本地钟点'):
        dbread.local_window('今晚九点')


def test_a_home_task_command_is_told_the_database_and_her_zone():
    env = dbread.environment({'mongo_uri': 'mongodb://example.invalid', 'database': 'd'}, 'Pacific/Auckland')
    assert env == {'ASUNA_MONGO_URI': 'mongodb://example.invalid', 'ASUNA_DATABASE': 'd', 'ASUNA_TIMEZONE': 'Pacific/Auckland'}
    assert dbread.environment({}, 'UTC') == {}


def test_a_command_given_no_zone_reads_the_machines_own_clock_not_utc(monkeypatch):
    monkeypatch.delenv('ASUNA_TIMEZONE', raising=False)
    from datetime import datetime
    before = datetime.now().strftime('%Y-%m-%d %H:%M')
    read = dbread.now()
    assert read in {before, datetime.now().strftime('%Y-%m-%d %H:%M')}       # a minute may turn in between
    assert dbread.local_window('2026-10-18 08:00').asked['zone'] == datetime.now().astimezone().tzname()
