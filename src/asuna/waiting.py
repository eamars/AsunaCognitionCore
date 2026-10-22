"""Who she is still waiting for: her lines of the last hour in a group that called someone with an @, or asked for an
answer with `await_answer` wait=yes, whose people have not spoken there since.

Computed each time from the stored lines; nothing is kept. A person drops off the list when they speak in that
group, a line she set wait=no never counts, a plain reply does not count, and a line older than HORIZON is no
longer listed. A group turn sees that group's; a heartbeat at home sees every group's, at most SHOWN_HOME.
"""
from __future__ import annotations

from datetime import timedelta

HORIZON = timedelta(hours=1)
SHOWN_HOME = 5
EXCERPT = 30
ANYONE = '这里任何人'
NOTE = '你点过名（@ 或 wait=yes）、到现在还没在那边开口的人，一小时以内的。对方一开口就不再列；过了一小时自己消失。'


def _excerpt(text):
    from .people import BARE_LABEL, LABEL_MENTION
    plain = LABEL_MENTION.sub(lambda m: '@' + ' '.join((m.group('name') or '').split()), text or '')
    plain = ' '.join(BARE_LABEL.sub(lambda m: ' '.join((m.group('name') or '').split()), plain).split())
    return plain if len(plain) <= EXCERPT else plain[:EXCERPT] + '…'


def pending(store, scene_ids, moment, persona=None):
    """[{scene_id, person (None: anyone), doc, at, text}] newest first: who she still waits for in these groups."""
    from .config import character_id
    from .ingress import NOT_CORE_NOTICE
    from .people import LABEL_MENTION, People
    people, me, since = People(store, persona), character_id(store.config), (moment - HORIZON).isoformat()
    found = []
    for scene_id in scene_ids:
        scene = store.db.scenes.find_one({'_id': scene_id}, {'kind': 1})
        if not scene or scene.get('kind') != 'group':
            continue
        by_handle = {str(doc.get('handle')): doc for doc in people.roster(scene_id).values()
                     if doc.get('person') and doc.get('person') != people.self_id}
        settled = set()
        lines = store.db.messages.find({'scene_id': scene_id, 'direction': 'outbound', 'delivery_state': 'DELIVERED',
                                        'author': me, 'receipt_at': {'$gte': since}},
                                       {'text': 1, 'episode_id': 1, 'scene_seq': 1, 'receipt_at': 1}).sort('scene_seq', -1)
        for line in lines:
            choice = (store.db.episodes.find_one({'_id': line.get('episode_id')}, {'await_answer': 1}) or {}).get(
                'await_answer') or {}
            if choice.get('off'):
                continue
            called = {}
            for match in LABEL_MENTION.finditer(line.get('text') or ''):
                doc = by_handle.get(match.group('handle') or match.group('bare'))
                if doc:
                    called[people.person(doc['person'])] = doc
            if not called and not choice.get('why'):
                continue
            for person, doc in (called.items() if called else [(None, None)]):
                if person in settled:
                    continue                    # a newer line to them is already listed, or they answered it
                settled.add(person)
                after = {'scene_id': scene_id, 'direction': 'inbound', 'scene_seq': {'$gt': line.get('scene_seq') or 0},
                         **NOT_CORE_NOTICE}         # a task result or a due plan answers nobody's wait
                if person is not None:
                    after['author'] = {'$in': people.authors_of(person, [scene_id]) or [person]}
                if not store.db.messages.find_one(after, {'_id': 1}):
                    found.append({'scene_id': scene_id, 'person': person, 'doc': doc, 'at': line.get('receipt_at'),
                                  'text': line.get('text') or ''})
    return sorted(found, key=lambda item: str(item['at']), reverse=True)


def block(store, scene_ids, moment, persona=None, *, home=False):
    """waiting_from_program: who she still waits for, in words; None when nobody."""
    from .people import People
    from . import places
    items = pending(store, scene_ids, moment, persona)
    if not items:
        return None
    people, shown = People(store, persona), []
    for item in items[:SHOWN_HOME] if home else items:
        row = {'who': people.label(item['doc']) if item['doc'] else ANYONE, 'waiting_since_at': item['at'],
               'waiting_on_you': True,
               'your_line': _excerpt(item['text'])}
        if home:
            scene = store.db.scenes.find_one({'_id': item['scene_id']}) or {'_id': item['scene_id']}
            row = {'place': places.place_id(item['scene_id']), 'group': people.scene_title(scene), **row}
        shown.append(row)
    result = {'items': shown, 'note': NOTE}
    if home and len(items) > SHOWN_HOME:
        result['more'] = '还有 %d 个，没列出来' % (len(items) - SHOWN_HOME)
    return result
