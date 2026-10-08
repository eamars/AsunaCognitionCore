"""Her understanding of a person, in two layers (owner 2026-10-08, with her wording).

- The person layer: one record per person (`relationship:<canonical person>|person`), shown wherever she meets
  them. What she thinks holds of them anywhere.
- The here layer: one record per person and conversation (`relationship:<person>|scene:<scene>`, as before), shown
  only there. How they are in this place; someone may speak differently in one group than in another.

She chooses the layer each time she writes (`understand_person`). The program does not filter what goes where: the
note gives her three questions to ask on the spot, and the person layer always opens with the line that it is only
part of them. Each person-layer revision records where it was written; it is read with that conversation's name and
how long ago.
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
    from .config import ago
    from .people import People
    origin = revision.get('origin') or {}
    scene = store.db.scenes.find_one({'_id': origin.get('scene_id')}) if origin.get('scene_id') else None
    try:
        hours = (moment - datetime.fromisoformat(origin['at'])).total_seconds() / 3600
    except (KeyError, TypeError, ValueError):
        return None
    return '最后是在%s里改的，%s' % (People(store).scene_title(scene) if scene else '一个现在已经没有的对话', ago(max(0.0, hours)))


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
        view['written'] = written
    return view
