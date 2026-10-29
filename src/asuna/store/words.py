"""The words the core describes records with: conditions, changes, sorts and totals, their JSON form for her read
tool, and their validation against a collection's declaration before any adapter sees them.

A `where` is a mapping {field: value or word}, every entry holding, or `And(...)` / `Or(...)` of wheres; a plain
value is equality. A `change` is one change word or a list of them. The meaning of each word is the in-memory
adapter's (memory.py), and every adapter answers the same. The `check_*` functions refuse with `QueryInvalid` the
forms the meaning table refuses, refuse with `RecordInvalid` a value a declared field cannot hold or a naive time
written, and return the words with every time in UTC at millisecond precision.
"""
from __future__ import annotations
from collections.abc import Mapping
from datetime import datetime, timezone
import json
import uuid
from .catalog import is_number, kind_of
from .errors import QueryInvalid, RecordInvalid, RecordTooLarge

MAX_DEPTH = 8
MAX_RECORD_BYTES = 1024 * 1024


class Word:
    """A word of the vocabulary; two are equal when their kind and arguments are."""
    __slots__ = ()

    def _args(self):
        return tuple(getattr(self, name) for name in type(self).__slots__)

    def __eq__(self, other):
        return type(self) is type(other) and self._args() == other._args()

    __hash__ = None

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, ', '.join(map(repr, self._args())))


# Condition words.

class AnyOf(Word):
    """Equal to one of the values; `AnyOf([])` matches nothing."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = list(values)


class NoneOf(Word):
    """Missing, null, or equal to none of the values; `NoneOf([])` matches every record."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = list(values)


class Not(Word):
    """The complement of equality: missing and null match."""
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value


class Range(Word):
    """Present, of the field's kind and within every bound given."""
    __slots__ = ('gt', 'gte', 'lt', 'lte')

    def __init__(self, *, gt=None, gte=None, lt=None, lte=None):
        self.gt, self.gte, self.lt, self.lte = gt, gte, lt, lte

    def bounds(self):
        return {name: value for name, value in zip(self.__slots__, self._args()) if value is not None}


class Exists(Word):
    """Present with any value, null included (`Exists(False)`: absent)."""
    __slots__ = ('present',)

    def __init__(self, present=True):
        self.present = present


class IsNull(Word):
    """Present and null."""
    __slots__ = ()


class StartsWith(Word):
    """Text that starts with any of the prefixes, literally, case kept."""
    __slots__ = ('prefixes',)

    def __init__(self, *prefixes):
        self.prefixes = prefixes


class Contains(Word):
    """Text that contains `text` literally; `case=False` folds each character that folds to one character."""
    __slots__ = ('text', 'case')

    def __init__(self, text, case=True):
        self.text, self.case = text, case


class Holds(Word):
    """A list with an element equal to the value."""
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value


class HoldsAny(Word):
    """A list with an element equal to one of the values."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = list(values)


class HoldsNone(Word):
    """A list with no element equal to any of the values; a list missing or null matches."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = list(values)


class NonEmpty(Word):
    """A list with at least one element."""
    __slots__ = ()


class Each(Word):
    """A list of objects with one element that meets every entry of `where` (paths relative to the element)."""
    __slots__ = ('where',)

    def __init__(self, where):
        self.where = where


class And(Word):
    __slots__ = ('wheres',)

    def __init__(self, *wheres):
        self.wheres = wheres


class Or(Word):
    __slots__ = ('wheres',)

    def __init__(self, *wheres):
        self.wheres = wheres


class Now(Word):
    """The database's clock at the moment of the write, plus `seconds`: a `Range` bound in `update` and `claim`, and a
    value of a `time` field in `Set`, `OnCreate` and `insert`."""
    __slots__ = ('seconds',)

    def __init__(self, seconds=0):
        self.seconds = seconds


# Change words.

