"""Her sticker shelf and the platform's own faces (ADR-016).

A sticker is a picture someone sent *as a sticker* (still or animated), or a store sticker; a photo is not
one. Where the platform marks stickers (channel_kinds: the adapter's media item, or the kind's
``sticker_of``), she may keep one on her shelf by its ref, under a name of her own and a note on when it
fits; a picture she made herself may go on the shelf too. Only stickers can be kept, never photos.

- Keeping a custom sticker stores its bytes once (``global-safe``: a sticker is public meme content, not
  anyone's private picture); a store sticker keeps the ids the platform needs to send it again.
- In a conversation whose platform sends stickers, ``[表情包:名字]`` in what she says goes out as that
  sticker, as a message of its own; one per turn. ``[表情:名字]`` is one of the platform's own faces, inside
  the text; the adapter turns a known name into the real face.
- The shelf holds STICKER_SHELF; her turn lists names and notes only. Rotating is hers: a weekly look in
  the nightly settlement lists the ones she has not used, and she drops what she no longer wants. The
  program never drops one for her.
- A sticker she kept or looked at and named stays known (``sticker_memory``): posted again, its line says
  what she called it, so she need not look again. It is known by the file's md5 (which the platform may give
  without a download) and by its picture (``picture_key``: the image data without metadata), so a copy
  re-sent with rewritten metadata is still hers; keeping the same picture twice is refused.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re

from . import channel_kinds
from .context_budget import ROUGH_AGO, STICKER_REVIEW, STICKER_SHELF, _tier
from .evidence import sha
from .state import Denied, now

TOKEN = re.compile(r'\[表情包:([^\[\]\n]{1,12})\]')
FACE_TOKEN = re.compile(r'\[表情:([^\[\]\s:]{1,12})\]')
NAME_CHARS = 12
WHEN_CHARS = 40
SCOPE = 'global-safe'
SOURCE = 'sticker:'                         # artifact source of a kept sticker's bytes
REVIEW_EVERY_DAYS = 7
UNUSED_DAYS = 14                            # kept this long and never sent: worth a look
FACES_SHOWN = 8
FACE_SCAN = 300

SHELF_WORDS = ((0.5, '宽裕'), (0.8, '用了一大半'), (1.0, '快满了'), (None, '满了'))
USE_WORDS = ((1, '还没发过'), (3, '发过一两次'), (8, '发过几次'), (None, '常发'))
ORIGIN_WORDS = {'own': '你自己画的', 'collected': '群里收来的'}

STICKERS_NOTE = ('这是你收着的表情包（只有名字和你写的用法）。在这里想发哪个，就在要说的话里单独写一行'
                 '「[表情包:名字]」，它会作为单独一条发出去，一回合最多一个；不想发就不用。'
                 '群里别人发的表情包下面会标「（表情包 ref：att-…）」，喜欢的可以用 sticker 的 keep 收下，'
                 '起个你记得住的名字、写一句什么时候用；只有表情包能收，照片不行。架子有上限，满了先 drop 一个。'
                 '你认得的表情包（收过的、看过记下的）下面会直接标你给它起的名字。')
HOME_NOTE = ('这是你收着的表情包。这里发不出去；想整理就用 sticker（drop 放下、rename 改名或改用法），'
             '你自己画的图也可以用 keep 放上来，在群里就能当表情包发。带图的那些标着 ref，想重看一眼就 read_image（ref 照抄）。')
FACES_NOTE = ('%s 自己的小黄脸写「[表情:名字]」，夹在话里就行，会变成真的表情；名字要用 %s 的'
              '（下面是这里最近有人用过的，别处见过的也行），不认识的名字会被退回。')
REVIEW_NOTE = ('这是你的表情包架子，每周看一眼。下面是收了以后一直没发、或很久没发的几个：'
               '还喜欢的留着，不想要的用 sticker 的 drop 放下，名字或用法不顺手的用 rename 改。'
               '留什么由你，程序不替你扔。')


def shelf(store, persona):
    return list(store.db.stickers.find({'persona': persona}).sort('name', 1))


def find(store, persona, name):
    return store.db.stickers.find_one({'persona': persona, 'name': name})


def _hours(moment, when):
    try:
        return (moment - datetime.fromisoformat(when)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _name(value, what='name'):
    text = ' '.join(str(value or '').split())
    if not 1 <= len(text) <= NAME_CHARS or re.search(r'[\[\]:]', text):
        raise Denied('STICKER_NAME_INVALID: %s 是 1–%d 个字，不含 [ ] :；%s' % (
            what, NAME_CHARS, '给的「%s」%d 个字' % (text[:20], len(text)) if text else '没写 ' + what))
    return text


def _when(value):
    text = ' '.join(str(value or '').split())
    if not 1 <= len(text) <= WHEN_CHARS:
        raise Denied('STICKER_WHEN_INVALID: when 是 1–%d 个字；%s' % (
            WHEN_CHARS, '给的 %d 个字，写短一点' % len(text) if text else '没写 when'))
    return text


ALREADY_KEPT = 'STICKER_ALREADY_KEPT: 在架子上叫「%s」；想改名字或用法用 rename'
CANDIDATE_GONE = 'STICKER_CANDIDATE_GONE: 「%s」；照抄 sticker_candidates_from_program 里现在还在的 candidate'


def _ref_problem(ref):
    return '「%s」' % ref if ref else '没写 ref（也没写 candidate）；想从候选池里收，先用 op=pool 看池子'


def fullness(count):
    return _tier(SHELF_WORDS, count / STICKER_SHELF)


# ── keeping, dropping, renaming ─────────────────────────────────────
def keep(store, blobs, ep, persona, args, config):
    """Put a sticker on her shelf: an att- ref of a sticker in this conversation, or a blob- id of a picture
    she made herself."""
    from .outbound_media import produced, sniff_media_type
    from .vision import ARTIFACT_REF, media_source_url, pull_bytes, scene_attachments
    name, when = _name(args.get('name')), _when(args.get('when'))
    ref = str(args.get('ref') or '').strip()
    if store.db.stickers.count_documents({'persona': persona}) >= STICKER_SHELF:
        raise Denied('STICKER_SHELF_FULL: 上限 %d 个' % STICKER_SHELF)
    if find(store, persona, name):
        raise Denied('STICKER_NAME_TAKEN: ' + name)
    doc = {'persona': persona, 'name': name, 'when': when, 'kept_at': now(), 'kept_in': ep['scene_id'],
           'sent': 0, 'last_sent_at': None}
    if ARTIFACT_REF.fullmatch(ref):
        row = store.db.artifacts.find_one({'_id': ref, 'kind': 'image', 'state': 'DONE', 'storage': 'gridfs'})
        if not row or not produced(row):
            raise Denied('STICKER_NOT_YOURS: 「%s」不是你自己画好的图' % ref)
        doc.update(origin='own', kind='custom', artifact_id=ref, sha256=row['sha256'], size=row['size'],
                   media_type=row.get('media_type'), identity='sha:' + row['sha256'],
                   picture=_picture_of(store, ref))
    else:
        scene = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
        listing = scene_attachments(store, scene, config)
        entry = next((item for item in listing['attachments'] if item['ref'] == ref), None)
        if not entry:
            raise Denied('STICKER_REF_NOT_HERE: ' + _ref_problem(ref))
        if not entry.get('sticker'):
            raise Denied('STICKER_IS_A_PHOTO: 「%s」' % ref)
        doc['origin'] = 'collected'
        if entry['sticker'] == 'market':
            doc.update(kind='market', market={**entry['market'], 'summary': entry.get('summary') or '[商城表情]'},
                       identity='market:' + entry['market']['emoji_id'])
        else:
            if not entry.get('pullable'):
                raise Denied('STICKER_NOT_REACHABLE: %s；重试也一样' % (entry.get('not_pullable_because') or '「%s」' % ref))
            data, media_type, _, _ = pull_bytes({**entry, 'url': media_source_url(store, scene, config, entry)}, config)
            stored = blobs.put_once(data, SCOPE, 'image', source_ids=[SOURCE + entry['source_message_id']])
            doc.update(kind='custom', artifact_id=stored['artifact_id'], sha256=stored['sha256'], size=stored['size'],
                       media_type=media_type or sniff_media_type(data), identity='sha:' + stored['sha256'],
                       md5=hashlib.md5(data).hexdigest().upper(), picture=picture_key(data))
    same = store.db.stickers.find_one({'persona': persona, '$or': [{'identity': doc['identity']},
                                       *([{'picture': doc['picture']}] if doc.get('picture') else [])]})
    if same:
        raise Denied(ALREADY_KEPT % same['name'])
    doc['_id'] = 'stk-' + sha((persona + '|' + doc['identity']).encode())[:20]
    store.put('stickers', doc, stream='stickers:' + persona)
    _kept(store, persona, doc)
    store.db.sticker_pool.delete_many({'identity': doc['identity']})
    count = store.db.stickers.count_documents({'persona': persona})
    return {'kept': name, 'shelf': '%d 个，%s' % (count, fullness(count))}


def drop(store, persona, name):
    row = find(store, persona, _name(name))
    if not row:
        raise Denied('STICKER_NOT_ON_SHELF: 「%s」' % name)
    store.db.stickers.delete_one({'_id': row['_id'], 'revision': row['revision']})
    store.audit('stickers:' + persona, 'sticker.dropped', {'name': row['name'], 'identity': row['identity']})
    return {'dropped': row['name']}


def rename(store, persona, name, new_name=None, when=None):
    row = find(store, persona, _name(name))
    if not row:
        raise Denied('STICKER_NOT_ON_SHELF: 「%s」' % name)
    changes = {}
    if new_name:
        new_name = _name(new_name, 'new_name')
        if new_name != row['name'] and find(store, persona, new_name):
            raise Denied('STICKER_NAME_TAKEN: ' + new_name)
        changes['name'] = new_name
    if when:
        changes['when'] = _when(when)
    if not changes:
        raise Denied('STICKER_NOTHING_TO_CHANGE')
    store.put('stickers', {**row, **changes}, expected=row['revision'], stream='stickers:' + persona)
    _kept(store, persona, {**row, **changes})
    return {'renamed': row['name'], **changes}


# ── what her turn sees ──────────────────────────────────────────────
def sends(scene):
    """Whether what she says in this conversation can carry stickers and faces."""
    return bool((scene or {}).get('channel_id')) and channel_kinds.sends_stickers(scene['_id'])


def block(store, persona, scene, *, at_home=False):
    """stickers_from_program: the shelf by name, in a conversation that sends stickers or at home."""
    rows = shelf(store, persona)
    if at_home and not rows:
        return None
    # At home, where she tidies it, a sticker with a picture carries its id so she can look at it again (her ask
    # 2026-10-10: animated ones were named from their first frame only).
    return {'items': [{'sticker': row['name'], 'when': row['when'], 'used': _tier(USE_WORDS, row.get('sent') or 0),
                       **({'from': ORIGIN_WORDS['own']} if row.get('origin') == 'own' else {}),
                       **({'ref': row['artifact_id']} if at_home and row.get('artifact_id') else {})} for row in rows],
            'shelf': '%d 个，%s' % (len(rows), fullness(len(rows))),
            'note': HOME_NOTE if at_home else STICKERS_NOTE}


def _title(scene):
    return getattr(channel_kinds.of(scene['_id']), 'TITLE', '这个平台')


def faces_block(store, scene):
    """faces_from_program: the platform faces people here used lately, by name."""
    names = channel_kinds.faces_of(scene['_id'])
    if not names:
        return None
    counts = {}
    for row in store.db.messages.find({'scene_id': scene['_id'], 'direction': 'inbound'}, {'text': 1}) \
            .sort('scene_seq', -1).limit(FACE_SCAN):
        for found in FACE_TOKEN.findall(row.get('text') or ''):
            if found in names:
                counts[found] = counts.get(found, 0) + 1
    seen = sorted(counts, key=lambda item: -counts[item])[:FACES_SHOWN]
    return {'seen_here': seen or '这里最近没人用过', 'note': FACES_NOTE % ((_title(scene),) * 2)}


def speech_problem(store, ep, speech):
    """What is wrong with the stickers and faces in what she is about to say; None when they can go."""
    stickers = TOKEN.findall(speech or '')
    faces = FACE_TOKEN.findall(speech or '')
    if not stickers and not faces:
        return None
    scene = store.db.scenes.find_one({'_id': ep['scene_id']}, {'_id': 1, 'channel_id': 1})
    if not sends(scene):
        return '这里发不出表情包或小黄脸：把「[表情包:…]」「[表情:…]」去掉，用话说。'
    if len(stickers) > 1:
        return '一回合最多发一个表情包，你写了 %d 个：留一个。' % len(stickers)
    for name in stickers:
        if not find(store, ep['persona'], name):
            return '架子上没有叫「%s」的表情包：照抄 stickers_from_program 里的名字，或者不发。' % name
    known = channel_kinds.faces_of(scene['_id'])
    unknown = [name for name in faces if name not in known]
    if unknown:
        return '「%s」不是 %s 的小黄脸名字：换成认识的名字，或者去掉。' % ('、'.join(dict.fromkeys(unknown)),
                                                           _title(scene))
    return None


def split(segments):
    """Each sticker token leaves as a message of its own, in the order she wrote it."""
    out = []
    for segment in segments:
        pos = 0
        for match in TOKEN.finditer(segment):
            before = segment[pos:match.start()].strip()
            if before:
                out.append(before)
            out.append(match.group(0))
            pos = match.end()
        tail = segment[pos:].strip()
        if tail:
            out.append(tail)
    return out or segments


def outbound(store, persona, segment):
    """The row fields of a message that is one sticker token: what the channel sends; None for words."""
    from .outbound_media import descriptor
    match = TOKEN.fullmatch(segment.strip())
    row = match and find(store, persona, match.group(1))
    if not row:
        return None
    if row['kind'] == 'market':
        return {'sticker': {'kind': 'market', 'name': row['name'], **row['market']}}
    attachment = descriptor({'attachment': {'artifact_id': row['artifact_id'], 'media_type': row.get('media_type'),
                                            'sha256': row['sha256'], 'size': row.get('size')}})
    if not attachment:
        return None
    return {'sticker': {'kind': 'custom', 'name': row['name']}, 'attachment': attachment}


def sent(store, persona, name, scene_id):
    row = find(store, persona, name)
    if row:
        store.put('stickers', {**row, 'sent': (row.get('sent') or 0) + 1, 'last_sent_at': now(),
                               'last_sent_in': scene_id}, expected=row['revision'], stream='stickers:' + persona)


def on_shelf(store, artifact_id):
    """A kept sticker's picture: it may go to any conversation that takes stickers (outbound_media.serve)."""
    return bool(store.db.stickers.find_one({'artifact_id': artifact_id}, {'_id': 1}))


