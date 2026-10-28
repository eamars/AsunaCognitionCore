"""The store's collections over a hand-made database, for the offline case modules' fake stores: the in-memory adapter
reads and writes the fake's own rows (each fake collection's `docs` or `rows`), so a record owner and the code that still
reads the fake directly see one set of records. Plain Python: no pymongo, as the offline checks run without it."""
from asuna.store import Checked
from asuna.store.catalog import CATALOG
from asuna.store.memory import Database, MemoryAdapter


class _Records(dict):
    """The in-memory adapter's record table, each collection looked up in the fake database when it is asked for."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    def get(self, name, default=None):
        column = self.db[name] if hasattr(self.db, '__getitem__') else getattr(self.db, name)
        rows = getattr(column, 'docs', None)
        rows = column.rows if rows is None else rows
        # A fake that keeps a list is read through a view by id (the cases that use one only read it).
        return {row['_id']: row for row in rows} if isinstance(rows, list) else rows

    setdefault = get


def collections(db):
    """A store's `collection(name)` over the fake database `db`."""
    data = Database()
    data.records = _Records(db)
    return Checked(MemoryAdapter(data, seed=0), CATALOG).collection
