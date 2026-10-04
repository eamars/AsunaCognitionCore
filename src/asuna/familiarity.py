"""How well she knows a person, in words (AGENTS.md: interpreted state from a versioned table).

Computed from records the host already keeps; nothing new is stored and no number reaches her. The level
is about the person (their canonical identity, across every conversation), and nothing a message says can
raise it: only the owner's account, her own written understanding, and how often she has actually talked
with them count. A persona gives each level its stance (persona-model `people.familiarity`); the core only
names the levels.
"""
import re

TABLE_VERSION = 1
LEVELS = ('owner', 'known', 'regular', 'met', 'new')
# Coarse thresholds: turns in which she answered this person, and lines this person wrote where she could read them.
KNOWN_REPLIES = 15
REGULAR_REPLIES, REGULAR_LINES = 4, 60
MET_REPLIES, MET_LINES = 1, 8
CORE_WORDS = {
    'owner': '{owner_label}本人',
    'known': '熟人：你们来往很多，或你写过对他的理解',
    'regular': '常来往：你们聊过不少',
    'met': '见过几次：跟你说过几句话',
    'new': '不熟：几乎没跟你说过话',
}
NO_UNDERSTANDING = '你还没写过对这个人的理解。'


def level(store, person_id):
    """One of LEVELS for this author, from the owner's account, her understanding and real exchanges."""
    from .scene_links import canonical_person_id, extra_person_values
    config, db = store.config, store.db
    person = canonical_person_id(config, db, person_id) or person_id
    if person and person == (config.get('chat') or {}).get('person_id'):
        return 'owner'
    ids = sorted({person_id, person, *extra_person_values(config, db, person)} - {None, ''})
    if db.state_heads.find_one({'_id': {'$regex': r'^relationship:(%s)\|' % '|'.join(re.escape(i) for i in ids)}}, {'_id': 1}):
        return 'known'
    replies = db.episodes.count_documents({'person_id': {'$in': ids}, 'state': {'$in': ['COMMITTED', 'WAITING_TASK']},
                                           'speech': {'$exists': True}},
                                           limit=KNOWN_REPLIES)
    if replies >= KNOWN_REPLIES:
        return 'known'
    lines = db.messages.count_documents({'author': {'$in': ids}, 'direction': 'inbound'}, limit=REGULAR_LINES)
    if replies >= REGULAR_REPLIES or lines >= REGULAR_LINES:
        return 'regular'
    if replies >= MET_REPLIES or lines >= MET_LINES:
        return 'met'
    return 'new'


def words(store, person_id, persona=None):
    """{'familiarity': the level in words, 'stance': the persona's stance at that level, when it has one}."""
    from .people import People
    from .persona_model import effective
    from .render import model_and_policy
    name = level(store, person_id)
    model, policy = model_and_policy(store, persona) if persona else ({}, {})
    row = (effective(model, 'people.familiarity', policy) or {}).get(name) or {}
    out = {'familiarity': row.get('label') or CORE_WORDS[name].format(owner_label=People(store, persona).owner_label)}
    if row.get('stance'):
        out['stance'] = row['stance']
    return out