def review_block(store, persona, moment):
    """stickers_review_from_program: once a week, the stickers she kept and has not been sending."""
    rows = shelf(store, persona)
    if not rows:
        return None
    last = store.db.audit_events.find_one({'stream_id': 'stickers:' + persona, 'type': 'sticker.review_offered'},
                                          sort=[('occurred_at', -1)])
    since = _hours(moment, (last or {}).get('occurred_at'))
    full = len(rows) >= STICKER_SHELF * 0.8
    if since is not None and since < REVIEW_EVERY_DAYS * 24 and not full:
        return None
    idle = []
    for row in rows:
        kept = _hours(moment, row.get('kept_at')) or 0
        last_sent = _hours(moment, row.get('last_sent_at'))
        if not row.get('sent') and kept >= UNUSED_DAYS * 24:
            idle.append((0, -kept, row, '收了以后还没发过'))
        elif last_sent is not None and last_sent >= UNUSED_DAYS * 24:
            idle.append((1, -last_sent, row, '上次发是' + _tier(ROUGH_AGO, last_sent)))
    if not idle and not full:
        return None
    if not idle:
        # full, and every one is in use: the least sent are the ones to weigh
        idle = [(0, row.get('sent') or 0, row, _tier(USE_WORDS, row.get('sent') or 0))
                for row in sorted(rows, key=lambda row: row.get('sent') or 0)]
    idle.sort(key=lambda item: item[:2])
    store.audit('stickers:' + persona, 'sticker.review_offered', {'listed': len(idle[:STICKER_REVIEW])})
    return {'shelf': '%d 个，%s' % (len(rows), fullness(len(rows))),
            'items': [{'sticker': row['name'], 'when': row['when'], 'why': why} for _, _, row, why in idle[:STICKER_REVIEW]],
            'note': REVIEW_NOTE}


