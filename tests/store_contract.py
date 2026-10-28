"""The store's contract: every adapter answers the words the way the meaning table says, through the shared layer.

Classes of cases, one letter each (W words, O order, G group, C changes, X writes, T time, V validation, N nearest,
B blobs, S schema), on a `store` fixture: `Checked` over the adapter under test with this file's synthetic catalog,
on a throwaway database. The module that runs them provides `open_store`, a session fixture returning a context
manager that yields such a store and drops its database on exit, failures included. Case ids are in the test names.
"""
import hashlib
import io
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from asuna.store import Checked, adapters
from asuna.store.adapters import Ensured, Updated
from asuna.store.catalog import Catalog, Collection, Field, Index, Space
from asuna.store.errors import (AdapterNotInstalled, BlobMissing, DuplicateKey, NotSupported, QueryInvalid,
                                RecordInvalid, RecordTooLarge, SchemaConflict)
from asuna.store.words import (AddToSet, And, AnyOf, Contains, Each, Exists, Holds, HoldsAny, Increase, IsNull,
                               Larger, Max, NonEmpty, NoneOf, Not, Now, OnCreate, Or, Push, Range, Set, Smaller,
                               StartsWith, Unset)

__all__ = ['CATALOG', 'store', 'vectors', 'TestW', 'TestO', 'TestG', 'TestC', 'TestX', 'TestT', 'TestV', 'TestN',
           'TestB', 'TestS']

DIM = 16
THINGS = Collection('things', owner='tests', fields=(
    Field('name', 'text'), Field('n', 'number', nullable=True), Field('flag', 'bool'), Field('at', 'time'),
    Field('note', 'text', nullable=True), Field('rank', 'number'), Field('tags', 'list', of='text'),
    Field('sources', 'list', of='object'), Field('sources.scene_id', 'text'), Field('sources.seq', 'number'),
    Field('meta', 'object'), Field('meta.kind', 'text', nullable=True), Field('meta.size', 'number')),
    indexes=(Index('rank_1', (('rank', 1),)),))
KEYED = Collection('keyed', owner='tests', fields=(
    Field('platform', 'text', required=True), Field('account', 'text', required=True), Field('event', 'text'),
    Field('revision', 'number'), Field('sequence', 'number'), Field('state', 'text'), Field('order', 'number')),
    indexes=(Index('platform_1_account_1', (('platform', 1), ('account', 1)), unique=True),
             Index('event_1', (('event', 1),), unique=True, only_where_present=('event',))))
LEASES = Collection('leases', owner='tests', fields=(
    Field('instance', 'text'), Field('since', 'time'), Field('expires_at', 'time'), Field('planned_stop', 'object'),
    Field('planned_stop.at', 'time')))
UNITS = Collection('units', owner='tests', fields=(
    Field('embedding', 'vector', dimensions=DIM), Field('scope_key', 'text'), Field('policy_epoch', 'number'),
    Field('status', 'text'), Field('kind', 'text'), Field('body', 'text')))
SPACE = Space('contract_vectors', 'units', 'embedding', DIM, ('scope_key', 'policy_epoch', 'status', 'kind'))
CATALOG = Catalog([THINGS, KEYED, LEASES, UNITS], [SPACE])

T0 = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)
ROWS = [
    {'_id': 'a', 'name': 'Alpha', 'n': 1, 'flag': True, 'at': T0, 'note': None, 'rank': 3, 'tags': ['x', 'y'],
     'meta': {'kind': 'k1', 'size': 3}, 'sources': [{'scene_id': 's1', 'seq': 1}, {'scene_id': 's2', 'seq': 2}]},
    {'_id': 'b', 'name': 'alpha', 'n': 1.0, 'flag': False, 'rank': 1, 'tags': [], 'meta': {'kind': None}},
    {'_id': 'c', 'name': 'Beta', 'n': 2, 'note': 'x', 'rank': 2, 'tags': ['y'], 'at': T0 + timedelta(hours=1)},
    {'_id': 'd', 'rank': 4},
    {'_id': 'e', 'name': 'a.c', 'n': None, 'rank': 5},
]


@pytest.fixture
def store(open_store):
    with open_store() as opened:
        opened.ensure()
        yield opened


def things(store, rows=ROWS):
    store.collection('things').insert([dict(row) for row in rows])
    return store.collection('things')


def ids(rows):
    return [row['_id'] for row in rows]


def found(handle, where, **kw):
    return sorted(ids(handle.find(where, **kw)))


def refused(error, call, code=None):
    with pytest.raises(error) as caught:
        call()
    if code:
        assert caught.value.code == code, str(caught.value)
    return caught.value