class Set(Word):
    """Sets each path, creating missing parent objects."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = dict(values)


class Unset(Word):
    """Each path is absent afterwards."""
    __slots__ = ('paths',)

    def __init__(self, *paths):
        self.paths = paths


class Increase(Word):
    """Adds `by` to a number; a missing field starts at 0."""
    __slots__ = ('path', 'by')

    def __init__(self, path, by=1):
        self.path, self.by = path, by


class Larger(Word):
    """Keeps the larger of the stored value and `value`; a missing field takes the value."""
    __slots__ = ('path', 'value')

    def __init__(self, path, value):
        self.path, self.value = path, value


class Smaller(Word):
    """Keeps the smaller of the stored value and `value`; a missing field takes the value."""
    __slots__ = ('path', 'value')

    def __init__(self, path, value):
        self.path, self.value = path, value


class AddToSet(Word):
    """Adds each value the list does not hold yet; a missing field becomes the list."""
    __slots__ = ('path', 'values')

    def __init__(self, path, *values):
        self.path, self.values = path, values


class Push(Word):
    """Appends the values, then keeps the last `keep_last` elements."""
    __slots__ = ('path', 'values', 'keep_last')

    def __init__(self, path, *values, keep_last=None):
        self.path, self.values, self.keep_last = path, values, keep_last


class OnCreate(Word):
    """Sets each path only when the write creates the record."""
    __slots__ = ('values',)

    def __init__(self, values):
        self.values = dict(values)


# What a read returns.

class Without(Word):
    """Every field of a record but these paths (`_id` always comes back): a read's `fields` that leaves out a large one
    no caller of that read uses."""
    __slots__ = ('paths',)

    def __init__(self, *paths):
        self.paths = paths


# Totals of `group`.

class Count(Word):
    __slots__ = ()


class Max(Word):
    __slots__ = ('field',)

    def __init__(self, field):
        self.field = field


def _shown(value):
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + '...'


def to_utc_ms(moment: datetime) -> datetime:
    """An aware time in UTC, truncated to the millisecond (what every adapter stores)."""
    moment = moment.astimezone(timezone.utc)
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


# Conditions.

def check_where(collection, where, *, now=False):
    """`where` validated against the declared collection; `now`: `Now` may bound a range (update and claim)."""
    return _where(collection, {} if where is None else where, now, '', 1)


def _where(collection, where, now, within, depth):
    if depth > MAX_DEPTH:
        raise QueryInvalid('QUERY_TOO_DEEP: 条件嵌套超过 %d 层；拆成几次读' % MAX_DEPTH)
    if isinstance(where, (And, Or)):
        if isinstance(where, Or) and not where.wheres:
            raise QueryInvalid('QUERY_EMPTY_OR: Or() 里一个分支也没有；至少写一个条件')
        return type(where)(*[_where(collection, w, now, within, depth + 1) for w in where.wheres])
    if not isinstance(where, Mapping):
        raise QueryInvalid('QUERY_WHERE_FORM: 条件要写成 {字段: 值或词}，或 And(...)、Or(...)（给的是 %s）'
                           % type(where).__name__)
    checked = {}
    for key, test in where.items():
        if not isinstance(key, str):
            raise QueryInvalid('QUERY_WHERE_FORM: 字段名要是文字（给的是 %s）' % _shown(key))
        field = _queried(collection, within + '.' + key if within else key, within)
        checked[key] = _test(collection, field, test, now, depth)
    return checked


def _queried(collection, path, within=''):
    """The declared field a condition, sort or group names; a path through a list is refused outside `Each`."""
    field = collection.field(path)
    if field is None:
        raise QueryInvalid('QUERY_FIELD_NOT_DECLARED: %s 没有声明字段 "%s"；条件、排序和分组只能用声明过的字段：%s'
                           % (collection.name, path, '、'.join(collection.paths())))
    parts = path.split('.')
    for n in range(1, len(parts)):
        prefix = '.'.join(parts[:n])
        if within and len(prefix) <= len(within):
            continue
        if collection.field(prefix).kind == 'list':
            raise QueryInvalid('QUERY_PATH_THROUGH_LIST: "%s" 穿过了列表 "%s"；对列表里的对象写 {"%s": Each({...})}'
                               % (path, prefix, prefix))
    return field


def _value(field, value, *, element=False):
    """A condition's value, of the field's kind (its element kind for list words), times in UTC ms."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise QueryInvalid('QUERY_NAIVE_TIME: "%s" 的时间 %s 没有时区；给带时区的时间' % (field.path, value))
        value = to_utc_ms(value)
    if not (field.holds_element(value) if element else field.holds(value)):
        raise QueryInvalid('QUERY_KIND_MISMATCH: "%s" 是 %s，给的 %s 是 %s'
                           % (field.path, field.of if element else field.kind, _shown(value), kind_of(value)))
    return value


