"""The owner of `identities` and `scene_people`: who a person is on this machine (their identity: platform, account,
the name the operator gave them) and how each conversation labels them (its label rows: number, card, nickname, role,
when last seen), read and written only through these operations.

`identity` and `label` return a record as stored (`fields` names what to return; `_id` always comes back). None
follows section 4's rule: an id or a fence (a person, an account, a platform, a conversation) given None, or a value not
of its kind, finds nothing without a read. The other reads are views (`View`: `rows`, `each`, `first`, `count`), in
the replaced read's order (none where it had none). `save_identity` and `save_label` are the revisioned writes
(`Store.put`).
"""
from ..store.words import Not
from .view import ANY, View, fenced, is_text

IDENTITIES, LABELS = 'identities', 'scene_people'


def _labels(store, where, by=()):
    by = (by,) if isinstance(by, str) else tuple(by)
    return View(store, LABELS, where, tuple((path, 1) for path in by))


# Identities.

def identity(store, person_id, fields=None):
    """The identity of a person (its id is the person's), or None."""
    return store.collection(IDENTITIES).get(person_id, fields) if is_text(person_id) else None


def by_account(store, account_id, *, platform=ANY, fields=None):
    """The identity of an account (on this platform), or None."""
    where = fenced({}, {'account_id': (account_id, is_text), 'platform': (platform, is_text)})
    return View(store, IDENTITIES, where).first(fields=fields)


def of_person(store, person_id, fields=None):
    """The identity whose `person_id` is this, or None."""
    return View(store, IDENTITIES, fenced({}, {'person_id': (person_id, is_text)})).first(fields=fields)


def all_identities(store):
    """View: every identity."""
    return View(store, IDENTITIES, {})


def save_identity(store, row, **kwargs):
    """The revisioned write of an identity (`Store.put`: `expected`, `stream`)."""
    return store.put(IDENTITIES, row, **kwargs)


# A conversation's labels.

def label(store, label_id, fields=None):
    """A conversation's label row by its id (`<conversation>|<person>`), or None."""
    return store.collection(LABELS).get(label_id, fields) if is_text(label_id) else None


def labels(store, scene_id, *, besides=ANY):
    """View: a conversation's label rows (not this person's)."""
    where = fenced({}, {'scene_id': (scene_id, is_text)})
    if where is not None and besides is not ANY:
        where['person'] = Not(besides)
    return _labels(store, where)


def label_of_person(store, person, fields=None):
    """A person's label row seen last, in any conversation, or None."""
    return _labels(store, fenced({}, {'person': (person, is_text)}), 'seen_at').first(newest_first=True,
                                                                                    fields=fields)


def first_label(store, scene_id, *, by, newest_first=False, fields=None):
    """A conversation's first label row by `by` (`newest_first` turns it: the highest number), or None."""
    return _labels(store, fenced({}, {'scene_id': (scene_id, is_text)}), by).first(newest_first=newest_first,
                                                                                 fields=fields)


def save_label(store, row, **kwargs):
    """The revisioned write of a label row (`Store.put`: `expected`, `stream`)."""
    return store.put(LABELS, row, **kwargs)