class TestW:
    """3.2: each condition word, with records missing the field, holding null, an empty list, a list."""

    def test_W01_equality_is_text_exactly(self, store):
        t = things(store)
        assert found(t, {'name': 'Alpha'}) == ['a']
        t.insert([{'_id': 'composed', 'name': 'é'}, {'_id': 'decomposed', 'name': 'é'}])
        assert found(t, {'name': 'é'}) == ['composed']

    def test_W02_numbers_by_value_and_a_bool_is_not_a_number(self, store):
        t = things(store)
        assert found(t, {'n': 1}) == ['a', 'b'] and found(t, {'n': 1.0}) == ['a', 'b']
        assert found(t, {'flag': True}) == ['a']
        refused(QueryInvalid, lambda: t.find({'flag': 1}), 'QUERY_KIND_MISMATCH')
        refused(QueryInvalid, lambda: t.find({'n': True}), 'QUERY_KIND_MISMATCH')

    def test_W03_time_equality_to_the_millisecond(self, store):
        t = things(store)
        assert found(t, {'at': T0 + timedelta(microseconds=400)}) == ['a']
        assert found(t, {'at': T0.astimezone(timezone(timedelta(hours=13)))}) == ['a']

    def test_W04_none_is_not_a_value(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'note': None}), 'QUERY_NULL_EQUALITY')

    def test_W05_equality_on_a_list_an_object_or_another_kind_is_refused(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'tags': ['x', 'y']}), 'QUERY_EQUALITY_ON_LIST')
        refused(QueryInvalid, lambda: t.find({'meta': {'kind': 'k1', 'size': 3}}), 'QUERY_EQUALITY_ON_OBJECT')
        refused(QueryInvalid, lambda: t.find({'name': 3}), 'QUERY_KIND_MISMATCH')

    def test_W06_any_of(self, store):
        t = things(store)
        assert found(t, {'name': AnyOf(['Alpha', 'Beta', 'nobody'])}) == ['a', 'c']
        assert found(t, {'n': AnyOf([2.0])}) == ['c']

    def test_W07_any_of_nothing_matches_nothing_and_none_is_refused(self, store):
        t = things(store)
        assert found(t, {'name': AnyOf([])}) == []
        refused(QueryInvalid, lambda: t.find({'note': AnyOf(['x', None])}), 'QUERY_NULL_EQUALITY')

    def test_W08_none_of_matches_missing_null_and_unequal(self, store):
        t = things(store)
        assert found(t, {'note': NoneOf(['x'])}) == ['a', 'b', 'd', 'e']
        assert found(t, {'name': NoneOf(['Alpha', 'Beta'])}) == ['b', 'd', 'e']

    def test_W09_none_of_nothing_matches_every_record_and_none_is_refused(self, store):
        t = things(store)
        assert found(t, {'name': NoneOf([])}) == ['a', 'b', 'c', 'd', 'e']
        refused(QueryInvalid, lambda: t.find({'note': NoneOf([None])}), 'QUERY_NULL_EQUALITY')

    def test_W10_not_matches_missing_and_null(self, store):
        t = things(store)
        assert found(t, {'note': Not('x')}) == ['a', 'b', 'd', 'e']
        assert found(t, {'n': Not(1)}) == ['c', 'd', 'e']

    def test_W11_range_within_every_bound(self, store):
        t = things(store)
        assert found(t, {'n': Range(gte=1, lt=2)}) == ['a', 'b']
        assert found(t, {'n': Range(gt=1)}) == ['c']
        assert found(t, {'n': Range(gt=1, lte=1.5)}) == []
        assert found(t, {'at': Range(gt=T0)}) == ['c']

    def test_W12_missing_and_null_never_meet_a_range(self, store):
        t = things(store)
        assert found(t, {'note': Range(gte='')}) == ['c']
        assert found(t, {'n': Range(lt=100)}) == ['a', 'b', 'c']

    def test_W13_text_ranges_go_by_code_point(self, store):
        t = store.collection('things')
        order = ['Z', 'a', 'é', '中', '￿', '\U0001F600']
        t.insert([{'_id': 'p%d' % n, 'name': name} for n, name in enumerate(order)])
        assert [row['name'] for row in t.find({}, sort=[('name', 1)])] == order
        assert found(t, {'name': Range(gt='Z', lt='中')}) == ['p1', 'p2']
        assert found(t, {'name': Range(gt='￿')}) == ['p5']

    def test_W14_a_bound_of_another_kind_is_refused(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'at': Range(gte='2026-01-01')}), 'QUERY_KIND_MISMATCH')
        refused(QueryInvalid, lambda: t.find({'name': Range(gt=1)}), 'QUERY_KIND_MISMATCH')
        refused(QueryInvalid, lambda: t.find({'n': Range(gt=T0)}), 'QUERY_KIND_MISMATCH')

    def test_W15_a_range_needs_a_bound_and_a_value_field(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'n': Range()}), 'QUERY_RANGE_EMPTY')
        refused(QueryInvalid, lambda: t.find({'tags': Range(gt='a')}), 'QUERY_WORD_KIND')
        refused(QueryInvalid, lambda: t.find({'meta': Range(gt='a')}), 'QUERY_WORD_KIND')

    def test_W16_exists_includes_null(self, store):
        t = things(store)
        assert found(t, {'note': Exists(True)}) == ['a', 'c']
        assert found(t, {'n': Exists()}) == ['a', 'b', 'c', 'e']

    def test_W17_exists_false_is_absent(self, store):
        t = things(store)
        assert found(t, {'note': Exists(False)}) == ['b', 'd', 'e']
        assert found(t, {'meta.kind': Exists(False)}) == ['c', 'd', 'e']

    def test_W18_is_null_is_present_and_null(self, store):
        t = things(store)
        assert found(t, {'note': IsNull()}) == ['a']
        assert found(t, {'meta.kind': IsNull()}) == ['b']
        refused(QueryInvalid, lambda: t.find({'name': IsNull()}), 'QUERY_NOT_NULLABLE')

    def test_W19_starts_with_is_literal_and_keeps_case(self, store):
        t = things(store)
        t.insert({'_id': 'abc', 'name': 'abc'})
        assert found(t, {'name': StartsWith('Al')}) == ['a']
        assert found(t, {'name': StartsWith('Al', 'Be')}) == ['a', 'c']
        assert found(t, {'name': StartsWith('a.')}) == ['e']
        assert found(t, {'name': StartsWith('.*')}) == []

    def test_W20_starts_with_needs_a_prefix_on_text(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'name': StartsWith()}), 'QUERY_EMPTY_TEXT')
        refused(QueryInvalid, lambda: t.find({'name': StartsWith('a', '')}), 'QUERY_EMPTY_TEXT')
        refused(QueryInvalid, lambda: t.find({'n': StartsWith('1')}), 'QUERY_WORD_KIND')

    def test_W21_contains_is_literal(self, store):
        t = things(store)
        assert found(t, {'name': Contains('lph')}) == ['a', 'b']
        assert found(t, {'name': Contains('.')}) == ['e']
        assert found(t, {'name': Contains('A.*')}) == []
        refused(QueryInvalid, lambda: t.find({'name': Contains('')}), 'QUERY_EMPTY_TEXT')

    def test_W22_case_blind_folds_ascii_latin_greek_cyrillic(self, store):
        t = store.collection('things')
        t.insert([{'_id': 'ascii', 'name': 'Hello World'}, {'_id': 'latin', 'name': 'CafÉ crÈme'},
                  {'_id': 'greek', 'name': 'ΑΘΗΝΑ'},
                  {'_id': 'cyrillic', 'name': 'МОСКВА'}])
        assert found(t, {'name': Contains('WORLD', case=False)}) == ['ascii']
        assert found(t, {'name': Contains('café crème', case=False)}) == ['latin']
        assert found(t, {'name': Contains('αθηνα', case=False)}) == ['greek']
        assert found(t, {'name': Contains('москва', case=False)}) == ['cyrillic']
        assert found(t, {'name': Contains('WORLD')}) == []

    def test_W23_sharp_s_and_dotted_capital_i_are_not_folded(self, store):
        t = store.collection('things')
        t.insert([{'_id': 'strasse', 'name': 'straße'}, {'_id': 'istanbul', 'name': 'İSTANBUL'}])
        assert found(t, {'name': Contains('STRASSE', case=False)}) == []
        assert found(t, {'name': Contains('istanbul', case=False)}) == []
        assert found(t, {'name': Contains('STRAßE', case=False)}) == ['strasse']

    def test_W24_greek_final_sigma_under_case_blind_matching(self, store):
        t = store.collection('things')
        t.insert({'_id': 'logos', 'name': 'ΛΟΓΟΣ'})
        assert found(t, {'name': Contains('λογοσ', case=False)}) == ['logos']
        assert found(t, {'name': Contains('λογος', case=False)}) == ['logos']

    def test_W25_holds_an_element(self, store):
        t = things(store)
        assert found(t, {'tags': Holds('x')}) == ['a']
        refused(QueryInvalid, lambda: t.find({'name': Holds('x')}), 'QUERY_WORD_KIND')
        refused(QueryInvalid, lambda: t.find({'sources': Holds({'scene_id': 's1'})}), 'QUERY_EQUALITY_ON_OBJECT')

    def test_W26_holds_any(self, store):
        t = things(store)
        assert found(t, {'tags': HoldsAny(['x', 'zz'])}) == ['a']
        assert found(t, {'tags': HoldsAny(['y'])}) == ['a', 'c']
        assert found(t, {'tags': HoldsAny([])}) == []

    def test_W27_non_empty(self, store):
        t = things(store)
        assert found(t, {'tags': NonEmpty()}) == ['a', 'c']
        refused(QueryInvalid, lambda: t.find({'name': NonEmpty()}), 'QUERY_WORD_KIND')

    def test_W28_each_needs_one_element_meeting_every_entry(self, store):
        t = things(store)
        assert found(t, {'sources': Each({'scene_id': 's1', 'seq': 1})}) == ['a']
        assert found(t, {'sources': Each({'seq': Range(gte=2)})}) == ['a']

    def test_W29_two_elements_each_meeting_one_entry_do_not_match(self, store):
        t = things(store)
        assert found(t, {'sources': Each({'scene_id': 's1', 'seq': 2})}) == []
        refused(QueryInvalid, lambda: t.find({'sources.scene_id': 's1'}), 'QUERY_PATH_THROUGH_LIST')
        refused(QueryInvalid, lambda: t.find({'tags': Each({'x': 1})}), 'QUERY_WORD_KIND')

    def test_W30_and_or(self, store):
        t = things(store)
        assert found(t, Or({'name': 'Alpha'}, {'note': 'x'})) == ['a', 'c']
        assert found(t, And({'n': 1}, Or({'flag': True}, {'name': 'Beta'}))) == ['a']
        assert found(t, And()) == ['a', 'b', 'c', 'd', 'e']
        assert found(t, {}) == ['a', 'b', 'c', 'd', 'e']

    def test_W31_empty_or_deep_trees_and_undeclared_fields_are_refused(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find(Or()), 'QUERY_EMPTY_OR')
        deep = {'name': 'Alpha'}
        for _ in range(8):
            deep = And(deep)
        refused(QueryInvalid, lambda: t.find(deep), 'QUERY_TOO_DEEP')
        refused(QueryInvalid, lambda: t.find({'colour': 'red'}), 'QUERY_FIELD_NOT_DECLARED')
        refused(QueryInvalid, lambda: t.find({'name': Set({'x': 1})}), 'QUERY_WORD_MISPLACED')


