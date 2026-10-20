"""Her understanding of a person, in two layers (owner 2026-10-08, with her wording).

- The person layer: one record per person (`relationship:<canonical person>|person`), shown wherever she meets
  them. What she thinks holds of them anywhere.
- The here layer: one record per person and conversation (`relationship:<person>|scene:<scene>`, as before), shown
  only there. How they are in this place; someone may speak differently in one group than in another.

She chooses the layer each time she writes (`understand_person`). The program does not filter what goes where: the
note gives her three questions to ask on the spot, and the person layer always opens with the line that it is only
part of them. Each person-layer revision records where it was written; it is read with that conversation's name and
the time (a timestamp field, shown on the local clock).

In groups (ADR-082) she reads the room by people: each layer carries her one line for herself (`short`, written with
the body). The person who starts a turn, and anyone whose @ or reply to her waits behind it, come in as an entry
(`group_people`: familiarity, stance, the shorts); the full layers come with `recall`'s `person` (`read`), and at home
「名单」 lists everyone she has written (`listing`). A layer written before shorts shows its body in the short's place.
One-to-one conversations keep the `relationship` block as before.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

PERSON_SCOPE = 'person'
LAYERS = ('person', 'here')
NO_PERSON = '你还没写过这个人在哪儿都成立的那一层。'
NO_HERE = '你还没写过他在这里是什么样。'
PART = '这只是他的一部分，不是他的全部'
PART_ELSEWHERE = '；你在另外 %d 个对话里还各有一份他在那儿的样子，这里看不到'
ASK = ('写之前当场问自己三句：① 这条换个群还成立吗？成立才写进 person（人那层），不成立写 here（这里那层）。'
       '② 这条在一个正经的场合说出口，当事人会不会不舒服？会就别进人那层，留在这里那层。'
       '③ 这条是他说的、你看到的，还是你推的？推的标明是推的。人那层不是他的全部。')


def person_entity(config, db, person_id):
    from .scene_links import canonical_person_id
    return 'relationship:' + (canonical_person_id(config, db, person_id) or person_id)


def person_ids(config, db, person_id):
    """Every id this person goes by: the account, its canonical person, and configured aliases."""
    from .scene_links import canonical_person_id, extra_person_values
    canonical = canonical_person_id(config, db, person_id) or person_id
    return sorted({person_id, canonical, *extra_person_values(config, db, canonical)} - {None, ''})


def _elsewhere(store, person_id, here_scope):
    ids = '|'.join(re.escape(i) for i in person_ids(store.config, store.db, person_id))
    return sum(1 for head in store.db.state_heads.find({'_id': {'$regex': r'^relationship:(%s)\|scene:' % ids}},
                                                       {'scope_key': 1}) if head.get('scope_key') != here_scope)


def _written(store, revision, moment):
    """(where it was last written, when) or None; the time is a field, shown on the local clock."""
    from .people import People
    origin = revision.get('origin') or {}
    scene = store.db.scenes.find_one({'_id': origin.get('scene_id')}) if origin.get('scene_id') else None
    try:
        datetime.fromisoformat(origin['at'])
    except (KeyError, TypeError, ValueError):
        return None
    return ('最后是在%s里改的' % (People(store).scene_title(scene) if scene else '一个现在已经没有的对话'), origin['at'])


def person_view(store, person_id, here_scope, head, moment=None):
    """The person layer as she reads it: the fixed line first, then her text and where it was last written."""
    moment = moment or datetime.now(timezone.utc)
    others = _elsewhere(store, person_id, here_scope)
    view = {'first': PART + (PART_ELSEWHERE % others if others else '') + '。'}
    if not head:
        view['text'] = NO_PERSON
        return view
    view['text'] = (head[1].get('content') or {}).get('body') or NO_PERSON
    written = _written(store, head[1], moment)
    if written:
        view['written'], view['written_at'] = written
    return view



# ---- groups (ADR-082) -------------------------------------------------------------------------------------------
SHORT_CHARS = 80                     # a word in the description; a longer one is kept and the result says by how much
ENTRY_MAX = 8                        # people in one turn's entry: the trigger and the queued addresses behind it
EXPLICIT = ('mentioned_account', 'reply_to_character', 'catchup_mention')    # a waiting line addressed to her
LIST_WORD = '名单'
NOT_WRITTEN = '还没写过'
LIST_HOME_ONLY = '「名单」只在家里列：那张表会把你别的对话里的人带进一个外面的人能写字的回合；回家里 recall 的 person 写「名单」。'


def layers(store, scene, person_id):
    """(person head, here head) of this person as this conversation reads them; each (head, revision) or None."""
    from .scene_links import relationship_target
    target = relationship_target(store.config, store.db, scene, person_id)
    here = store.head(target['entity'], target['scope'])
    person = store.head(person_entity(store.config, store.db, person_id), PERSON_SCOPE)
    return person, here


def line(pair):
    """Her line for a layer: its short, or its body while it has none (written before shorts); None when unwritten."""
    content = (pair[1].get('content') or {}) if pair else {}
    return content.get('short') or content.get('body') or None


def pins(person, here):
    """The revisions a view showed, for the write rule: {'person': id or None, 'here': id or None}."""
    return {'person': person[0]['revision_id'] if person else None, 'here': here[0]['revision_id'] if here else None}


def _written_at(person, here):
    times = [((person or [None, {}])[1].get('origin') or {}).get('at'), (here or [None, {}])[1].get('created_at')]
    times = [t for t in times if isinstance(t, str) and t]
    return max(times) if times else None


def entry(store, scene, person_id, persona, people, ledger=None):
    """One person as a group turn shows them: label, familiarity and stance (as every turn did), her shorts when she
    has written them. Every field is the same from turn to turn until something changes, so delivery folds it."""
    from .familiarity import words
    person, here = layers(store, scene, person_id)
    item = {'who': people.speaker(scene, person_id), **words(store, person_id, persona)}
    for key, pair in (('short', person), ('here', here)):
        content = (pair[1].get('content') or {}) if pair else {}
        if content.get('short'):
            item[key] = content['short']
        elif content.get('body'):            # written before shorts: the body, named as one (ADR-082 D4)
            item[key + '_body'] = content['body']
    written = _written_at(person, here) if (person or here) else None
    if written:
        item['written_at'] = written
    # ADR-086 D1: her live feelings toward this person (a group entry is public: the feeling and how long ago).
    from . import visibility
    if ledger is None:
        from .affect import AffectLedger
        from .render import model_and_policy
        ledger = AffectLedger(store, persona, *model_and_policy(store, persona))
    felt = ledger.person_feelings(person_id, visibility.PUBLIC)
    if felt:
        item['feelings_toward'] = felt
    return item, pins(person, here)


def group_people(store, scene, event, persona, source):
    """people_from_program for a group turn: the person who started it, then whoever's @ or reply to her waits behind
    it in this scene's queue (at most ENTRY_MAX); and what each item showed ({person_id: pins})."""
    from .people import People
    people = People(store, persona)
    ids = [event['person_id']]
    if source:
        for row in store.db.messages.find({'scene_id': scene['_id'], 'direction': 'inbound',
                                           'scene_seq': {'$gt': source['scene_seq']},
                                           'event.group_context.wake_reason': {'$in': list(EXPLICIT)}},
                                          {'author': 1}).sort('scene_seq', 1).limit(ENTRY_MAX * 4):
            if row.get('author') and row['author'] not in ids:
                ids.append(row['author'])
    from .affect import AffectLedger
    from .render import model_and_policy
    ledger = AffectLedger(store, persona, *model_and_policy(store, persona))     # once for every entry of the turn
    items, shown = [], {}
    for person_id in ids[:ENTRY_MAX]:
        if person_id == people.self_id:
            continue
        item, showed = entry(store, scene, person_id, persona, people, ledger)
        items.append(item)
        shown[person_id] = showed
    return items, shown


