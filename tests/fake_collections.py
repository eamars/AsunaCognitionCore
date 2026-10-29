"""The store's collections over a hand-made database, for the offline case modules' fake stores: the in-memory adapter
reads and writes the fake's own rows (each fake collection's `docs` or `rows` dict), so a record owner and the code
that still reads the fake directly see one set of records. A fake that keeps a list is read through a read-only view
by id: a write through an owner there fails at once rather than going nowhere; so is a collection the fake does
not hold, read as empty. Plain Python: no pymongo, as the offline checks run without it."""
from types import MappingProxyType

from asuna.store import Checked
from asuna.store.catalog import CATALOG
from asuna.store.memory import Database, MemoryAdapter


class _Records(dict):
    """The in-memory adapter's record table, each collection looked up in the fake database when it is asked for."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    def get(self, name, default=None):
        column = self.db[name] if hasattr(self.db, '__getitem__') else getattr(self.db, name, None)
        if column is None:                    # a collection the fake does not hold: no records, and no writes
            return MappingProxyType({})
        rows = getattr(column, 'docs', None)
        rows = column.rows if rows is None else rows
        return MappingProxyType({row['_id']: row for row in rows}) if isinstance(rows, list) else rows

    setdefault = get


def checked(db):
    """The shared layer over the in-memory adapter reading and writing the fake database `db`'s rows."""
    data = Database()
    data.records = _Records(db)
    return Checked(MemoryAdapter(data, seed=0), CATALOG)


def collections(db):
    """A store's `collection(name)` over the fake database `db`."""
    return checked(db).collection