class TestO:
    """3.3: order, paging, fields. O05 (the double shuffles ties) is the in-memory adapter's own case."""

    def test_O01_missing_and_null_sort_first_ascending(self, store):
        t = things(store)
        rows = list(t.find({}, sort=[('note', 1)]))
        assert sorted(ids(rows[:4])) == ['a', 'b', 'd', 'e'] and ids(rows[4:]) == ['c']

    def test_O02_missing_and_null_sort_last_descending(self, store):
        t = things(store)
        rows = list(t.find({}, sort=[('n', -1)]))
        assert ids(rows[:1]) == ['c'] and sorted(ids(rows[1:3])) == ['a', 'b'] and sorted(ids(rows[3:])) == ['d', 'e']

    def test_O03_several_keys(self, store):
        t = things(store)
        assert ids(t.find({'n': Exists()}, sort=[('n', -1), ('_id', 1)])) == ['c', 'a', 'b', 'e']
        assert ids(t.find({'n': Range(lt=5)}, sort=[('n', 1), ('_id', -1)])) == ['b', 'a', 'c']

    def test_O04_a_unique_key_last_gives_one_order(self, store):
        t = store.collection('things')
        t.insert([{'_id': 'r%02d' % n, 'rank': n % 3} for n in range(30)])
        want = sorted(('r%02d' % n for n in range(30)), key=lambda i: (int(i[1:]) % 3, i))
        assert ids(t.find({}, sort=[('rank', 1), ('_id', 1)])) == want
        assert ids(t.find({}, sort=[('rank', -1), ('_id', -1)])) == want[::-1]

    def test_O06_skip_and_limit(self, store):
        t = things(store)
        order = ids(t.find({}, sort=[('rank', 1)]))
        assert order == ['b', 'c', 'a', 'd', 'e']
        assert ids(t.find({}, sort=[('rank', 1)], skip=1, limit=2)) == ['c', 'a']
        assert ids(t.find({}, sort=[('rank', 1)], skip=4)) == ['e']
        assert ids(t.find({}, sort=[('rank', 1)], limit=0)) == [] and t.count({}, limit=0) == 0
        refused(QueryInvalid, lambda: t.find({}, skip=-1), 'QUERY_PAGE_FORM')
        refused(QueryInvalid, lambda: t.find({}, sort=[('tags', 1)]), 'QUERY_SORT_KIND')
        refused(QueryInvalid, lambda: t.find({}, sort=[('rank', 2)]), 'QUERY_SORT_FORM')

    def test_O07_fields(self, store):
        t = things(store)
        t.update({'_id': 'a'}, Set({'loose': {'deep': 1, 'other': 2}}))
        assert t.get('a', fields=['name', 'meta.kind', 'loose.deep']) == {
            '_id': 'a', 'name': 'Alpha', 'meta': {'kind': 'k1'}, 'loose': {'deep': 1}}
        assert list(t.find({'_id': 'd'}, fields=['name'])) == [{'_id': 'd'}]
        refused(QueryInvalid, lambda: t.find({}, fields=['meta', 'meta.kind']), 'QUERY_FIELDS_FORM')