def read(store, scene, person_id, moment=None):
    """What `recall`'s `person` returns: the person layer as she reads it (with its short), this conversation's here
    layer, and the revisions shown."""
    person, here = layers(store, scene, person_id)
    view = person_view(store, person_id, scene.get('scope_key'), person, moment)
    if person and (person[1].get('content') or {}).get('short'):
        view['short'] = person[1]['content']['short']
    here_view = {'text': ((here[1].get('content') or {}).get('body') if here else None) or NO_HERE}
    if here and (here[1].get('content') or {}).get('short'):
        here_view['short'] = here[1]['content']['short']
    return {'person': view, 'here': here_view}, pins(person, here)


def _name(store, people, person):
    from .people import safe_name
    from .peer_context import speaker_name
    if people.named(person):
        return people.named(person)
    seen = store.db.scene_people.find_one({'person': person}, {'card': 1, 'nickname': 1}, sort=[('seen_at', -1)])
    return (safe_name((seen or {}).get('card')) or safe_name((seen or {}).get('nickname'))
            or speaker_name(store.config, person, None, store.db))


def listing(store, persona):
    """「名单」 (home only): everyone she has written, each layer with its length, where and when it was last written;
    newest first. [{'name', 'person', 'layers': [...]}]"""
    from .people import People
    people = People(store, persona)
    heads = list(store.db.state_heads.find({'_id': {'$regex': '^relationship:'}}))
    revisions = {row['_id']: row for row in store.db.state_revisions.find(
        {'_id': {'$in': [h['revision_id'] for h in heads]}}, {'content': 1, 'created_at': 1, 'origin': 1})}
    found = {}
    for head in heads:
        entity, scope = head['_id'].rsplit('|', 1)
        person = entity.split(':', 1)[1]
        revision = revisions.get(head['revision_id']) or {}
        body = (revision.get('content') or {}).get('body') or ''
        if scope == PERSON_SCOPE:
            origin = revision.get('origin') or {}
            where = store.db.scenes.find_one({'_id': origin.get('scene_id')}) if origin.get('scene_id') else None
            layer = {'layer': '人那层', 'chars': len(body),
                     'written_in': people.scene_title(where) if where else '一个现在已经没有的对话',
                     'written_at': origin.get('at') or revision.get('created_at')}
        else:
            where = store.db.scenes.find_one({'scope_key': scope})
            layer = {'layer': '这里那层：%s' % (people.scene_title(where) if where else '一个现在已经没有的对话'),
                     'chars': len(body), 'written_at': revision.get('created_at')}
        layer['short'] = (revision.get('content') or {}).get('short') or '没有'      # every row says which it is
        found.setdefault(person, []).append(layer)
    rows = [{'name': _name(store, people, person), 'person': person,
             'layers': sorted(layers_, key=lambda l: l.get('written_at') or '', reverse=True)}
            for person, layers_ in found.items()]
    return sorted(rows, key=lambda r: max((l.get('written_at') or '') for l in r['layers']), reverse=True)