# ── the candidate pool (owner 2026-10-06) ───────────────────────────
# Stickers people post in her groups are saved as they arrive (platform links expire within hours) into a pool
# of candidates. Nothing goes on her shelf by itself: she looks at a candidate (read_image) and keeps it with a
# name and a note of her own. Past POOL_MAX the least recently seen leave; one that keeps being posted stays.
POOL_MAX = 30
POOL_SHOWN = 8                  # nightly: the most posted first
POOL_SHOWN_HERE = 4             # in a group's turn: posted there lately
POOL_HERE_HOURS = 2
POOL_SOURCE = 'sticker-pool:'
SEEN_WORDS = ((2, '一次'), (4, '几次'), (10, '好些次'), (None, '很多次'))
POOL_NOTE = ('这些是群里有人发过的表情包，程序先替你存着（池子最多 %d 个，很久没人发的会被挤掉）。'
             '想收哪个：先用 read_image 看（ref 照抄 candidate），看过了用 sticker 的 keep（candidate 照抄，'
             '起个名字、写一句什么时候用）；没看过的收不了。不想要的不用管。' % POOL_MAX)


def pool_seen(store, blobs, config, message_id):
    """A group message's stickers join the pool (bytes saved now); returns how many new candidates."""
    from .state import Conflict
    from .vision import attachments_of, media_source_url, pull_bytes
    row = store.db.messages.find_one({'_id': message_id})
    if not row or row.get('direction') != 'inbound':
        return 0
    scene = store.db.scenes.find_one({'_id': row['scene_id']})
    if not scene or scene.get('kind') != 'group':
        return 0
    task = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    added = 0
    for entry in attachments_of(row, config=config):
        if not entry.get('sticker') or not entry.get('pullable'):
            continue
        fingerprint = memory_key(entry)
        if fingerprint and store.db.sticker_memory.find_one(_by_key(fingerprint), {'_id': 1}):
            continue                                   # she knows it already: kept once, or looked and let go
        try:
            data, media_type, _, _ = pull_bytes({**entry, 'url': media_source_url(store, task, config, entry)}, config)
        except Exception:
            continue                                   # gone already: nothing to save
        stored = blobs.put_once(data, SCOPE, 'image', source_ids=[POOL_SOURCE + message_id])
        identity = ('market:' + entry['market']['emoji_id'] if entry['sticker'] == 'market'
                    else 'sha:' + stored['sha256'])
        md5 = hashlib.md5(data).hexdigest().upper()
        if store.db.stickers.find_one({'identity': identity}, {'_id': 1}):
            continue                                   # already on her shelf
        picture = picture_key(data)
        if store.db.sticker_memory.find_one({'$or': [_by_key('md5:' + md5), {'picture': picture}]}, {'_id': 1}):
            continue                                   # known by its bytes or its picture, though named otherwise
        at = row.get('received_at') or now()
        key = 'cand-' + sha(identity.encode())[:16]
        current = store.db.sticker_pool.find_one({'_id': key})
        try:
            if current:
                store.put('sticker_pool', {**current, 'seen': current['seen'] + 1, 'last_seen': at,
                                           'scenes': list(dict.fromkeys([*current['scenes'], scene['_id']]))[-5:]},
                          expected=current['revision'], stream='sticker-pool')
            else:
                doc = {'_id': key, 'identity': identity, 'kind': entry['sticker'], 'artifact_id': stored['artifact_id'],
                       'sha256': stored['sha256'], 'md5': md5, 'picture': picture, 'size': stored['size'],
                       'media_type': media_type,
                       'first_seen': at, 'last_seen': at, 'seen': 1, 'scenes': [scene['_id']],
                       'source_message_id': message_id}
                if entry['sticker'] == 'market':
                    doc['market'] = {**entry['market'], 'summary': entry.get('summary') or '[商城表情]'}
                store.put('sticker_pool', doc, stream='sticker-pool')
                added += 1
        except Conflict:
            continue                                   # the same sticker, counted by a concurrent arrival
    rotate(store)
    return added