class TestG:
    """3.3: group, values, count."""

    def test_G01_count_by_one_key(self, store):
        t = things(store)
        assert t.group({}, 'n') == [{'n': None, 'total': 2}, {'n': 1, 'total': 2}, {'n': 2, 'total': 1}]
        assert t.group({'rank': Range(lt=3)}, ('flag',)) == [{'flag': None, 'total': 1}, {'flag': False, 'total': 1}]
        refused(QueryInvalid, lambda: t.group({}, 'tags'), 'QUERY_GROUP_KIND')

    def test_G02_max(self, store):
        t = things(store)
        assert t.group({}, 'flag', total=Max('rank')) == [
            {'flag': None, 'total': 5}, {'flag': False, 'total': 1}, {'flag': True, 'total': 3}]
        assert t.group({'_id': 'd'}, 'flag', total=Max('at')) == [{'flag': None, 'total': None}]

    def test_G03_two_keys_in_order(self, store):
        t = store.collection('keyed')
        t.insert([{'_id': str(n), 'platform': 'p%d' % (n % 2), 'account': 'a%d' % n, 'state': 's%d' % (n % 3)}
                  for n in range(6)])
        rows = t.group({}, ('platform', 'state'))
        assert [(r['platform'], r['state'], r['total']) for r in rows] == [
            ('p0', 's0', 1), ('p0', 's1', 1), ('p0', 's2', 1), ('p1', 's0', 1), ('p1', 's1', 1), ('p1', 's2', 1)]

    def test_G04_values_ascending_without_records_missing_the_field(self, store):
        t = things(store)
        assert t.group({}, 'n', total=None) == [None, 1, 2]
        assert t.group({}, 'name', total=None) == ['Alpha', 'Beta', 'a.c', 'alpha']
        assert t.group({}, ('flag', 'n'), total=None) == [(False, 1), (True, 1)]

    def test_G05_count_with_a_limit(self, store):
        t = things(store)
        assert t.count({}) == 5 and t.count({}, limit=3) == 3 and t.count({'name': 'nobody'}, limit=3) == 0
        assert t.count({'n': 1}) == 2


class TestC:
    """3.4: change words, and the rules of a write that creates its record."""

    def test_C01_set_creates_missing_parents(self, store):
        t = things(store)
        assert t.update({'_id': 'd'}, Set({'meta.size': 5, 'extra.deep.x': 1})) == Updated(1, 1, False)
        assert t.get('d') == {'_id': 'd', 'rank': 4, 'meta': {'size': 5}, 'extra': {'deep': {'x': 1}}}
        assert t.update({'_id': 'd'}, Set({'meta.size': 5})) == Updated(1, 0, False)

    def test_C02_set_through_a_non_object_or_of_another_kind_is_refused(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.update({'_id': 'a'}, Set({'name.x': 1})), 'QUERY_PATH_THROUGH')
        t.update({'_id': 'a'}, Set({'loose': 'text'}))
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Set({'loose.x': 1})), 'RECORD_PATH_NOT_OBJECT')
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Set({'n': 'one'})), 'RECORD_KIND')
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Set({'meta': {'size': 'big'}})), 'RECORD_KIND')
        refused(QueryInvalid, lambda: t.update({'_id': 'a'}, Set({'_id': 'z'})), 'QUERY_CHANGE_ID')
        assert t.get('a')['loose'] == 'text' and t.get('a')['n'] == 1

    def test_C03_unset(self, store):
        t = things(store)
        assert t.update({'_id': 'a'}, Unset('note', 'meta.kind', 'nowhere')) == Updated(1, 1, False)
        assert 'note' not in t.get('a') and t.get('a')['meta'] == {'size': 3}
        k = store.collection('keyed')
        refused(RecordInvalid, lambda: k.update({'_id': 'x'}, Unset('account')), 'RECORD_REQUIRED')

    def test_C04_increase_starts_a_missing_field_at_zero(self, store):
        t = things(store)
        t.update({'_id': 'a'}, [Increase('meta.size', 2), Increase('count')])
        t.update({'_id': 'a'}, Increase('count', 0.5))
        assert t.get('a')['meta']['size'] == 5 and t.get('a')['count'] == 1.5

    def test_C05_increase_refuses_what_is_not_a_number(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.update({'_id': 'a'}, Increase('name')), 'QUERY_WORD_KIND')
        refused(QueryInvalid, lambda: t.update({'_id': 'a'}, Increase('rank', by='1')), 'QUERY_CHANGE_FORM')
        t.update({'_id': 'a'}, Set({'loose': 'text', 'yes': True}))
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Increase('loose')), 'RECORD_NOT_A_NUMBER')
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Increase('yes')), 'RECORD_NOT_A_NUMBER')

    def test_C06_larger_and_smaller(self, store):
        t = things(store)
        t.update({'_id': 'a'}, [Larger('rank', 2), Smaller('low', 7), Larger('high', 7)])
        assert (t.get('a')['rank'], t.get('a')['low'], t.get('a')['high']) == (3, 7, 7)
        t.update({'_id': 'a'}, [Larger('rank', 9), Smaller('low', 2), Larger('at', T0 + timedelta(days=1))])
        assert (t.get('a')['rank'], t.get('a')['low'], t.get('a')['at']) == (9, 2, T0 + timedelta(days=1))
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Larger('rank', 'z')), 'RECORD_KIND')
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Smaller('low', 'z')), 'RECORD_KIND')

    def test_C07_add_to_set(self, store):
        t = things(store)
        t.update({'_id': 'a'}, AddToSet('tags', 'y', 'z', 'z'))
        t.update({'_id': 'd'}, AddToSet('tags', 'a', 'b'))
        assert t.get('a')['tags'] == ['x', 'y', 'z'] and t.get('d')['tags'] == ['a', 'b']
        t.update({'_id': 'd'}, AddToSet('loose', 1, True, 1.0, 'b'))
        assert t.get('d')['loose'] == [1, True, 'b']
        refused(QueryInvalid, lambda: t.update({'_id': 'a'}, AddToSet('name', 'q')), 'QUERY_WORD_KIND')
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, AddToSet('tags', 1)), 'RECORD_KIND')

    def test_C08_push_keeps_the_last(self, store):
        t = things(store)
        t.update({'_id': 'a'}, Push('tags', 'p', 'q', keep_last=3))
        assert t.get('a')['tags'] == ['y', 'p', 'q']
        t.update({'_id': 'd'}, Push('log', {'n': 1}))
        t.update({'_id': 'd'}, Push('log', {'n': 2}, keep_last=0))
        assert t.get('d')['log'] == []
        t.update({'_id': 'a'}, Set({'loose': 1}))
        refused(RecordInvalid, lambda: t.update({'_id': 'a'}, Push('loose', 2)), 'RECORD_NOT_A_LIST')

    def test_C09_on_create_applies_only_to_a_created_record(self, store):
        t = things(store)
        t.update({'_id': 'a'}, [OnCreate({'name': 'never'}), Set({'note': 'set'})], create=True)
        assert t.get('a')['name'] == 'Alpha' and t.get('a')['note'] == 'set'
        t.update({'_id': 'z'}, [OnCreate({'name': 'made'}), Set({'note': 'set'})], create=True)
        assert t.get('z') == {'_id': 'z', 'name': 'made', 'note': 'set'}

    def test_C10_create_on_the_id(self, store):
        t = store.collection('things')
        change = [Set({'name': 'n'}), Increase('rank'), AddToSet('tags', 'a'), Push('sources', {'seq': 1})]
        assert t.update({'_id': 'new'}, change, create=True) == Updated(0, 0, True)
        assert t.get('new') == {'_id': 'new', 'name': 'n', 'rank': 1, 'tags': ['a'], 'sources': [{'seq': 1}]}
        assert t.update({'_id': 'new'}, change, create=True) == Updated(1, 1, False)
        assert t.get('new')['rank'] == 2
        assert t.update({'_id': 'other'}, change) == Updated(0, 0, False) and t.get('other') is None

    def test_C11_create_on_a_unique_index_and_nothing_else(self, store):
        k = store.collection('keyed')
        k.update({'platform': 'chat', 'account': '1'}, Set({'state': 'new'}), create=True)
        made = list(k.find({'platform': 'chat'}))
        assert len(made) == 1 and isinstance(made[0]['_id'], str) and made[0]['_id']
        assert {key: made[0][key] for key in ('platform', 'account', 'state')} == {
            'platform': 'chat', 'account': '1', 'state': 'new'}
        refused(QueryInvalid, lambda: k.update({'state': 'new'}, Set({'order': 1}), create=True),
                'QUERY_CREATE_WHERE')
        refused(QueryInvalid, lambda: k.update({'_id': 'x', 'order': Range(gt=1)}, Set({'order': 1}), create=True),
                'QUERY_CREATE_WHERE')
        refused(RecordInvalid, lambda: k.update({'_id': 'x'}, Set({'state': 'a'}), create=True), 'RECORD_REQUIRED')

    def test_C12_a_create_that_repeats_a_unique_key(self, store):
        k = store.collection('keyed')
        k.insert({'_id': 'k1', 'platform': 'chat', 'account': '1'})
        error = refused(DuplicateKey, lambda: k.update(
            {'_id': 'k2'}, Set({'platform': 'chat', 'account': '1'}), create=True))
        assert error.index == 'platform_1_account_1' and k.get('k2') is None
        refused(DuplicateKey, lambda: k.claim({'_id': 'k3'}, Set({'platform': 'chat', 'account': '1'}), create=True))


