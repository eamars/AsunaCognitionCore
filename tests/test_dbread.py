"""asuna.dbread: her task scripts read the database without guessing (owner 2026-10-13, her four asks): every answer
says what it asked and how many rows it found, an empty answer says 零行, her local times become UTC bounds, a wrong
collection or field name is answered with the real ones, and nothing writes."""
import pytest

from asuna import dbread


def reader(store):
    return dbread.Reader(store.db, store.db.name)


def line(store, seq, at, scene='local-dm', text='你好'):
    store.db.messages.insert_one({'_id': 'm%d' % seq, 'schema_version': 1, 'scene_id': scene, 'scene_seq': seq,
                                  'direction': 'inbound', 'author': 'A', 'text': text, 'received_at': at})


def test_her_local_hour_becomes_utc_bounds_that_match_both_stored_forms():
    window = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00', 'Pacific/Auckland')
    assert window == {'$gte': '2026-10-12T08:00:00', '$lt': '2026-10-12T09:00:00'}
    assert window.asked['zone'] == 'Pacific/Auckland' and window.asked['utc'] == ['2026-10-12T08:00:00', '2026-10-12T09:00:00']
    assert '2026-10-12T08:30:00Z' >= window['$gte'] and '2026-10-12T08:59:59.9+00:00' < window['$lt']
    day = dbread.local_window('2026-10-12', zone='Pacific/Auckland')
    assert day == {'$gte': '2026-10-11T11:00:00', '$lt': '2026-10-12T11:00:00'}
    with pytest.raises(ValueError, match='不是本地钟点'):
        dbread.local_window('今晚九点')


def test_every_answer_says_what_it_asked_and_an_empty_one_says_zero_rows(store):
    line(store, 1, '2026-10-12T08:30:00+00:00')
    line(store, 2, '2026-10-12T10:30:00+00:00')
    db = reader(store)
    when = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00', 'Pacific/Auckland')
    found = db.find('messages', {'scene_id': 'local-dm', 'received_at': when}, fields=['text'])
    assert found['collection'] == 'messages' and found['database'] == store.db.name and found['found'] == 1
    assert found['local_window'][0]['utc'] == ['2026-10-12T08:00:00', '2026-10-12T09:00:00']
    assert found['filter']['received_at'] == {'$gte': '2026-10-12T08:00:00', '$lt': '2026-10-12T09:00:00'}
    empty = db.find('messages', {'scene_id': 'nowhere'})
    assert empty['found'] == 0 and empty['said'].startswith('零行') and empty['rows'] == []
    assert db.count('messages', {'scene_id': 'local-dm'})['found'] == 2


def test_wrong_names_are_answered_with_the_real_ones_and_nothing_writes(store):
    line(store, 1, '2026-10-12T08:30:00+00:00')
    db = reader(store)
    with pytest.raises(ValueError, match='state_heads.*有的集合：.*messages'):
        db.find('documents')
    asked = db.find('messages', {'created_at': {'$gte': 'x'}})
    assert 'created_at' in asked['unseen_fields']
    with pytest.raises(ValueError, match='只读'):
        db.aggregate('messages', [{'$match': {}}, {'$out': 'copy'}])
    assert not [name for name in dir(dbread.Reader) if name.startswith(('insert', 'update', 'delete', 'replace'))]


def test_a_groups_history_comes_with_its_archive(store):
    line(store, 1, '2026-10-12T08:30:00+00:00', scene='g-a')
    store.db.messages.insert_one({'_id': 'old', 'schema_version': 1, 'scene_id': 'archive:g-a', 'scene_seq': 1,
                                  'direction': 'archived', 'author': 'B', 'text': '旧的', 'occurred_at': '2026-01-01T00:00:00Z'})
    both = reader(store).history('g-a', fields=['text'])
    assert both['live']['found'] == 1 and both['archive']['found'] == 1


def test_a_home_task_command_is_told_the_database_and_her_zone():
    env = dbread.environment({'mongo_uri': 'mongodb://example.invalid', 'database': 'd'}, 'Pacific/Auckland')
    assert env == {'ASUNA_MONGO_URI': 'mongodb://example.invalid', 'ASUNA_DATABASE': 'd', 'ASUNA_TIMEZONE': 'Pacific/Auckland'}
    assert dbread.environment({}, 'UTC') == {}
