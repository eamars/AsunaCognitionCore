"""Her sticker shelf and the platform's own faces (ADR-016).

A sticker is a picture someone sent *as a sticker* (still or animated), or a store sticker; a photo is not
one. Where the platform marks stickers (channel_kinds: the adapter's media item, or the kind's
``sticker_of``), she may keep one on her shelf by its ref, under a name of her own and a note on when it
fits; a picture she made herself may go on the shelf too. Only stickers can be kept, never photos.

- Keeping a custom sticker stores its bytes once (``global-safe``: a sticker is public meme content, not
  anyone's private picture); a store sticker keeps the ids the platform needs to send it again.
- In a conversation whose platform sends stickers, a ``speak`` part of kind ``sticker`` with its ``name`` goes
  out as that sticker, as a message of its own; a ``[表情包:名字]`` token inside a text part is refused.
  ``[表情:名字]`` is one of the platform's own faces, inside the text; the adapter turns a known name into
  the real face.
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
from .records import artifacts as artifact_records
from .records import scenes as scene_records
from .records import messages as message_records
from .records.view import ANY, View, fenced, is_text
from .store.words import And, Holds, Or, Range

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

STICKERS_NOTE = ('你收着的表情包（名字和你写的用法）。能发的地方：speak 里写一个 kind=sticker 的 part（name 照抄这里的名字），作为单独一条发出去。'
                 '群里别人发的表情包下面标着「表情包 ref：att-…」，喜欢的用 sticker 的 keep 收下；'
                 '你认得的表情包下面标着你给它起的名字。')
HOME_NOTE = ('你收着的表情包。在家里发不出去，只是给你整理（sticker 的 drop、rename；你画的图也能 keep 上来）；'
             '带图的标着 ref，想重看就 read_image。')
FACES_NOTE = ('%s 自己的小黄脸写「[表情:名字]」，夹在话里就行，会变成真的表情；名字要用 %s 的'
              '（下面是这里最近有人用过的，别处见过的也行），不认识的名字会被退回。')
REVIEW_NOTE = ('这是你的表情包架子，每周看一眼。下面是收了以后一直没发、或很久没发的几个：'
               '还喜欢的留着，不想要的用 sticker 的 drop 放下，名字或用法不顺手的用 rename 改。'
               '留什么由你，程序不替你扔。')


# ── the owner of `stickers`, `sticker_pool` and `sticker_memory` ──
# Read and written only through these: a row as stored (`fields` names what to return; `_id` always comes back). None
# follows the store's rule (ADR-104 section 4): an id, the persona, a name, a sticker's identity, a fingerprint, a
# picture or a conversation given None, or a value not of its kind, finds nothing without a read.
SHELF, POOL, MEMORY = 'stickers', 'sticker_pool', 'sticker_memory'


def shelf(store, persona):
    """Her shelf, by name."""
    return View(store, SHELF, fenced({}, {'persona': (persona, is_text)}), (('name', 1),)).rows()


def find(store, persona, name):
    """The sticker of hers with this name, or None."""
    return View(store, SHELF, fenced({}, {'persona': (persona, is_text), 'name': (name, is_text)})).first()


def shelf_size(store, persona):
    return View(store, SHELF, fenced({}, {'persona': (persona, is_text)})).count()


def holding(store, identity, *, persona=ANY, picture=None, fields=None):
    """The shelf row holding this sticker (of this persona): by its identity, or (`picture` given) by its picture too;
    or None."""
    if not is_text(identity) or not (persona is ANY or is_text(persona)):
        return None
    where = {'identity': identity}
    if picture:
        where = Or(where, {'picture': picture})
    if persona is not ANY:
        where = And({'persona': persona}, where) if picture else {'persona': persona, **where}
    return View(store, SHELF, where).first(fields=fields)


def holds_picture(store, artifact_id):
    """Whether a shelf row keeps this picture."""
    return View(store, SHELF, fenced({}, {'artifact_id': (artifact_id, is_text)})).first(fields=['_id']) is not None


def drop_sticker(store, sticker_id, revision):
    """A shelf row goes, if it is still at this revision."""
    if is_text(sticker_id):
        store.collection(SHELF).delete({'_id': sticker_id, 'revision': revision})


def save(store, row, **kwargs):
    """The revisioned write of a shelf row (`Store.put`: `expected`, `stream`)."""
    return store.put(SHELF, row, **kwargs)


def candidate_of(store, artifact_id):
    """The candidate in the pool whose picture this is, or None."""
    return View(store, POOL, fenced({}, {'artifact_id': (artifact_id, is_text)})).first()


def pooled(store, key):
    """The candidate with this id, or None."""
    return store.collection(POOL).get(key) if is_text(key) else None


def pool_size(store, limit=None):
    return store.collection(POOL).count(limit=limit)


def pool(store, *, scene_id=ANY, since=None):
    """View: the candidates (posted in this conversation since `since`, ISO text), the most seen first, then the most
    recently seen."""
    where = {}
    if scene_id is not ANY:
        here = is_text(scene_id) and is_text(since)
        where = {'scenes': Holds(scene_id), 'last_seen': Range(gte=since)} if here else None
    return View(store, POOL, where, (('seen', -1), ('last_seen', -1)))


def least_seen(store, count):
    """The `count` candidates seen least recently (identity and revision)."""
    return View(store, POOL, {}, (('last_seen', 1),)).rows(limit=count or None, fields=['identity', 'revision'])


def drop_candidate(store, key, revision=ANY):
    """A candidate goes (if it is still at this revision)."""
    if is_text(key):
        store.collection(POOL).delete({'_id': key, **({} if revision is ANY else {'revision': revision})})


def _of_key(key):
    """The pool's rows of a sticker known by this fingerprint: its identity, or (an md5 fingerprint) its bytes' md5."""
    return Or({'identity': key}, {'md5': key[4:]})


def pooled_as(store, key):
    """A candidate known by this fingerprint (its picture only), or None."""
    return View(store, POOL, _of_key(key) if is_text(key) else None).first(fields=['picture'])


def drop_pooled(store, *, identity=ANY, key=ANY):
    """The candidates of this identity, or known by this fingerprint, go."""
    if identity is not ANY:
        where = {'identity': identity} if is_text(identity) else None
    else:
        where = _of_key(key) if is_text(key) else None
    if where is not None:
        store.collection(POOL).delete(where, many=True)


def save_candidate(store, row, **kwargs):
    """The revisioned write of a candidate (`Store.put`: `expected`, `stream`)."""
    return store.put(POOL, row, **kwargs)


def _by_key(key):
    return Or({'key': key}, {'aliases': Holds(key)})


def memory(store, memory_id):
    """What she knows of one sticker by its row's id, or None."""
    return store.collection(MEMORY).get(memory_id) if is_text(memory_id) else None