class TestX:
    """Writes: insert, get, delete, unique keys, revisions, claims, the counter."""

    def test_X01_insert_one(self, store):
        t = store.collection('things')
        t.insert(dict(ROWS[0]))
        assert t.get('a') == ROWS[0]

    def test_X02_insert_many_stops_at_a_duplicate_and_keeps_what_came_before(self, store):
        t = store.collection('things')
        error = refused(DuplicateKey, lambda: t.insert([{'_id': '1'}, {'_id': '2'}, {'_id': '1'}, {'_id': '3'}]))
        assert error.at == 2 and found(t, {}) == ['1', '2']
        refused(DuplicateKey, lambda: t.insert([{'_id': '2'}, {'_id': '4'}], ordered=False))
        assert found(t, {}) == ['1', '2', '4']

    def test_X03_get(self, store):
        t = things(store)
        assert t.get('nobody') is None
        assert t.get('c', fields=['name']) == {'_id': 'c', 'name': 'Beta'}
        refused(QueryInvalid, lambda: t.get(3), 'QUERY_ID')

    def test_X04_delete_one(self, store):
        t = things(store)
        assert t.delete({'n': 1}) == 1 and t.count({'n': 1}) == 1
        assert t.delete({'name': 'nobody'}) == 0

    def test_X05_delete_many(self, store):
        t = things(store)
        assert t.delete({'rank': Range(gte=3)}, many=True) == 3 and found(t, {}) == ['b', 'c']

    def test_X06_a_unique_index_of_required_fields(self, store):
        k = store.collection('keyed')
        k.insert({'_id': 'k1', 'platform': 'chat', 'account': '1'})
        k.insert({'_id': 'k2', 'platform': 'chat', 'account': '2'})
        error = refused(DuplicateKey, lambda: k.insert({'_id': 'k3', 'platform': 'chat', 'account': '1'}))
        assert error.index == 'platform_1_account_1' and error.collection == 'keyed'

    def test_X07_a_unique_index_only_where_present(self, store):
        k = store.collection('keyed')
        k.insert([{'_id': 'k1', 'platform': 'p', 'account': '1'}, {'_id': 'k2', 'platform': 'p', 'account': '2'},
                  {'_id': 'k3', 'platform': 'p', 'account': '3', 'event': 'e1'}])
        error = refused(DuplicateKey, lambda: k.insert({'_id': 'k4', 'platform': 'p', 'account': '4', 'event': 'e1'}))
        assert error.index == 'event_1'

    def test_X08_a_duplicate_on_update(self, store):
        k = store.collection('keyed')
        k.insert([{'_id': 'k1', 'platform': 'p', 'account': '1', 'event': 'e1'},
                  {'_id': 'k2', 'platform': 'p', 'account': '2'}])
        refused(DuplicateKey, lambda: k.update({'_id': 'k2'}, Set({'event': 'e1'})))
        assert 'event' not in k.get('k2')
        assert k.update({'_id': 'k1'}, Set({'event': 'e1'})) == Updated(1, 0, False)

    def test_X09_a_duplicate_on_replace(self, store):
        k = store.collection('keyed')
        k.insert([{'_id': 'k1', 'platform': 'p', 'account': '1'}, {'_id': 'k2', 'platform': 'p', 'account': '2'}])
        refused(DuplicateKey, lambda: k.replace({'_id': 'k2', 'platform': 'p', 'account': '1'}))
        refused(DuplicateKey, lambda: k.replace({'_id': 'k3', 'platform': 'p', 'account': '1'}, create=True))
        assert k.get('k2')['account'] == '2' and k.get('k3') is None

    def test_X10_replace_at_a_revision(self, store):
        k = store.collection('keyed')
        k.insert({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 1, 'state': 'a'})
        assert k.replace({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'state': 'b'}, expected=1)
        assert k.get('k1') == {'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'state': 'b'}
        assert k.replace({'_id': 'k9', 'platform': 'p', 'account': '9'}, create=True) and k.get('k9')

    def test_X11_a_stale_revision_writes_nothing(self, store):
        k = store.collection('keyed')
        k.insert({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'state': 'a'})
        assert k.replace({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'state': 'b'}, expected=1) \
            is False
        assert k.get('k1')['state'] == 'a'
        assert k.replace({'_id': 'k2', 'platform': 'p', 'account': '2', 'revision': 1}, expected=0) is False
        assert k.get('k2') is None

    def test_X12_replace_keeps_the_counters(self, store):
        k = store.collection('keyed')
        k.insert({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 1, 'sequence': 4})
        k.update({'_id': 'k1'}, Increase('sequence'))
        assert k.replace({'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'sequence': 4,
                          'order': 1}, expected=1, keep=('sequence', 'order'))
        assert k.get('k1') == {'_id': 'k1', 'platform': 'p', 'account': '1', 'revision': 2, 'sequence': 5}

    def test_X13_claim_takes_the_first_by_sort_and_returns_it_changed(self, store):
        k = store.collection('keyed')
        k.insert([{'_id': 'q%d' % n, 'platform': 'p', 'account': str(n), 'state': 'queued', 'order': (n * 7) % 5}
                  for n in range(5)])
        taken = [k.claim({'state': 'queued'}, Set({'state': 'taken'}), sort=[('order', 1)]) for _ in range(6)]
        assert [row and (row['order'], row['state']) for row in taken] == [
            (0, 'taken'), (1, 'taken'), (2, 'taken'), (3, 'taken'), (4, 'taken'), None]

    def test_X14_the_counter(self, store):
        t = things(store)
        assert [t.claim({'_id': 'a'}, Increase('rank'))['rank'] for _ in range(3)] == [4, 5, 6]
        assert t.claim({'_id': 'nobody'}, Increase('rank')) is None
        assert t.claim({'_id': 'fresh'}, Increase('rank'), create=True) == {'_id': 'fresh', 'rank': 1}


class TestT:
    """Time: aware, UTC, milliseconds; `Now` is the database's clock at the write."""

    def test_T01_an_aware_time_comes_back_as_the_same_instant_in_utc(self, store):
        t = store.collection('things')
        local = datetime(2026, 3, 4, 18, 30, 1, 250000, tzinfo=timezone(timedelta(hours=13)))
        t.insert({'_id': 'x', 'at': local, 'loose': {'when': local}})
        back = t.get('x')
        assert back['at'] == local and back['at'].utcoffset() == timedelta(0) and back['loose']['when'] == local

    def test_T02_a_naive_time_is_refused(self, store):
        t = store.collection('things')
        naive = datetime(2026, 3, 4, 5, 6, 7)
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'at': naive}), 'RECORD_NAIVE_TIME')
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'loose': [naive]}), 'RECORD_NAIVE_TIME')
        refused(QueryInvalid, lambda: t.find({'at': naive}), 'QUERY_NAIVE_TIME')
        refused(RecordInvalid, lambda: t.update({'_id': 'x'}, Set({'at': naive})), 'RECORD_NAIVE_TIME')

    def test_T03_times_are_kept_to_the_millisecond(self, store):
        t = store.collection('things')
        moment = datetime(2026, 3, 4, 5, 6, 7, 456789, tzinfo=timezone.utc)
        t.insert({'_id': 'x', 'at': moment})
        assert t.get('x')['at'] == moment.replace(microsecond=456000)
        assert found(t, {'at': moment}) == ['x'] and found(t, {'at': Range(gt=moment)}) == []

    def test_T04_now_bounds_a_range_in_update_and_claim(self, store):
        l = store.collection('leases')
        real = datetime.now(timezone.utc)
        l.insert([{'_id': 'old', 'expires_at': real - timedelta(hours=1)},
                  {'_id': 'live', 'expires_at': real + timedelta(hours=1)}])
        assert l.update({'expires_at': Range(lt=Now())}, Set({'instance': 'me'}), many=True) == Updated(1, 1, False)
        assert l.get('old')['instance'] == 'me' and 'instance' not in l.get('live')
        assert l.claim({'expires_at': Range(gt=Now(7200))}, Set({'instance': 'x'})) is None
        assert l.claim({'expires_at': Range(gt=Now(-7200), lt=Now())}, Set({'instance': 'y'}))['_id'] == 'old'
        refused(QueryInvalid, lambda: l.find({'expires_at': Range(lt=Now())}), 'QUERY_NOW_MISPLACED')
        refused(QueryInvalid, lambda: store.collection('things').update({'name': Range(lt=Now())}, Set({'n': 1})),
                'QUERY_NOW_MISPLACED')

    def test_T05_now_in_set_and_in_an_insert(self, store):
        l = store.collection('leases')
        l.insert({'_id': 'host', 'instance': 'a', 'since': Now(), 'expires_at': Now(30)})
        before = datetime.now(timezone.utc)
        l.update({'_id': 'host'}, Set({'since': Now(), 'expires_at': Now(30), 'planned_stop.at': Now()}))
        after = datetime.now(timezone.utc)
        lease = l.get('host')
        assert before - timedelta(seconds=5) <= lease['since'] <= after + timedelta(seconds=5)
        assert lease['expires_at'] - lease['since'] == timedelta(seconds=30)
        assert lease['planned_stop']['at'] == lease['since']
        refused(QueryInvalid, lambda: l.replace({'_id': 'host', 'since': Now()}), 'QUERY_NOW_MISPLACED')
        refused(QueryInvalid, lambda: l.update({'_id': 'host'}, Set({'instance': Now()})), 'QUERY_NOW_MISPLACED')


