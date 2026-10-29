"""The store's errors: what the shared layer and an adapter raise, each a message that starts with its code.

`QueryInvalid` is a condition, sort or change the meaning table refuses, raised before any adapter sees it;
`RecordInvalid` a value a record cannot hold (from the shared layer, or from an adapter for a change the stored record
cannot take). The rest name one situation each. `refuse_in_unit_run` is the unit run's lock: in a process with
`ASUNA_UNIT_RUN=1` (tests/conftest.py sets it; every process the run starts inherits it) nothing opens a database.
"""
import os

UNIT_RUN = 'ASUNA_UNIT_RUN'


class StoreError(Exception):
    """Every error of the store; `code` is the first word of its message."""

    @property
    def code(self):
        return str(self).split(':', 1)[0]


class QueryInvalid(StoreError, ValueError):
    """A condition, sort, group, field list or change the meaning table refuses."""


class RecordInvalid(StoreError, ValueError):
    """A record, or a value written into one, that its collection's declared fields cannot hold."""


class RecordTooLarge(StoreError, ValueError):
    """A record over the store's limit by its adapter's measure."""


class DuplicateKey(StoreError):
    """A write repeated a unique key: `index` names the index, `at` the position in an insert of several."""

    def __init__(self, collection, index, at=None):
        self.collection, self.index, self.at = collection, index, at
        where = '' if at is None else '（第 %d 条）' % at
        super().__init__('DUPLICATE_KEY: %s 的唯一键 %s 已经有这个值的记录了%s；换一个值，或者读出已有的那条再改它'
                         % (collection, index, where))


class StaleRevision(StoreError):
    """A revisioned write found the record at another revision than the one it was read at."""

    def __init__(self, collection, record_id, expected):
        self.collection, self.record_id, self.expected = collection, record_id, expected
        super().__init__('STALE_REVISION: %s 的 %s 已经不是第 %s 版了，这次没有写进去；读一次最新的再做'
                         % (collection, record_id, expected))


class NotSupported(StoreError):
    """The adapter lacks a capability the call needs; raised before the database is reached."""

    def __init__(self, capability):
        self.capability = capability
        super().__init__('STORE_NOT_SUPPORTED: 这个数据库适配器没有 %s 这项能力；不是参数的问题，重试也一样' % capability)


class SchemaConflict(StoreError):
    """The database holds an index of a declared name with other keys or options."""

    def __init__(self, name, why):
        self.name, self.why = name, why
        super().__init__('SCHEMA_CONFLICT: 索引 %s 和声明的不一样（%s）；先把数据库里的那个改成声明的样子' % (name, why))


class Unavailable(StoreError, OSError):
    """The database cannot be reached."""


class BlobMissing(StoreError, LookupError):
    """No stored blob has that id."""

    def __init__(self, blob_id):
        self.blob_id = blob_id
        super().__init__('BLOB_MISSING: 存储里没有 %s 这份字节' % blob_id)


class AdapterNotInstalled(StoreError, RuntimeError):
    """No adapter of the asked kind is installed."""


class InUnitRun(RuntimeError):
    """A database was asked for in a unit run. Not a StoreError: no caller takes it for an outage and goes on."""


def refuse_in_unit_run(what):
    """Raise InUnitRun when this process is a unit run's: unit tests never need a database."""
    if os.environ.get(UNIT_RUN) == '1':
        raise InUnitRun('DATABASE_IN_UNIT_RUN: %s：单元测试不连数据库（%s=1）；要数据库的测试写在 integration/'
                        % (what, UNIT_RUN))