def known_as(store, key, *, persona=ANY, picture=None):
    """What she knows of a sticker by this fingerprint (its key or one of its aliases), or (`picture` given) by its
    picture; her own (`persona`) or anyone's."""
    if not is_text(key):
        return None
    where = Or(_by_key(key), {'picture': picture}) if picture else _by_key(key)
    if persona is not ANY:
        where = And({'persona': persona}, where) if is_text(persona) else None
    return View(store, MEMORY, where).first()


def memory_of(store, persona, *, key=ANY, picture=ANY, fields=None):
    """What she knows of a sticker by its key alone, or by its picture, or None."""
    where = fenced({}, {'persona': (persona, is_text), 'key': (key, is_text), 'picture': (picture, is_text)})
    return View(store, MEMORY, where).first(fields=fields)


def save_memory(store, row, **kwargs):
    """The revisioned write of what she knows of a sticker (`Store.put`: `expected`, `stream`)."""
    return store.put(MEMORY, row, **kwargs)


def artifact_ids(store):
    """The pictures the shelf and the pool keep (their artifact ids)."""
    return set(store.collection(SHELF).group({}, ['artifact_id'], None)) | set(
        store.collection(POOL).group({}, ['artifact_id'], None))


# A sticker she drew keeps its picture in the conversation she drew it in, so an erasure of that conversation deletes
# it (ADR-105); the shelf row stays, as the only record that the drawing existed, until she drops it herself.
GONE_WORDS = '这几张画不在了：名字还在架子上，放不放下由你。'