class TestV:
    """3.1: declared fields, kinds, null, required, size."""

    def test_V01_undeclared_fields_are_stored_and_returned_unchanged(self, store):
        t = store.collection('things')
        record = {'_id': 'x', 'loose': {'a': [1, 'two', {'three': None}], 'b': True}, 'raw': b'\x00\x01',
                  'MixedCase': 1.5}
        t.insert(record)
        assert t.get('x') == record

    def test_V02_undeclared_fields_cannot_be_named(self, store):
        t = things(store)
        refused(QueryInvalid, lambda: t.find({'loose': 1}), 'QUERY_FIELD_NOT_DECLARED')
        refused(QueryInvalid, lambda: t.find({}, sort=[('loose', 1)]), 'QUERY_FIELD_NOT_DECLARED')
        refused(QueryInvalid, lambda: t.group({}, 'loose'), 'QUERY_FIELD_NOT_DECLARED')
        refused(QueryInvalid, lambda: t.find({'meta.other': 1}), 'QUERY_FIELD_NOT_DECLARED')

    def test_V03_each_declared_kind_is_held(self, store):
        t = store.collection('things')
        for bad in ({'name': 1}, {'at': '2026-01-01T00:00:00+00:00'}, {'tags': 'x'}, {'tags': ['x', 2]},
                    {'meta': 'k1'}, {'sources': [{'seq': 'one'}]}, {'meta': {'size': '3'}}):
            refused(RecordInvalid, lambda: t.insert({'_id': 'x', **bad}), 'RECORD_KIND')
        u = store.collection('units')
        refused(RecordInvalid, lambda: u.insert({'_id': 'u', 'embedding': [0.5] * (DIM - 1)}), 'RECORD_KIND')
        u.insert({'_id': 'u', 'embedding': [0.5] * DIM})
        assert t.get('x') is None and u.get('u')['embedding'] == [0.5] * DIM

    def test_V04_a_bool_is_not_a_number_and_a_number_not_a_bool(self, store):
        t = store.collection('things')
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'n': True}), 'RECORD_KIND')
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'flag': 1}), 'RECORD_KIND')

    def test_V05_null_only_where_declared_nullable(self, store):
        t = store.collection('things')
        t.insert({'_id': 'x', 'n': None, 'meta': {'kind': None}})
        refused(RecordInvalid, lambda: t.insert({'_id': 'y', 'name': None}), 'RECORD_NULL')
        refused(RecordInvalid, lambda: t.update({'_id': 'x'}, Set({'rank': None})), 'RECORD_NULL')

    def test_V06_required_fields(self, store):
        k = store.collection('keyed')
        refused(RecordInvalid, lambda: k.insert({'_id': 'k', 'platform': 'p'}), 'RECORD_REQUIRED')
        refused(RecordInvalid, lambda: k.insert({'_id': 'k', 'platform': 'p', 'account': None}), 'RECORD_NULL')
        refused(RecordInvalid, lambda: k.insert({'platform': 'p', 'account': '1'}), 'RECORD_ID')
        refused(RecordInvalid, lambda: k.insert({'_id': 5, 'platform': 'p', 'account': '1'}), 'RECORD_ID')

    def test_V07_values_of_no_kind_are_refused(self, store):
        t = store.collection('things')
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'loose': {1, 2}}), 'RECORD_VALUE_KIND')
        refused(RecordInvalid, lambda: t.insert({'_id': 'x', 'loose': {1: 'a'}}), 'RECORD_KEY')
        t.insert({'_id': 'x', 'loose': ('a', 'b')})
        assert t.get('x')['loose'] == ['a', 'b']

    def test_V08_a_record_over_one_mebibyte_is_refused(self, store):
        t = store.collection('things')
        overhead = len('{"_id":"x","loose":""}')
        t.insert({'_id': 'x', 'loose': 'a' * (1024 * 1024 - overhead)})
        error = refused(RecordTooLarge, lambda: t.insert({'_id': 'y', 'loose': 'a' * (1024 * 1024 - overhead + 1)}))
        assert error.code == 'DOCUMENT_TOO_LARGE_USE_ARTIFACT' and t.get('y') is None


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def brute(rows, vector, keep):
    q = unit(vector)
    scored = [(row['_id'], sum(a * b for a, b in zip(q, unit(row['embedding'])))) for row in rows if keep(row)]
    return sorted(scored, key=lambda hit: (-hit[1], hit[0]))