def rotate(store):
    """Past POOL_MAX, the least recently seen candidates leave the pool."""
    extra = store.db.sticker_pool.count_documents({}) - POOL_MAX
    if extra > 0:
        for doc in list(store.db.sticker_pool.find({}, {'identity': 1, 'revision': 1}).sort('last_seen', 1).limit(extra)):
            store.db.sticker_pool.delete_one({'_id': doc['_id'], 'revision': doc['revision']})
            store.audit('sticker-pool', 'sticker.pool.rotated', {'identity': doc['identity']})


def candidates_block(store, moment, scene_id=None):
    """sticker_candidates_from_program: nightly the most posted; in a group's turn, the ones posted there lately."""
    from datetime import timedelta
    from .people import People
    query, limit = {}, POOL_SHOWN
    if scene_id:
        query = {'scenes': scene_id, 'last_seen': {'$gte': (moment - timedelta(hours=POOL_HERE_HOURS)).isoformat()}}
        limit = POOL_SHOWN_HERE
    rows = list(store.db.sticker_pool.find(query).sort([('seen', -1), ('last_seen', -1)]).limit(limit))
    if not rows:
        return None
    people = People(store)
    items = []
    for row in rows:
        where = '、'.join(people.scene_title(store.db.scenes.find_one({'_id': s}) or {'_id': s}) for s in row['scenes'][-2:])
        hours = _hours(moment, row['last_seen'])
        items.append({'candidate': row['artifact_id'], 'seen': '%s见过%s' % (where, _tier(SEEN_WORDS, row['seen'])),
                      **({'last': _tier(ROUGH_AGO, hours)} if hours is not None else {})})
    return {'items': items, 'pool': '池子里 %d 个' % store.db.sticker_pool.count_documents({}), 'note': POOL_NOTE}