def erased_pictures(store, rows):
    """{artifact_id: artifacts row} of the shelf pictures a privacy erasure deleted."""
    ids = [row['artifact_id'] for row in rows if row and row.get('artifact_id')]
    if not ids:
        return {}
    return {item['_id']: item for item in artifact_records.by_ids(store, ids, storage=artifact_records.ERASED).rows()}


def refuse_erased(store, persona, name, scene_id):
    """A sticker named in speak whose picture an erasure deleted: ADR-105's sentence in that call, so it is never
    accepted and then failed when the adapter asks for its bytes."""
    from . import blobs
    row = find(store, persona, name)
    gone = erased_pictures(store, [row])
    if gone:
        raise Denied('ARTIFACT_ERASED: ' + blobs.erased_words(store, gone[row['artifact_id']], scene_id))


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
    return '「%s」' % ref if ref else '没写 ref（也没写 candidate）；想从候选池里收，先用 do=pool 看池子'


def fullness(count):
    return _tier(SHELF_WORDS, count / STICKER_SHELF)


# ── keeping, dropping, renaming ─────────────────────────────────────
def keep(store, blobs, ep, persona, args, config):
    """Put a sticker on her shelf: an att- ref of a sticker in this conversation, or a blob- id of a picture
    she made herself."""
    from .outbound_media import produced, sniff_media_type
    from .vision import ARTIFACT_REF, attachment_by_ref, media_source, pull_bytes
    name, when = _name(args.get('name')), _when(args.get('when'))
    ref = str(args.get('ref') or '').strip()
    if shelf_size(store, persona) >= STICKER_SHELF:
        raise Denied('STICKER_SHELF_FULL: 上限 %d 个' % STICKER_SHELF)
    if find(store, persona, name):
        raise Denied('STICKER_NAME_TAKEN: ' + name)
    doc = {'persona': persona, 'name': name, 'when': when, 'kept_at': now(), 'kept_in': ep['scene_id'],
           'sent': 0, 'last_sent_at': None}
    if ARTIFACT_REF.fullmatch(ref):
        from .blobs import refuse_erased
        row = artifact_records.get(store, ref, kind='image', state='DONE')
        if not row or not produced(row):
            raise Denied('STICKER_NOT_YOURS: 「%s」不是你自己画好的图' % ref)
        refuse_erased(store, row, ep['scene_id'])           # hers, erased with the conversation it was made in
        if row.get('storage') != artifact_records.STORED:
            raise Denied('STICKER_NOT_YOURS: 「%s」不是你自己画好的图' % ref)
        doc.update(origin='own', kind='custom', artifact_id=ref, sha256=row['sha256'], size=row['size'],
                   media_type=row.get('media_type'), identity='sha:' + row['sha256'],
                   picture=_picture_of(store, ref))
    else:
        scene = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
        entry, _ = attachment_by_ref(store, scene, config, ref)
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
            data, media_type, _, _ = pull_bytes({**entry, **media_source(store, scene, config, entry)}, config)
            stored = blobs.put_once(data, SCOPE, 'image', source_ids=[SOURCE + entry['source_message_id']])
            doc.update(kind='custom', artifact_id=stored['artifact_id'], sha256=stored['sha256'], size=stored['size'],
                       media_type=media_type or sniff_media_type(data), identity='sha:' + stored['sha256'],
                       md5=hashlib.md5(data).hexdigest().upper(), picture=picture_key(data))
    same = holding(store, doc['identity'], persona=persona, picture=doc.get('picture'))
    if same:
        raise Denied(ALREADY_KEPT % same['name'])
    doc['_id'] = 'stk-' + sha((persona + '|' + doc['identity']).encode())[:20]
    save(store, doc, stream='stickers:' + persona)
    _kept(store, persona, doc)
    drop_pooled(store, identity=doc['identity'])
    count = shelf_size(store, persona)
    return {'kept': name, 'shelf': '%d 个，%s' % (count, fullness(count))}