PAIRS = (('s0', 1), ('s2', 1), ('s4', 2))
NEAREST = [
    ('no filter', {}, lambda r: True),
    ('value', {'status': 'active'}, lambda r: r['status'] == 'active'),
    ('list', {'scope_key': AnyOf(['s1', 's3'])}, lambda r: r['scope_key'] in ('s1', 's3')),
    ('pairs', And(Or(*[{'scope_key': s, 'policy_epoch': e} for s, e in PAIRS]), {'status': 'active'}),
     lambda r: (r['scope_key'], r['policy_epoch']) in PAIRS and r['status'] == 'active'),
    ('pairs and kind', And(Or({'scope_key': 's1', 'policy_epoch': 2}, {'scope_key': 's3', 'policy_epoch': 2}),
                           {'kind': 'monologue'}),
     lambda r: (r['scope_key'], r['policy_epoch']) in {('s1', 2), ('s3', 2)} and r['kind'] == 'monologue'),
]


@pytest.fixture(scope='class')
def vectors(open_store):
    with open_store() as opened:
        opened.ensure(['units'])
        rng = random.Random(10428)
        rows = [{'_id': 'u%03d' % n, 'embedding': [rng.uniform(-1, 1) for _ in range(DIM)],
                 'scope_key': 's%d' % (n % 5), 'policy_epoch': 1 + n % 2,
                 'status': 'active' if n % 7 else 'forgotten', 'kind': 'monologue' if n % 3 == 0 else 'turn'}
                for n in range(300)]
        rows.append(dict(rows[10], _id='u999'))         # an identical vector: a tie
        opened.collection('units').insert([dict(r) for r in rows])
        # Made first with fewer filter fields, so the next ensure_vectors has to bring it up to the space's.
        assert opened.ensure_vectors(Space(SPACE.name, SPACE.collection, SPACE.path, DIM, ('scope_key',)), timeout=120)
        assert opened.ensure_vectors(SPACE, timeout=180)
        yield opened, rows, [rows[10]['embedding']] + [[rng.uniform(-1, 1) for _ in range(DIM)] for _ in range(9)]


class TestN:
    """Vector search: exact cosine against brute force, as step 1b built it."""

    def test_N01_the_index_is_brought_up_to_the_space(self, vectors):
        store, rows, queries = vectors
        got = store.nearest(SPACE, queries[1], 5, {'kind': 'monologue'})
        assert [i for i, _ in got] == [i for i, _ in brute(rows, queries[1], lambda r: r['kind'] == 'monologue')[:5]]

    @pytest.mark.parametrize('label,where,keep', NEAREST, ids=[c[0] for c in NEAREST])
    @pytest.mark.parametrize('k', (1, 12, 24))
    def test_N02_nearest_is_exact_cosine(self, vectors, label, where, keep, k):
        store, rows, queries = vectors
        for q in queries:
            got, everything = store.nearest(SPACE, q, k, where), brute(rows, q, keep)
            want = everything[:k]
            assert len(got) == len(want) and all(abs(a - b) < 1e-4 for (_, a), (_, b) in zip(got, want))
            last = want[-1][1]
            tied = {i for i, s in everything if abs(s - last) < 1e-4}
            # Above the k-th score the same records in id order; at it, any of the records tied there.
            assert all(g == w if s > last + 1e-4 else g in tied for (g, _), (w, s) in zip(got, want))

    def test_N17_ties_come_in_id_order(self, vectors):
        store, rows, _ = vectors
        assert [i for i, _ in store.nearest(SPACE, rows[10]['embedding'], 2, {})] == ['u010', 'u999']

    def test_N18_empty_any_of_matches_nothing_and_bad_queries_are_refused(self, vectors):
        store, _, queries = vectors
        assert store.nearest(SPACE, queries[1], 5, {'scope_key': AnyOf([])}) == []
        for where, vector, k, code in (({'body': 'x'}, queries[1], 5, 'VECTOR_FIELD_NOT_DECLARED'),
                                       ({'status': Range(gt='a')}, queries[1], 5, 'VECTOR_FILTER_WORD'),
                                       ({}, queries[1][:3], 5, 'VECTOR_SHAPE'), ({}, [0.0] * DIM, 5, 'VECTOR_SHAPE'),
                                       ({}, queries[1], 0, 'VECTOR_K'), ({}, queries[1], 101, 'VECTOR_K')):
            refused(QueryInvalid, lambda: store.nearest(SPACE, vector, k, where), code)