def _equal(field, value):
    if value is None:
        raise QueryInvalid('QUERY_NULL_EQUALITY: "%s" 等于 None 不是条件；值是 null 的用 IsNull()，没有这个字段的用 '
                           'Exists(False)' % field.path)
    if field.kind == 'list':
        raise QueryInvalid('QUERY_EQUALITY_ON_LIST: "%s" 是列表，不能拿整个列表比相等；用 Holds 或 HoldsAny'
                           % field.path)
    if field.kind in ('object', 'vector'):
        raise QueryInvalid('QUERY_EQUALITY_ON_OBJECT: "%s" 是 %s，不能比相等；写它里面声明过的字段'
                           % (field.path, field.kind))
    return _value(field, value)


def _needs(field, kinds, word):
    if field.kind not in kinds:
        raise QueryInvalid('QUERY_WORD_KIND: %s 不能用在 "%s"（%s）上，只能用在 %s 上'
                           % (word, field.path, field.kind, '、'.join(kinds)))


def _test(collection, field, test, now, depth):
    if not isinstance(test, Word):
        return _equal(field, test)
    name = type(test).__name__
    if isinstance(test, (AnyOf, NoneOf)):
        return type(test)([_equal(field, value) for value in test.values])
    if isinstance(test, Not):
        return Not(_equal(field, test.value))
    if isinstance(test, Range):
        _needs(field, ('text', 'number', 'bool', 'time'), name)
        bounds = test.bounds()
        if not bounds:
            raise QueryInvalid('QUERY_RANGE_EMPTY: "%s" 的 Range 一个边界也没有；写 gt、gte、lt、lte 里的至少一个'
                               % field.path)
        for bound, value in bounds.items():
            if isinstance(value, Now):
                if not now or field.kind != 'time':
                    raise QueryInvalid('QUERY_NOW_MISPLACED: Now() 只能做 update、claim 里 time 字段的 Range 边界'
                                       '（这里是 "%s"）' % field.path)
            else:
                bounds[bound] = _value(field, value)
        return Range(**bounds)
    if isinstance(test, Exists):
        if not isinstance(test.present, bool):
            raise QueryInvalid('QUERY_WORD_FORM: Exists 要 True 或 False（给的是 %s）' % _shown(test.present))
        return test
    if isinstance(test, IsNull):
        if not field.nullable:
            raise QueryInvalid('QUERY_NOT_NULLABLE: "%s" 没有声明可以是 null，IsNull 什么也找不到' % field.path)
        return test
    if isinstance(test, StartsWith):
        _needs(field, ('text',), name)
        if not test.prefixes or not all(isinstance(p, str) and p for p in test.prefixes):
            raise QueryInvalid('QUERY_EMPTY_TEXT: StartsWith 至少要一个不空的前缀（"%s"）' % field.path)
        return test
    if isinstance(test, Contains):
        _needs(field, ('text',), name)
        if not isinstance(test.text, str) or not test.text or not isinstance(test.case, bool):
            raise QueryInvalid('QUERY_EMPTY_TEXT: Contains 要一段不空的文字，case 是 True 或 False（"%s"）'
                               % field.path)
        return test
    if isinstance(test, (Holds, HoldsAny, HoldsNone)):
        _needs(field, ('list',), name)
        if field.of == 'object':
            raise QueryInvalid('QUERY_EQUALITY_ON_OBJECT: "%s" 的元素是对象，不能比相等；用 Each({...})' % field.path)
        if isinstance(test, Holds):
            return Holds(_value(field, test.value, element=True))
        return type(test)([_value(field, value, element=True) for value in test.values])
    if isinstance(test, NonEmpty):
        _needs(field, ('list',), name)
        return test
    if isinstance(test, Each):
        if field.kind != 'list' or field.of != 'object':
            raise QueryInvalid('QUERY_WORD_KIND: Each 只能用在对象的列表上（"%s" 是 %s）' % (field.path, field.kind))
        return Each(_where(collection, test.where, False, field.path, depth + 1))
    raise QueryInvalid('QUERY_WORD_MISPLACED: %s 不是条件里的词（"%s"）' % (name, field.path))