def drop(store, persona, name):
    row = find(store, persona, _name(name))
    if not row:
        raise Denied('STICKER_NOT_ON_SHELF: 「%s」' % name)
    drop_sticker(store, row['_id'], row['revision'])
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
    save(store, {**row, **changes}, expected=row['revision'], stream='stickers:' + persona)
    _kept(store, persona, {**row, **changes})
    return {'renamed': row['name'], **changes}


# ── what her turn sees ──────────────────────────────────────────────
def sends(scene):
    """Whether what she says in this conversation can carry stickers and faces."""
    return bool((scene or {}).get('channel_id')) and channel_kinds.sends_stickers(scene['_id'])


def block(store, persona, scene, *, at_home=False):
    """The shelf in full (names, usage notes, how often sent): in the turns that tidy it at home, and for `sticker` op
    shelf anywhere."""
    from . import blobs
    rows = shelf(store, persona)
    if at_home and not rows:
        return None
    gone = erased_pictures(store, rows)
    # At home, where she tidies it, a sticker with a picture carries its id so she can look at it again (her ask
    # 2026-10-10: animated ones were named from their first frame only). A picture an erasure deleted says so in a
    # field of its own; the name stays as she wrote it, since she copies it to send, drop or rename.
    return {'items': [{'sticker': row['name'], 'when': row['when'], 'used': _tier(USE_WORDS, row.get('sent') or 0),
                       **({'from': ORIGIN_WORDS['own']} if row.get('origin') == 'own' else {}),
                       **({'picture': blobs.erased_words(store, gone[row['artifact_id']], (scene or {}).get('_id'))}
                          if row.get('artifact_id') in gone else
                          {'ref': row['artifact_id']} if at_home and row.get('artifact_id') else {})} for row in rows],
            'shelf': '%d 个，%s' % (len(rows), fullness(len(rows))),
            'note': HOME_NOTE if at_home else STICKERS_NOTE, **({'gone': GONE_WORDS} if gone else {})}


NAMES_NOTE = '架子上的名字（你起的）。用法、样子和 ref 在整理架子的回合里列全，别的时候用 sticker 的 shelf 看。'
SEND_NOTE = ('你收着的表情包的名字（你起的）。能发的地方：speak 里写一个 kind=sticker 的 part（name 照抄这里的名字），作为单独一条发出去；'
             '你写的用法用 sticker 的 shelf 看。群里别人发的表情包下面标着「表情包 ref：att-…」，喜欢的用 sticker 的 keep 收下；'
             '你认得的表情包下面标着你给它起的名字。')


def send_block(store, persona):
    """stickers_from_program where stickers can go out: every name on her shelf, her usage notes left to the shelf
    (her answer, 2026-10-21: the names are hers and few characters; the notes were most of the list)."""
    rows = shelf(store, persona)
    return {'names': '、'.join(row['name'] for row in rows), 'shelf': '%d 个，%s' % (len(rows), fullness(len(rows))),
            'note': SEND_NOTE}


def names_block(store, persona):
    """stickers_from_program at home outside the turns that tidy the shelf: its names only (her answer, 2026-10-16:
    what she has stays in mind; the uses are what take the room)."""
    rows = shelf(store, persona)
    if not rows:
        return None
    return {'names': '、'.join(row['name'] for row in rows), 'shelf': '%d 个，%s' % (len(rows), fullness(len(rows))),
            'note': NAMES_NOTE}


def _title(scene):
    return getattr(channel_kinds.of(scene['_id']), 'TITLE', '这个平台')