class _Stream:
    """A synthetic stream of `size` bytes (a seeded block repeated), read in pieces of whatever size is asked."""

    def __init__(self, size, seed):
        self.size, self.at, self.block = size, 0, random.Random(seed).randbytes(65537)

    def read(self, n=-1):
        n = self.size - self.at if n is None or n < 0 else min(n, self.size - self.at)
        piece = bytearray()
        while len(piece) < n:
            offset = (self.at + len(piece)) % len(self.block)
            piece += self.block[offset:offset + n - len(piece)]
        self.at += n
        return bytes(piece)


class TestB:
    """The blob store."""

    def test_B01_write_and_open(self, store):
        blob_id, size = store.blobs.write(io.BytesIO(b'hello blob'), {'scope_key': 's', 'kind': 'file'})
        assert isinstance(blob_id, str) and size == 10 and store.blobs.open(blob_id).read() == b'hello blob'
        refused(RecordInvalid, lambda: store.blobs.write(io.BytesIO(b'x'), {'kind': 'file'}), 'RECORD_BLOB_META')

    def test_B02_a_blob_opens_seekable(self, store):
        data = bytes(range(256)) * 4
        blob_id, _ = store.blobs.write(io.BytesIO(data), {'scope_key': 's', 'kind': 'file'})
        stream = store.blobs.open(blob_id)
        stream.seek(100)
        assert stream.read(10) == data[100:110]
        assert stream.seek(0, io.SEEK_END) == len(data)

    def test_B03_delete_twice(self, store):
        blob_id, _ = store.blobs.write(io.BytesIO(b'x'), {'scope_key': 's', 'kind': 'file'})
        assert store.blobs.delete(blob_id) is True and store.blobs.delete(blob_id) is False
        refused(BlobMissing, lambda: store.blobs.open(blob_id))

    def test_B04_a_missing_blob(self, store):
        refused(BlobMissing, lambda: store.blobs.open('0' * 24), 'BLOB_MISSING')

    def test_B05_blobs_of_a_scope(self, store):
        mine = {store.blobs.write(io.BytesIO(b'%d' % n), {'scope_key': 'mine', 'kind': 'file',
                                                          'source_ids': ['m%d' % n]})[0] for n in range(3)}
        store.blobs.write(io.BytesIO(b'other'), {'scope_key': 'theirs', 'kind': 'file'})
        assert set(store.blobs.of_scope('mine')) == mine and store.blobs.of_scope('nobody') == []

    def test_B06_a_five_mebibyte_stream(self, store):
        size = 5 * 1024 * 1024 + 17
        blob_id, written = store.blobs.write(_Stream(size, 7), {'scope_key': 's', 'kind': 'file'})
        expected, got, stored = hashlib.sha256(_Stream(size, 7).read()).hexdigest(), hashlib.sha256(), 0
        stream = store.blobs.open(blob_id)
        while piece := stream.read(1024 * 1024 - 3):
            got.update(piece)
            stored += len(piece)
        assert written == size == stored and got.hexdigest() == expected


class _Without:
    """The adapter under test with no capabilities, failing if anything reaches it."""
    capabilities = frozenset()

    def __getattr__(self, name):
        raise AssertionError('the call reached the adapter: ' + name)


class TestS:
    """Schema: ensure, retired and conflicting indexes, capabilities, the registry."""

    def test_S01_ensure_is_idempotent(self, store):
        fresh = Catalog([Collection('fresh', owner='tests', fields=(Field('x', 'number'),),
                                    indexes=(Index('x_1', (('x', 1),)),))])
        shared = Checked(store.adapter, fresh)
        assert shared.ensure() == {'fresh': Ensured(True, ('x_1',), ())}
        assert shared.ensure() == {'fresh': Ensured(False, (), ())}
        assert set(store.ensure().values()) == {Ensured(False, (), ())}

    def test_S02_a_retired_index_is_dropped(self, store):
        field = (Field('x', 'number'),)
        Checked(store.adapter, Catalog([Collection('fresh', 'tests', field, (Index('x_1', (('x', 1),)),))])).ensure()
        later = Checked(store.adapter, Catalog([Collection('fresh', 'tests', field, retired=('x_1', 'never_made'))]))
        assert later.ensure() == {'fresh': Ensured(False, (), ('x_1',))}
        assert later.ensure() == {'fresh': Ensured(False, (), ())}

    def test_S03_an_index_of_the_same_name_that_differs_is_refused(self, store):
        field = (Field('x', 'number', required=True),)
        Checked(store.adapter, Catalog([Collection('fresh', 'tests', field, (Index('x_1', (('x', 1),)),))])).ensure()
        for other in (Index('x_1', (('x', -1),)), Index('x_1', (('x', 1),), unique=True)):
            error = refused(SchemaConflict, lambda: Checked(
                store.adapter, Catalog([Collection('fresh', 'tests', field, (other,))])).ensure())
            assert error.name == 'x_1'

    def test_S04_a_missing_capability_is_refused_before_dispatch(self, store):
        bare = Checked(_Without(), CATALOG)
        refused(NotSupported, lambda: bare.nearest(SPACE, [1.0] * DIM, 3, {}), 'STORE_NOT_SUPPORTED')
        refused(NotSupported, lambda: bare.ensure_vectors(SPACE), 'STORE_NOT_SUPPORTED')

    def test_S05_an_adapter_kind_not_installed_is_refused(self):
        error = refused(AdapterNotInstalled, lambda: adapters.open({'database_adapter': 'no-such-kind'}, 'x'))
        assert str(error) == 'DATABASE_ADAPTER_NOT_INSTALLED: no-such-kind'