def check_vector_where(collection, space, where):
    """A vector search's filter: equality, `AnyOf`, `And` and `Or` on the space's filter fields."""
    def walk(where, depth):
        if isinstance(where, (And, Or)) and depth <= MAX_DEPTH:
            for branch in where.wheres:
                walk(branch, depth + 1)
            return
        for key, test in (where.items() if isinstance(where, Mapping) else ()):
            if key not in space.fields:
                raise QueryInvalid('VECTOR_FIELD_NOT_DECLARED: 向量空间 %s 只能按 %s 过滤（给的是 "%s"）'
                                   % (space.name, '、'.join(space.fields), key))
            if isinstance(test, Word) and not isinstance(test, AnyOf):
                raise QueryInvalid('VECTOR_FILTER_WORD: 向量搜索的过滤只用相等、AnyOf、And、Or（"%s" 用了 %s）'
                                   % (key, type(test).__name__))
    walk(where, 1)
    return check_where(collection, where)


# Sorts, field lists, pages, groups.

def check_sort(collection, sort):
    """[(field, 1 | -1)] on declared fields that are not lists, objects or vectors."""
    checked = []
    for item in sort or ():
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise QueryInvalid('QUERY_SORT_FORM: 排序写成 [(字段, 1 或 -1), ...]（给的是 %s）' % _shown(item))
        path, direction = item
        field = _queried(collection, path)
        if field.kind in ('list', 'object', 'vector'):
            raise QueryInvalid('QUERY_SORT_KIND: 不能按 %s 字段 "%s" 排序' % (field.kind, path))
        if direction not in (1, -1) or isinstance(direction, bool):
            raise QueryInvalid('QUERY_SORT_FORM: "%s" 的方向要 1 或 -1（给的是 %s）' % (path, _shown(direction)))
        if path in [p for p, _ in checked]:
            raise QueryInvalid('QUERY_SORT_FORM: "%s" 在排序里出现了两次' % path)
        checked.append((path, direction))
    return tuple(checked)


def check_fields(fields):
    """The paths to return (`_id` always comes back), or `Without(paths)` to return all but those; None returns whole
    records."""
    if fields is None:
        return None
    left_out = isinstance(fields, Without)
    paths = fields.paths if left_out else fields
    # A dict (MongoDB's projection) would be read as the list of its keys, {'embedding': 0} as "embedding only".
    if isinstance(paths, (str, Mapping)) or not all(isinstance(p, str) and p and all(p.split('.')) for p in paths):
        raise QueryInvalid('QUERY_FIELDS_FORM: 要返回的字段写成字段名的列表（给的是 %s）' % _shown(fields))
    paths = list(dict.fromkeys(paths))
    if left_out and (not paths or '_id' in paths):
        raise QueryInvalid('QUERY_FIELDS_FORM: Without 至少要一个字段，_id 总会返回、去不掉（给的是 %s）' % _shown(fields))
    for a in paths:
        for b in paths:
            if a != b and b.startswith(a + '.'):
                raise QueryInvalid('QUERY_FIELDS_FORM: "%s" 和 "%s" 重叠了；只留一个' % (a, b))
    return Without(*paths) if left_out else tuple(paths)


def check_page(skip, limit):
    for name, value in (('skip', skip), ('limit', limit)):
        if value is None and name == 'limit':
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise QueryInvalid('QUERY_PAGE_FORM: %s 要是不小于 0 的整数（给的是 %s）' % (name, _shown(value)))
    return skip, limit


def check_group(collection, by, total):
    """(the `by` fields, the total): `by` names declared value fields; the total is `Count()`, `Max(field)` or None."""
    by = (by,) if isinstance(by, str) else tuple(by)
    if not by:
        raise QueryInvalid('QUERY_GROUP_FORM: 分组至少要一个字段')
    for path in by:
        field = _queried(collection, path)
        if field.kind in ('list', 'object', 'vector'):
            raise QueryInvalid('QUERY_GROUP_KIND: 不能按 %s 字段 "%s" 分组' % (field.kind, path))
    if len(set(by)) != len(by):
        raise QueryInvalid('QUERY_GROUP_FORM: 分组字段重复了')
    if isinstance(total, Max):
        _needs(_queried(collection, total.field), ('text', 'number', 'time'), 'Max')
    elif total is not None and not isinstance(total, Count):
        raise QueryInvalid('QUERY_GROUP_FORM: 总数写 Count()、Max(字段) 或 None（给的是 %s）' % _shown(total))
    return by, total


