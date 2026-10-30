"""asuna.dbread: her task scripts read the database without guessing (owner 2026-10-13, her four asks): every answer
says what it asked and how many rows it found, an empty answer says 零行, her local times become UTC bounds, a wrong
collection or field name is answered with the real ones, and nothing writes."""
import pytest

from asuna import dbread


def test_her_local_hour_becomes_utc_bounds_that_match_both_stored_forms():
    window = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00', 'Etc/GMT-12')
    assert window == {'$gte': '2026-10-12T09:00:00', '$lt': '2026-10-12T10:00:00'}
    assert window.asked['utc'] == ['2026-10-12T09:00:00', '2026-10-12T10:00:00']
    assert set(window.asked) == {'local', 'utc'}, 'a receipt carries her face and the bounds, never a zone name (ADR-106)'
    assert '2026-10-12T09:30:00Z' >= window['$gte'] and '2026-10-12T09:59:59.9+00:00' < window['$lt']
    day = dbread.local_window('2026-10-12', zone='Etc/GMT-12')
    assert day == {'$gte': '2026-10-11T12:00:00', '$lt': '2026-10-12T12:00:00'}
    with pytest.raises(ValueError, match='不是本地钟点'):
        dbread.local_window('今晚九点')


def test_a_home_task_command_is_told_the_database_and_her_zone():
    env = dbread.environment({'mongo_uri': 'mongodb://example.invalid', 'database': 'd'}, 'Etc/GMT-12')
    assert env == {'ASUNA_MONGO_URI': 'mongodb://example.invalid', 'ASUNA_DATABASE': 'd', 'ASUNA_TIMEZONE': 'Etc/GMT-12'}
    assert dbread.environment({}, 'UTC') == {}


def test_a_command_given_no_zone_reads_the_machines_own_clock_not_utc(monkeypatch):
    monkeypatch.delenv('ASUNA_TIMEZONE', raising=False)
    from datetime import datetime
    before = datetime.now().strftime('%Y-%m-%d %H:%M')
    read = dbread.now()
    assert read in {before, datetime.now().strftime('%Y-%m-%d %H:%M')}       # a minute may turn in between
    from datetime import timezone
    machine = datetime(2026, 10, 18, 8, 0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')   # naive = the machine's clock
    assert dbread.local_window('2026-10-18 08:00').asked['utc'][0] == machine