def pool_listing(store, moment):
    """sticker op=pool: the candidate pool when she asks, anywhere her shelf is -- the list the nightly round shows."""
    return candidates_block(store, moment) or {'items': [], 'pool': '池子里 0 个',
                                               'note': '池子现在是空的：群里有人发表情包，程序会先替你存着。'}


def candidate_ids(context, listed=()):
    """The sticker pictures listed this turn -- candidates (in her context, or by op=pool) and, at home, her shelf:
    she may look at them with read_image."""
    items = ((context or {}).get('sticker_candidates_from_program') or {}).get('items') or ()
    shelf = ((context or {}).get('stickers_from_program') or {}).get('items') or ()
    return tuple(item['candidate'] for item in items if isinstance(item, dict) and item.get('candidate'))         + tuple(item['ref'] for item in shelf if isinstance(item, dict) and item.get('ref')) + tuple(listed or ())


def keep_candidate(store, ep, persona, args):
    """A candidate from the pool goes on her shelf -- only one she looked at in this turn (read_image)."""
    name, when = _name(args.get('name')), _when(args.get('when'))
    candidate = str(args.get('candidate') or '').strip()
    row = store.db.sticker_pool.find_one({'artifact_id': candidate})
    if not row:
        raise Denied(CANDIDATE_GONE % candidate)
    if candidate not in (ep.get('looked') or []) and not known(store, persona, _pool_key(store, row)):
        raise Denied('STICKER_CANDIDATE_NOT_LOOKED')       # one she knows from before counts as looked
    if store.db.stickers.count_documents({'persona': persona}) >= STICKER_SHELF:
        raise Denied('STICKER_SHELF_FULL: 上限 %d 个' % STICKER_SHELF)
    if find(store, persona, name):
        raise Denied('STICKER_NAME_TAKEN: ' + name)
    same = store.db.stickers.find_one({'persona': persona, '$or': [{'identity': row['identity']},
                                       *([{'picture': row['picture']}] if row.get('picture') else [])]})
    if same:
        raise Denied(ALREADY_KEPT % same['name'])
    doc = {'_id': 'stk-' + sha((persona + '|' + row['identity']).encode())[:20], 'persona': persona, 'name': name,
           'when': when, 'kept_at': now(), 'kept_in': ep['scene_id'], 'sent': 0, 'last_sent_at': None,
           'origin': 'collected', 'kind': row['kind'], 'identity': row['identity']}
    if row['kind'] == 'market':
        doc['market'] = row['market']
    else:
        doc.update(artifact_id=row['artifact_id'], sha256=row['sha256'], size=row['size'], media_type=row.get('media_type'),
                   md5=row.get('md5') or _md5_of(store, row['artifact_id']),
                   picture=row.get('picture') or _picture_of(store, row['artifact_id']))
    store.put('stickers', doc, stream='stickers:' + persona)
    _kept(store, persona, doc)
    store.db.sticker_pool.delete_one({'_id': row['_id']})
    count = store.db.stickers.count_documents({'persona': persona})
    return {'kept': name, 'shelf': '%d 个，%s' % (count, fullness(count))}