# Writes.

def _written(collection, value, path, now):
    """A copy of a written value: times aware and in UTC ms, tuples as lists; `Now` only at a declared time field."""
    if isinstance(value, Now):
        field = collection.field(path)
        if not now or field is None or field.kind != 'time':
            raise QueryInvalid('QUERY_NOW_MISPLACED: Now() 只能写进声明为 time 的字段（这里是 "%s"）' % path)
        if not is_number(value.seconds):
            raise QueryInvalid('QUERY_WORD_FORM: Now 的秒数要是数（给的是 %s）' % _shown(value.seconds))
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise RecordInvalid('RECORD_NAIVE_TIME: "%s" 的时间 %s 没有时区；只存带时区的时间' % (path, value))
        return to_utc_ms(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) and key for key in value):
            raise RecordInvalid('RECORD_KEY: "%s" 里的键要是不空的文字' % path)
        return {key: _written(collection, item, path + '.' + key if path else key, now) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_written(collection, item, path, now) for item in value]
    if isinstance(value, Word):
        raise QueryInvalid('QUERY_WORD_MISPLACED: %s 不能当作值写进 "%s"' % (type(value).__name__, path))
    if value is None or isinstance(value, (str, bool, int, float, bytes)):
        return value
    raise RecordInvalid('RECORD_VALUE_KIND: "%s" 的值是 %s，存不了' % (path, type(value).__name__))


def _values_at(value, parts):
    """The values at a path, through the objects of lists on the way."""
    if not parts:
        yield value
    elif isinstance(value, dict):
        if parts[0] in value:
            yield from _values_at(value[parts[0]], parts[1:])
    elif isinstance(value, list):
        for item in value:
            yield from _values_at(item, parts)


def _containers(value, parts):
    for found in _values_at(value, parts):
        if isinstance(found, dict):
            yield found
        elif isinstance(found, list):
            yield from (item for item in found if isinstance(item, dict))


def _declared_values(collection, value, base):
    """Check every declared field at or under `base` that `value` (the value written at `base`) reaches."""
    for field in collection.fields:
        if base and field.path != base and not field.path.startswith(base + '.'):
            continue
        rest = field.path[len(base) + 1:] if base else field.path
        parts = rest.split('.') if rest else []
        for found in _values_at(value, parts):
            if found is None:
                if not field.nullable:
                    raise RecordInvalid('RECORD_NULL: "%s" 不能是 null' % field.path)
            elif not isinstance(found, Now) and not field.holds(found):
                raise RecordInvalid('RECORD_KIND: "%s" 是 %s%s，写进来的 %s 是 %s'
                                    % (field.path, field.kind, '（%s）' % (field.of or field.dimensions)
                                       if field.kind in ('list', 'vector') else '', _shown(found), kind_of(found)))
        if field.required and parts:
            for container in _containers(value, parts[:-1]):
                if container.get(parts[-1]) is None:
                    raise RecordInvalid('RECORD_REQUIRED: 缺了必填的 "%s"' % field.path)


def record_bytes(record) -> int:
    """A record's size as canonical JSON (UTF-8)."""
    return len(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode())


def check_record(collection, record, *, now=False, measure=record_bytes):
    """A copy of a whole record, validated: a text `_id`, every declared field of its kind, the required ones
    present, at most 1 MiB by the adapter's `measure`; `now`: `Now` may stand for a time (insert)."""
    if not isinstance(record, Mapping):
        raise RecordInvalid('RECORD_FORM: 记录要是一个 dict（给的是 %s）' % type(record).__name__)
    doc = _written(collection, record, '', now)
    if not isinstance(doc.get('_id'), str) or not doc['_id']:
        raise RecordInvalid('RECORD_ID: 记录的 _id 要是不空的文字（给的是 %s）' % _shown(doc.get('_id')))
    _declared_values(collection, doc, '')
    if measure(doc) > MAX_RECORD_BYTES:
        raise RecordTooLarge('DOCUMENT_TOO_LARGE_USE_ARTIFACT')
    return doc