def faces_block(store, scene):
    """faces_from_program: the platform faces people here used lately, by name."""
    names = channel_kinds.faces_of(scene['_id'])
    if not names:
        return None
    counts = {}
    for row in message_records.inbound(store, scene['_id']).rows(newest_first=True, limit=FACE_SCAN, fields=['text']):
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
    scene = scene_records.get(store, ep['scene_id'], fields=['_id', 'channel_id'])
    if not sends(scene):
        return '这里发不出表情包或小黄脸：把「[表情包:…]」「[表情:…]」去掉，用话说。'
    for name in stickers:
        if not find(store, ep['persona'], name):
            return '架子上没有叫「%s」的表情包：照抄 stickers_from_program 里的名字，或者不发。' % name
    known = channel_kinds.faces_of(scene['_id'])
    unknown = [name for name in faces if name not in known]
    if unknown:
        return '「%s」不是 %s 的小黄脸名字：换成认识的名字，或者去掉。' % ('、'.join(dict.fromkeys(unknown)),
                                                           _title(scene))
    return None


def leaving(store, row):
    """The sha and size of a shelf picture as it leaves: its stored bytes without their text, which is what
    outbound_media.serve sends and checks the declared sha against. A copy that cannot be read keeps the shelf's own
    sha, and serve refuses it and says why."""
    from .blobs import BlobStore
    from .outbound_media import sha256_of, without_text
    item = artifact_records.get(store, row['artifact_id'], ['scope_key']) or {}
    try:
        data = without_text(BlobStore(store).get(row['artifact_id'], item.get('scope_key'), operator=True))
    except (Denied, ValueError):
        return {'sha256': row['sha256'], 'size': row.get('size')}
    return {'sha256': sha256_of(data), 'size': len(data)}


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
                                            **leaving(store, row)}})
    if not attachment:
        return None
    return {'sticker': {'kind': 'custom', 'name': row['name']}, 'attachment': attachment}


def sent(store, persona, name, scene_id):
    row = find(store, persona, name)
    if row:
        save(store, {**row, 'sent': (row.get('sent') or 0) + 1, 'last_sent_at': now(), 'last_sent_in': scene_id},
             expected=row['revision'], stream='stickers:' + persona)