# ── the stickers she knows (owner 2026-10-06) ───────────────────────
# A sticker she looked at and named stays known for good, by a fingerprint: the md5 of a picture's bytes (a
# platform may name the file by it, channel_kinds.sticker_md5) or a store sticker's ids, and by its picture
# (picture_key). When it is posted again, the line under it says what she called it, so she need not look
# again: the file md5 needs no download; a copy whose md5 is unknown is downloaded once by the program and
# matched by its picture, and that md5 is then known too (aliases). The words are only hers: a sticker on her
# shelf is known by its name and note (and stays known after she drops it); one she looked at and does not want
# to send she may remember with a name and a line of her own.
MEMORY_WORDS = {'kept': '在你架子上', 'dropped': '你收过又放下了', 'looked': '你看过没收'}
PICTURE_FETCH_SECONDS = 5
_JPEG_METADATA = set(range(0xE0, 0xF0)) | {0xFE}          # APP0-APP15 (JFIF, EXIF, XMP, ICC...) and comments
_PNG_METADATA = {b'tEXt', b'zTXt', b'iTXt', b'tIME', b'eXIf', b'pHYs'}
_WEBP_METADATA = {b'EXIF', b'XMP ', b'VP8X'}


def _jpeg_image(data):
    out, index = [], 2
    while index + 4 <= len(data) and data[index] == 0xFF:
        marker = data[index + 1]
        if marker == 0xDA:                                 # start of scan: the rest is image data
            out.append(data[index:])
            return b''.join(out)
        length = int.from_bytes(data[index + 2:index + 4], 'big')
        if marker not in _JPEG_METADATA:
            out.append(data[index:index + 2 + length])
        index += 2 + length
    return None