def _target(collection, path):
    """The declared field a change writes (None when undeclared); a path through anything but an object is refused."""
    if not isinstance(path, str) or not path or not all(path.split('.')):
        raise QueryInvalid('QUERY_CHANGE_FORM: 要改的字段名要是不空的文字（给的是 %s）' % _shown(path))
    parts = path.split('.')
    if parts[0] == '_id':
        raise QueryInvalid('QUERY_CHANGE_ID: _id 改不了；要换 _id 就写一条新记录')
    for n in range(1, len(parts)):
        parent = collection.field('.'.join(parts[:n]))
        if parent is not None and parent.kind != 'object':
            raise QueryInvalid('QUERY_PATH_THROUGH: "%s" 是 %s，不能往里面写 "%s"' % (parent.path, parent.kind, path))
    return collection.field(path)


def _orderable(collection, path, value, word):
    field = _target(collection, path)
    if value is None or kind_of(value) not in ('number', 'text', 'time'):
        raise RecordInvalid('RECORD_KIND: %s 要数、文字或时间（"%s" 给的是 %s）' % (word, path, _shown(value)))
    if field is not None:
        _declared_values(collection, value, path)


def _listed(collection, path, values, word):
    field = _target(collection, path)
    if not values:
        raise QueryInvalid('QUERY_CHANGE_FORM: %s 至少要一个值（"%s"）' % (word, path))
    if field is not None:
        if field.kind != 'list':
            raise QueryInvalid('QUERY_WORD_KIND: %s 只能用在列表上（"%s" 是 %s）' % (word, path, field.kind))
        _declared_values(collection, list(values), path)


def holds_now(value) -> bool:
    if isinstance(value, Now):
        return True
    if isinstance(value, Mapping):
        return any(holds_now(v) for v in value.values())
    if isinstance(value, list):
        return any(holds_now(v) for v in value)
    return False


def check_change(collection, change, *, create=False):
    """A change validated: a list of change words, each value copied with times in UTC ms; two words never write
    one path or a path inside another. A change that writes `Now` holds only `Set` and `Unset` and creates nothing
    (a server writes it with an update pipeline)."""
    words = list(change) if isinstance(change, (list, tuple)) else [change]
    if not words:
        raise QueryInvalid('QUERY_CHANGE_EMPTY: 没有要改的；至少写一个 Set、Unset、Increase……')
    checked, paths = [], []
    for word in words:
        if isinstance(word, (Set, OnCreate)):
            if not word.values:
                raise QueryInvalid('QUERY_CHANGE_EMPTY: %s 里没有字段' % type(word).__name__)
            values = {}
            for path, value in word.values.items():
                if not (isinstance(word, OnCreate) and path == '_id'):
                    field = _target(collection, path)
                elif not isinstance(value, str) or not value:
                    raise RecordInvalid('RECORD_ID: _id 要是不空的文字（给的是 %s）' % _shown(value))
                else:
                    field = None
                values[path] = _written(collection, value, path, True)
                if field is not None:
                    _declared_values(collection, values[path], path)
                paths.append(path)
            checked.append(type(word)(values))
        elif isinstance(word, Unset):
            if not word.paths:
                raise QueryInvalid('QUERY_CHANGE_EMPTY: Unset 里没有字段')
            for path in word.paths:
                field = _target(collection, path)
                if field is not None and field.required:
                    raise RecordInvalid('RECORD_REQUIRED: "%s" 是必填的，不能去掉' % path)
                paths.append(path)
            checked.append(word)
        elif isinstance(word, Increase):
            field = _target(collection, word.path)
            if not is_number(word.by):
                raise QueryInvalid('QUERY_CHANGE_FORM: Increase 的 by 要是数（给的是 %s）' % _shown(word.by))
            if field is not None and field.kind != 'number':
                raise QueryInvalid('QUERY_WORD_KIND: Increase 只能用在数上（"%s" 是 %s）' % (word.path, field.kind))
            paths.append(word.path)
            checked.append(word)
        elif isinstance(word, (Larger, Smaller)):
            value = _written(collection, word.value, word.path, False)
            _orderable(collection, word.path, value, type(word).__name__)
            paths.append(word.path)
            checked.append(type(word)(word.path, value))
        elif isinstance(word, (AddToSet, Push)):
            values = [_written(collection, value, word.path, False) for value in word.values]
            _listed(collection, word.path, values, type(word).__name__)
            if isinstance(word, Push):
                keep = word.keep_last
                if keep is not None and (not isinstance(keep, int) or isinstance(keep, bool) or keep < 0):
                    raise QueryInvalid('QUERY_CHANGE_FORM: keep_last 要是不小于 0 的整数（给的是 %s）' % _shown(keep))
                checked.append(Push(word.path, *values, keep_last=keep))
            else:
                checked.append(AddToSet(word.path, *values))
            paths.append(word.path)
        else:
            raise QueryInvalid('QUERY_CHANGE_WORD: %s 不是改动的词；用 Set、Unset、Increase、Larger、Smaller、AddToSet、'
                               'Push、OnCreate' % _shown(word))
    for a in paths:
        for b in paths:
            if a is not b and (a == b or b.startswith(a + '.')):
                raise QueryInvalid('QUERY_CHANGE_CONFLICT: 同一次改动里 "%s" 和 "%s" 写到了一处；分成两次' % (a, b))
    if any(isinstance(w, (Set, OnCreate)) and holds_now(w.values) for w in checked) and (
            create or not all(isinstance(w, (Set, Unset)) for w in checked)):
        raise QueryInvalid('QUERY_NOW_MISPLACED: 写 Now() 的改动只能有 Set 和 Unset，也不能新建记录；分成两次写')
    return checked