class Unknown(ValueError):
    """A `person` this turn cannot take; the message lists the ones it can."""


def present(ep):
    """The people whose own lines are in this turn (the manifest's `present`, recorded at prepare while the rows still
    carry ids), and whoever its entry listed (the queue behind it)."""
    manifest = ep.get('manifest') or {}
    ids = [*(manifest.get('present') or []), *((manifest.get('people_shown') or {}).keys())]
    return [i for i in dict.fromkeys(ids) if i]


def resolve(store, ep, scene, value, persona, home=False, for_read=False):
    """The person_id `value` names in this turn, or Unknown with the labels it can take. Groups: a label (or #n, or a
    name that names one person) among the people present; one-to-one: the speaker; at home a read may also name
    anyone on 「名单」 by the name it shows."""
    from .people import People
    people = People(store, persona)
    text = ' '.join(str(value or '').split()).lstrip('@')
    if scene.get('kind') == 'group':
        here = present(ep)
        found = [d for d in people.resolve(scene, text) if (d.get('author') or d.get('person')) in here] if text else []
        if not text and ep.get('person_id') in here:
            return ep['person_id']
        if len(found) == 1:
            return found[0].get('author') or found[0]['person']
        labels = [people.speaker(scene, i) for i in here if i != people.self_id]
        raise Unknown(('「%s」指的不止一个人' % text if len(found) > 1 else '这一回合里没有「%s」' % text if text else '要写 person')
                      + '：照抄标签，这一回合能写的是 %s。' % ('、'.join(labels) or '（没有）'))
    if not text or text in (people.speaker(scene, ep['person_id']),) or people.person(text) == people.person(ep['person_id']):
        return ep['person_id']
    if home and for_read:
        rows = [r for r in listing(store, persona) if r['name'] == text]
        if len(rows) == 1:
            return rows[0]['person']
        raise Unknown('「%s」%s：照抄「名单」里的名字（recall 的 person 写「名单」看）。'
                      % (text, '指的不止一个人' if rows else '不在名单上'))
    raise Unknown('这里只有跟你说话的这个人，person 不写就是他。')