def _chunks_without(data, start, metadata, *, size_first):
    out, index = [], start
    while index + 8 <= len(data):
        if size_first:                                     # PNG: length, type, data, crc
            length, kind = int.from_bytes(data[index:index + 4], 'big'), data[index + 4:index + 8]
            end = index + 12 + length
        else:                                              # RIFF: type, length, data (padded to even)
            kind, length = data[index:index + 4], int.from_bytes(data[index + 4:index + 8], 'little')
            end = index + 8 + length + (length & 1)
        if end > len(data):
            return None
        if kind not in metadata:
            out.append(data[index:end])
        index = end
    return b''.join(out) if index == len(data) else None


def picture_key(data):
    """The picture's fingerprint: its image data without metadata (EXIF, XMP, text and time chunks), so a copy
    whose metadata was rewritten on the way is the same picture. Other formats, or bytes that do not parse,
    use all of their bytes."""
    image = None
    if data[:3] == b'\xff\xd8\xff':
        image = _jpeg_image(data)
    elif data[:8] == b'\x89PNG\r\n\x1a\n':
        image = _chunks_without(data, 8, _PNG_METADATA, size_first=True)
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        image = _chunks_without(data, 12, _WEBP_METADATA, size_first=False)
    return 'img:' + hashlib.sha256(image or data).hexdigest()


def _blob(store, artifact_id):
    from .blobs import BlobStore
    row = store.db.artifacts.find_one({'_id': artifact_id}, {'scope_key': 1})
    return BlobStore(store).get(artifact_id, row['scope_key'], operator=True) if row else None


def memory_key(entry):
    """The fingerprint a posted sticker is known by; None when the platform gives none."""
    if entry.get('sticker') == 'market':
        emoji = (entry.get('market') or {}).get('emoji_id')
        return 'market:' + emoji if emoji else None
    md5 = channel_kinds.sticker_md5(entry)
    return 'md5:' + md5 if md5 else None


def _md5_of(store, artifact_id):
    data = _blob(store, artifact_id)
    return hashlib.md5(data).hexdigest().upper() if data is not None else None


def _picture_of(store, artifact_id):
    data = _blob(store, artifact_id)
    return picture_key(data) if data is not None else None


def _by_key(key):
    return {'$or': [{'key': key}, {'aliases': key}]}


def _shelf_key(store, doc):
    if doc.get('kind') == 'market':
        return 'market:' + doc['market']['emoji_id']
    md5 = doc.get('md5') or _md5_of(store, doc['artifact_id'])
    return 'md5:' + md5 if md5 else None


def _know(store, persona, key, name, note, how, identity=None, picture=None):
    """Write what she knows of one sticker (a new look replaces the old words)."""
    _id = 'skm-' + sha((persona + '|' + key).encode())[:20]
    current = store.db.sticker_memory.find_one({'_id': _id})
    doc = {**(current or {}), '_id': _id, 'persona': persona, 'key': key, 'name': name, 'note': note, 'how': how,
           'identity': identity or (current or {}).get('identity'),
           'picture': picture or (current or {}).get('picture'), 'at': now()}
    return store.put('sticker_memory', doc, expected=current and current['revision'], stream='sticker-memory:' + persona)


def _shelf_picture(store, doc):
    """A custom shelf sticker's picture fingerprint, worked out once from its bytes and kept on its shelf row."""
    if doc.get('kind') == 'market' or doc.get('picture'):
        return doc.get('picture')
    from .state import Conflict
    picture = _picture_of(store, doc['artifact_id'])
    if picture and doc.get('revision'):
        try:
            store.put('stickers', {**doc, 'picture': picture}, expected=doc['revision'], stream='stickers:' + doc['persona'])
        except Conflict:
            pass                                           # changed meanwhile: worked out again next start
    return picture


def remember_shelf(store, persona):
    """Every sticker on her shelf is known, by its md5 and its picture (startup: the shelf as it is now)."""
    count = 0
    for doc in shelf(store, persona):
        key = _shelf_key(store, doc)
        if not key:
            continue
        picture = _shelf_picture(store, doc)
        row = store.db.sticker_memory.find_one({'persona': persona, 'key': key}, {'picture': 1})
        if not row or (picture and row.get('picture') != picture):
            _know(store, persona, key, doc['name'], doc['when'], 'kept', doc['identity'], picture)
            count += 1
    return count