def check_create(collection, where, change):
    """The change of a write that may create its record, with the created record's `_id` as `OnCreate` when the
    condition does not give it. Creating needs equality on `_id`, or on every field of a declared unique index, and
    nothing else; the created record must get every required field."""
    if not isinstance(where, Mapping) or not where or any(isinstance(test, Word) for test in where.values()):
        raise QueryInvalid('QUERY_CREATE_WHERE: 可以新建记录的写，条件只能是相等（_id，或一个唯一索引的全部字段）')
    keys = set(where)
    if '_id' not in keys and not any({path for path, _ in index.keys} <= keys for index in collection.unique()):
        raise QueryInvalid('QUERY_CREATE_WHERE: 新建要按 _id 或一个唯一索引的全部字段找（给的是 %s）'
                           % '、'.join(sorted(keys)))
    written = set(keys)
    for word in change:
        for path in (word.values if isinstance(word, (Set, OnCreate)) else word.paths if isinstance(word, Unset)
                     else [word.path]):
            if not isinstance(word, Unset):
                written.add(path.split('.')[0])
    missing = [field.path for field in collection.fields if field.required and '.' not in field.path
               and field.path not in written]
    if missing:
        raise RecordInvalid('RECORD_REQUIRED: 新建的记录会缺必填的 %s' % '、'.join(missing))
    if '_id' in written:
        return change
    return [*change, OnCreate({'_id': uuid.uuid4().hex})]


# The JSON form (her read tool).

_JSON_ONE = {'any_of': AnyOf, 'none_of': NoneOf, 'not': Not, 'holds': Holds, 'holds_any': HoldsAny,
             'holds_none': HoldsNone}
_MONGO = {'$eq': '直接写值', '$in': '{"any_of": [...]}', '$nin': '{"none_of": [...]}', '$ne': '{"not": 值}',
          '$gt': '{"range": {"gt": 值}}', '$gte': '{"range": {"gte": 值}}', '$lt': '{"range": {"lt": 值}}',
          '$lte': '{"range": {"lte": 值}}', '$exists': '{"exists": true}', '$type': '{"is_null": true}',
          '$regex': '{"starts_with": [...]} 或 {"contains": "...", "case": false}', '$elemMatch': '{"each": {...}}',
          '$size': '{"non_empty": true}', '$all': '"and": [{"字段": {"holds": 值}}, ...]'}
WORDS_JSON = ('any_of', 'none_of', 'not', 'range', 'exists', 'is_null', 'starts_with', 'contains', 'holds',
              'holds_any', 'holds_none', 'non_empty', 'each')


def _mongo(key, field=None):
    if key in ('$or', '$and'):
        hint = '这里写 {"%s": [...]}' % key[1:]
    elif key in _MONGO and field:
        hint = '这里' + (_MONGO[key] if key == '$eq' else '写 {"%s": %s}' % (field, _MONGO[key]))
    else:
        hint = '这里没有对应的词；能用的：%s，以及 "or"、"and"' % '、'.join(WORDS_JSON)
    return QueryInvalid('QUERY_MONGO_SYNTAX: "%s" 是 MongoDB 的写法；%s' % (key, hint))