def on_shelf(store, artifact_id):
    """A kept sticker's picture: it may go to any conversation that takes stickers (outbound_media.serve)."""
    return holds_picture(store, artifact_id)


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
    from . import blobs
    gone = erased_pictures(store, rows)
    idle = [(-1, 0, row, blobs.erased_words(store, gone[row['artifact_id']])) for row in rows
            if row.get('artifact_id') in gone]          # first to weigh; dropping them stays hers
    for row in rows:
        if row.get('artifact_id') in gone:
            continue
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
            'note': REVIEW_NOTE, **({'gone': GONE_WORDS} if gone else {})}


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
    from .vision import attachments_of, media_source, pull_bytes
    row = message_records.get(store, message_id)
    if not row or row.get('direction') != 'inbound':
        return 0
    scene = scene_records.get(store, row['scene_id'])
    if not scene or scene.get('kind') != 'group':
        return 0
    task = {'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    added = 0
    for entry in attachments_of(row, config=config):
        if not entry.get('sticker') or not entry.get('pullable'):
            continue
        fingerprint = memory_key(entry)
        if fingerprint and known_as(store, fingerprint):
            continue                                   # she knows it already: kept once, or looked and let go
        try:
            data, media_type, _, _ = pull_bytes({**entry, **media_source(store, task, config, entry)}, config)
        except Exception:
            continue                                   # gone already: nothing to save
        stored = blobs.put_once(data, SCOPE, 'image', source_ids=[POOL_SOURCE + message_id])
        identity = ('market:' + entry['market']['emoji_id'] if entry['sticker'] == 'market'
                    else 'sha:' + stored['sha256'])
        md5 = hashlib.md5(data).hexdigest().upper()
        if holding(store, identity, fields=['_id']):
            continue                                   # already on her shelf
        picture = picture_key(data)
        if known_as(store, 'md5:' + md5, picture=picture):
            continue                                   # known by its bytes or its picture, though named otherwise
        at = row.get('received_at') or now()
        key = 'cand-' + sha(identity.encode())[:16]
        current = pooled(store, key)
        try:
            if current:
                save_candidate(store, {**current, 'seen': current['seen'] + 1, 'last_seen': at,
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
                save_candidate(store, doc, stream='sticker-pool')
                added += 1
        except Conflict:
            continue                                   # the same sticker, counted by a concurrent arrival
    rotate(store)
    return added


def rotate(store):
    """Past POOL_MAX, the least recently seen candidates leave the pool."""
    extra = pool_size(store) - POOL_MAX
    if extra > 0:
        for doc in least_seen(store, extra):
            drop_candidate(store, doc['_id'], doc['revision'])
            store.audit('sticker-pool', 'sticker.pool.rotated', {'identity': doc['identity']})


def candidates_block(store, moment, scene_id=None):
    """sticker_candidates_from_program: nightly the most posted; in a group's turn, the ones posted there lately."""
    from datetime import timedelta
    from .people import People
    view, limit = pool(store), POOL_SHOWN
    if scene_id:
        view = pool(store, scene_id=scene_id, since=(moment - timedelta(hours=POOL_HERE_HOURS)).isoformat())
        limit = POOL_SHOWN_HERE
    rows = view.rows(limit=limit)
    if not rows:
        return None
    people = People(store)
    items = []
    for row in rows:
        where = '、'.join(people.scene_title(scene_records.get(store, s) or {'_id': s}) for s in row['scenes'][-2:])
        hours = _hours(moment, row['last_seen'])
        items.append({'candidate': row['artifact_id'], 'seen': '%s见过%s' % (where, _tier(SEEN_WORDS, row['seen'])),
                      **({'last': _tier(ROUGH_AGO, hours)} if hours is not None else {})})
    return {'items': items, 'pool': '池子里 %d 个' % pool_size(store), 'note': POOL_NOTE}


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
    row = candidate_of(store, candidate)
    if not row:
        raise Denied(CANDIDATE_GONE % candidate)
    if candidate not in (ep.get('looked') or []) and not known(store, persona, _pool_key(store, row)):
        raise Denied('STICKER_CANDIDATE_NOT_LOOKED')       # one she knows from before counts as looked
    if shelf_size(store, persona) >= STICKER_SHELF:
        raise Denied('STICKER_SHELF_FULL: 上限 %d 个' % STICKER_SHELF)
    if find(store, persona, name):
        raise Denied('STICKER_NAME_TAKEN: ' + name)
    same = holding(store, row['identity'], persona=persona, picture=row.get('picture'))
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
    save(store, doc, stream='stickers:' + persona)
    _kept(store, persona, doc)
    drop_candidate(store, row['_id'])
    count = shelf_size(store, persona)
    return {'kept': name, 'shelf': '%d 个，%s' % (count, fullness(count))}


# ── the stickers she knows (owner 2026-10-06) ───────────────────────
# A sticker she looked at and named stays known for good, by a fingerprint: the md5 of a picture's bytes (a
# platform may name the file by it, channel_kinds.sticker_md5) or a store sticker's ids, and by its picture
# (picture_key). When it is posted again, the line under it says what she called it, so she need not look
# again: the file md5 needs no download. A copy whose md5 is unknown is matched by its picture when she opens it
# (read_image, or her group turn's pictures: the bytes are there already), and that md5 is then known too
# (aliases); a line is never held for a download. The words are only hers: a sticker on her shelf is known by its
# name and note (and stays known after she drops it); one she looked at and does not want to send she may
# remember with a name and a line of her own.
MEMORY_WORDS = {'kept': '在你架子上', 'dropped': '你收过又放下了', 'looked': '你看过没收'}
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
    row = artifact_records.get(store, artifact_id, ['scope_key'])
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


def _shelf_key(store, doc):
    if doc.get('kind') == 'market':
        return 'market:' + doc['market']['emoji_id']
    md5 = doc.get('md5') or _md5_of(store, doc['artifact_id'])
    return 'md5:' + md5 if md5 else None


def _know(store, persona, key, name, note, how, identity=None, picture=None):
    """Write what she knows of one sticker (a new look replaces the old words)."""
    _id = 'skm-' + sha((persona + '|' + key).encode())[:20]
    current = memory(store, _id)
    doc = {**(current or {}), '_id': _id, 'persona': persona, 'key': key, 'name': name, 'note': note, 'how': how,
           'identity': identity or (current or {}).get('identity'),
           'picture': picture or (current or {}).get('picture'), 'at': now()}
    return save_memory(store, doc, expected=current and current['revision'], stream='sticker-memory:' + persona)


def _shelf_picture(store, doc):
    """A custom shelf sticker's picture fingerprint, worked out once from its bytes and kept on its shelf row."""
    if doc.get('kind') == 'market' or doc.get('picture'):
        return doc.get('picture')
    from .state import Conflict
    picture = _picture_of(store, doc['artifact_id'])
    if picture and doc.get('revision'):
        try:
            save(store, {**doc, 'picture': picture}, expected=doc['revision'], stream='stickers:' + doc['persona'])
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
        row = memory_of(store, persona, key=key, fields=['picture'])
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
    return known_as(store, key, persona=persona) if key else None


def opened(store, persona, entry, data):
    """She opened a posted custom sticker (its bytes `data`): one she knows by its picture though not by this md5
    makes that md5 known too, so the next copy is known on sight. Returns the memory, or None."""
    if entry.get('sticker') != 'custom' or not data:
        return None
    key = memory_key(entry)
    if not key or known(store, persona, key):
        return None
    row = memory_of(store, persona, picture=picture_key(data))
    if row and key != row['key'] and key not in (row.get('aliases') or ()):
        save_memory(store, {**row, 'aliases': [*(row.get('aliases') or ()), key][-20:]},
                    expected=row['revision'], stream='sticker-memory:' + persona)
    return row


def recognized(store, persona, entries):
    """{ref: words} for the posted stickers she knows: what she called it, and whether it is on her shelf. Known by
    the md5 or a store sticker's ids only: nothing is downloaded."""
    out = {}
    for entry in entries:
        if not entry.get('sticker'):
            continue
        row = known(store, persona, memory_key(entry))
        if not row:
            continue
        how = row['how']
        if how == 'kept' and not holding(store, row.get('identity'), persona=persona, fields=['_id']):
            how = 'dropped'
        out[entry['ref']] = '你认得：「%s」，%s；%s' % (row['name'], row['note'], MEMORY_WORDS[how])
    return out


def remember(store, ep, persona, args, config):
    """She looked at a posted sticker or a candidate this turn and names it, without keeping it."""
    from .vision import attachment_by_ref
    name, when = _name(args.get('name')), _when(args.get('when'))
    looked = ep.get('looked') or []
    candidate = str(args.get('candidate') or '').strip()
    if candidate:
        row = candidate_of(store, candidate)
        if not row:
            raise Denied(CANDIDATE_GONE % candidate)
        if candidate not in looked:
            raise Denied('STICKER_CANDIDATE_NOT_LOOKED')
        _know(store, persona, _pool_key(store, row), name, when, 'looked',
              picture=row.get('picture') or _picture_of(store, row['artifact_id']))
        drop_candidate(store, row['_id'])
        return {'remembered': name}
    ref = str(args.get('ref') or '').strip()
    scene = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
    entry, _ = attachment_by_ref(store, scene, config, ref)
    if not entry:
        raise Denied('STICKER_REF_NOT_HERE: ' + _ref_problem(ref))
    if not entry.get('sticker'):
        raise Denied('STICKER_IS_A_PHOTO: 「%s」' % ref)
    if ref not in looked:
        raise Denied('STICKER_NOT_LOOKED')
    key = memory_key(entry)
    if not key:
        raise Denied('STICKER_NO_FINGERPRINT')
    seen = pooled_as(store, key)
    _know(store, persona, key, name, when, 'looked', picture=(seen or {}).get('picture'))
    drop_pooled(store, key=key)
    return {'remembered': name}