def _kept(store, persona, doc):
    key = _shelf_key(store, doc)
    if key:
        _know(store, persona, key, doc['name'], doc['when'], 'kept', doc['identity'], _shelf_picture(store, doc))


def _pool_key(store, row):
    if row['kind'] == 'market':
        return row['identity']
    return 'md5:' + (row.get('md5') or _md5_of(store, row['artifact_id']))


def known(store, persona, key):
    return store.db.sticker_memory.find_one({'persona': persona, **_by_key(key)}) if key else None


_pictures = {}                  # ref -> picture of a posted sticker, downloaded once (None: it could not be)


def _known_by_picture(store, persona, entry, key, fetch):
    """A posted custom sticker whose md5 she does not know: downloaded once and matched by its picture; a match
    makes that md5 known too, so the next copy needs no download."""
    ref = entry['ref']
    if ref not in _pictures:
        try:
            _pictures[ref] = picture_key(fetch(entry))
        except Exception:                                  # unreachable or gone: it stays unknown, as before
            _pictures[ref] = None
        while len(_pictures) > 512:
            _pictures.pop(next(iter(_pictures)))
    picture = _pictures[ref]
    row = store.db.sticker_memory.find_one({'persona': persona, 'picture': picture}) if picture else None
    if row and key and key != row['key'] and key not in (row.get('aliases') or ()):
        store.put('sticker_memory', {**row, 'aliases': [*(row.get('aliases') or ()), key][-20:]},
                  expected=row['revision'], stream='sticker-memory:' + persona)
    return row


def recognized(store, persona, entries, fetch=None):
    """{ref: words} for the posted stickers she knows: what she called it, and whether it is on her shelf.
    ``fetch(entry) -> bytes`` lets a custom sticker whose md5 is unknown be matched by its picture."""
    out = {}
    for entry in entries:
        if not entry.get('sticker'):
            continue
        key = memory_key(entry)
        row = known(store, persona, key)
        if not row and fetch and entry['sticker'] == 'custom' and entry.get('pullable'):
            row = _known_by_picture(store, persona, entry, key, fetch)
        if not row:
            continue
        how = row['how']
        if how == 'kept' and not store.db.stickers.find_one({'persona': persona, 'identity': row.get('identity')}, {'_id': 1}):
            how = 'dropped'
        out[entry['ref']] = '你认得：「%s」，%s；%s' % (row['name'], row['note'], MEMORY_WORDS[how])
    return out


def remember(store, ep, persona, args, config):
    """She looked at a posted sticker or a candidate this turn and names it, without keeping it."""
    from .vision import scene_attachments
    name, when = _name(args.get('name')), _when(args.get('when'))
    looked = ep.get('looked') or []
    candidate = str(args.get('candidate') or '').strip()
    if candidate:
        row = store.db.sticker_pool.find_one({'artifact_id': candidate})
        if not row:
            raise Denied(CANDIDATE_GONE % candidate)
        if candidate not in looked:
            raise Denied('STICKER_CANDIDATE_NOT_LOOKED')
        _know(store, persona, _pool_key(store, row), name, when, 'looked',
              picture=row.get('picture') or _picture_of(store, row['artifact_id']))
        store.db.sticker_pool.delete_one({'_id': row['_id']})
        return {'remembered': name}
    ref = str(args.get('ref') or '').strip()
    scene = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
    entry = next((item for item in scene_attachments(store, scene, config)['attachments'] if item['ref'] == ref), None)
    if not entry:
        raise Denied('STICKER_REF_NOT_HERE: ' + _ref_problem(ref))
    if not entry.get('sticker'):
        raise Denied('STICKER_IS_A_PHOTO: 「%s」' % ref)
    if ref not in looked:
        raise Denied('STICKER_NOT_LOOKED')
    key = memory_key(entry)
    if not key:
        raise Denied('STICKER_NO_FINGERPRINT')
    pooled = store.db.sticker_pool.find_one({'$or': [{'identity': key}, {'md5': key[4:]}]}, {'picture': 1})
    _know(store, persona, key, name, when, 'looked', picture=(pooled or {}).get('picture'))
    store.db.sticker_pool.delete_many({'$or': [{'identity': key}, {'md5': key[4:]}]})
    return {'remembered': name}