def from_json(where):
    """The words of a condition given in her JSON form: a plain value is equality, a dict value is one word
    (`{"any_of": [...]}`, `{"range": {"gte": ...}}`, `{"contains": "...", "case": false}`, ...), and logic is the
    keys `"or"` and `"and"`."""
    if not isinstance(where, Mapping):
        raise QueryInvalid('QUERY_WHERE_FORM: 条件要是一个对象 {字段: 值或词}（给的是 %s）' % type(where).__name__)
    entries, logic = {}, []
    for key, value in where.items():
        if isinstance(key, str) and key.startswith('$'):
            raise _mongo(key)
        if key in ('or', 'and'):
            if not isinstance(value, list) or (key == 'or' and not value):
                raise QueryInvalid('QUERY_WHERE_FORM: "%s" 要一个不空的条件列表' % key)
            branches = [from_json(branch) for branch in value]
            logic.append(Or(*branches) if key == 'or' else And(*branches))
        else:
            entries[key] = _json_test(key, value)
    if not logic:
        return entries
    if not entries and len(logic) == 1:
        return logic[0]
    return And(*([entries] if entries else []), *logic)


def _json_test(field, value):
    if isinstance(value, list):
        raise QueryInvalid('QUERY_EQUALITY_ON_LIST: "%s" 给了一个列表；列表里含某个值写 {"holds": 值}，等于其中之一写 '
                           '{"any_of": [...]}' % field)
    if not isinstance(value, Mapping):
        return value
    for key in value:
        if isinstance(key, str) and key.startswith('$'):
            raise _mongo(key, field)
    keys = set(value)
    if 'contains' in keys and keys <= {'contains', 'case'}:
        return Contains(value['contains'], value.get('case', True))
    if len(keys) != 1 or not keys <= set(WORDS_JSON):
        raise QueryInvalid('QUERY_WORD_UNKNOWN: "%s" 的 %s 不是一个词；能用的：%s'
                           % (field, _shown(dict(value)), '、'.join(WORDS_JSON)))
    (word, argument), = value.items()
    if word in _JSON_ONE:
        return _JSON_ONE[word](argument)
    if word == 'range':
        if not isinstance(argument, Mapping) or not set(argument) <= {'gt', 'gte', 'lt', 'lte'}:
            raise QueryInvalid('QUERY_WORD_FORM: "%s" 的 range 写成 {"gt"、"gte"、"lt"、"lte": 值}' % field)
        return Range(**argument)
    if word == 'exists':
        return Exists(argument)
    if word in ('is_null', 'non_empty'):
        if argument is not True:
            raise QueryInvalid('QUERY_WORD_FORM: "%s" 的 %s 只写 true' % (field, word))
        return IsNull() if word == 'is_null' else NonEmpty()
    if word == 'starts_with':
        return StartsWith(*([argument] if isinstance(argument, str) else argument))
    return Each(from_json(argument))


def to_json(where):
    """A condition in her JSON form (what her read tool shows as the filter asked)."""
    if isinstance(where, (And, Or)):
        return {type(where).__name__.lower(): [to_json(branch) for branch in where.wheres]}
    return {key: _json_word(test) for key, test in where.items()}


def _json_word(test):
    if not isinstance(test, Word):
        return test
    for name, kind in _JSON_ONE.items():
        if type(test) is kind:
            return {name: test.values if 'values' in kind.__slots__ else test.value}
    if isinstance(test, Range):
        return {'range': test.bounds()}
    if isinstance(test, Exists):
        return {'exists': test.present}
    if isinstance(test, IsNull):
        return {'is_null': True}
    if isinstance(test, NonEmpty):
        return {'non_empty': True}
    if isinstance(test, StartsWith):
        return {'starts_with': list(test.prefixes)}
    if isinstance(test, Contains):
        return {'contains': test.text, 'case': test.case}
    if isinstance(test, Each):
        return {'each': to_json(test.where)}
    raise QueryInvalid('QUERY_WORD_MISPLACED: %s 没有 JSON 写法' % type(test).__name__)
