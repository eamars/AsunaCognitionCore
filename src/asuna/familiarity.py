"""How well she knows a person, in words (AGENTS.md: interpreted state from a versioned table).

Computed from records the host already keeps; nothing new is stored and no number reaches her. The level is about
the person (their canonical identity, across every conversation), and nothing a message says can raise it: the owner
by his account, and a person she has written her understanding of (ADR-135 D1). Anyone else has no level and no word.
A persona gives each level its stance (persona-model `people.familiarity`); the core only names the levels.
"""
from .records import heads as head_records

TABLE_VERSION = 2
LEVELS = ('owner', 'known')
CORE_WORDS = {
    'owner': '{owner_label}本人',
    'known': '你写过对他的理解',
}


def _ids(store, person_id):
    """(the canonical person, every id of theirs her records may name)."""
    from .scene_links import canonical_person_id, extra_person_values
    person = canonical_person_id(store.config, store, person_id) or person_id
    return person, sorted({person_id, person, *extra_person_values(store.config, store, person)} - {None, ''})


def _understandings(store, ids):
    return head_records.with_prefix(store, *('relationship:%s|' % i for i in ids))


def level(store, person_id):
    """'owner', 'known', or None for this author: the owner's account, then her own written understanding."""
    person, ids = _ids(store, person_id)
    if person and person == (store.config.get('chat') or {}).get('person_id'):
        return 'owner'
    if ids and _understandings(store, ids).first(fields=['_id']):
        return 'known'
    return None


def known_before(store, person_id, moment):
    """Whether she first wrote her understanding of this person on an earlier day than `moment`, on her clock: the
    earliest revision of any of her records of them against the day of the request, two stored times (ADR-135 D1)."""
    from . import clock
    from .local_time import her_zone
    _, ids = _ids(store, person_id)
    if not ids:
        return False
    firsts = [row.get('created_at') for head in _understandings(store, ids).rows(fields=['_id'])
              for row in [head_records.history(store, head['_id']).first(fields=['created_at']) or {}]]
    firsts = [value for value in firsts if value]
    if not firsts:
        return False
    tz = her_zone(store)['tz']
    first = min(clock.moment(value) for value in firsts)
    return first.astimezone(tz).date() < clock.moment(moment).astimezone(tz).date()


def words(store, person_id, persona=None):
    """{'familiarity': the level in words, 'stance': the persona's stance at that level, when it has one}; nothing for
    someone with no level."""
    from .people import People
    from .persona_model import effective
    from .render import model_and_policy
    name = level(store, person_id)
    if name is None:
        return {}
    model, policy = model_and_policy(store, persona) if persona else ({}, {})
    row = (effective(model, 'people.familiarity', policy) or {}).get(name) or {}
    out = {'familiarity': row.get('label') or CORE_WORDS[name].format(owner_label=People(store, persona).owner_label)}
    if row.get('stance'):
        out['stance'] = row['stance']
    return out
