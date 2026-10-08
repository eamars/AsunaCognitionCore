"""Who is who in a scene, as the character reads it.

Identity is the account: a person_id, mapped to its canonical person by configuration. A name is
only what that person chose to show today, and anyone can choose any name. So each person gets a
fixed label (#n) in each scene the first time they appear, kept for good: the same person reads
the same across renames, compaction and memory, and two people with one name never merge.

Names are made safe before she reads them: one line, visible characters only, and none of the
characters a label is built from, so a name can never close a label, imitate a handle or start a
new speaker line. Message text is indented under its label for the same reason. The program, not
the model, notices look-alike names, recent renames and group roles, and says so after the label.
Platform account numbers stay in program data: mentions of known people read as their label.
"""
from __future__ import annotations

import re
import unicodedata

from . import channel_kinds
from .config import excerpt
from .peer_context import channel_of, peer_from_message, verify_peer
from .state import Conflict, now

NAME_LIMIT = 20
# Applied after NFKC, which already folds ［］＃＜＞ into their ASCII forms.
LABEL_BREAKERS = frozenset('[]【】「」『』#<>')
RENAME_NOTE_HOURS = 24
PREVIOUS_NAMES = 4
LOOKALIKE_NOTES = 2
ROLE_NOTES = {'owner': '群主', 'admin': '管理员'}
ROLES = ('owner', 'admin', 'member')
# A label as she sees it: [name #4].
LABEL = r'\[(?P<name>[^\[\]#\n]*)#\s*(?P<handle>\d{1,6})\s*\]'
# What she writes to @ someone: @ and their label, e.g. @[name #4] (the owner's may start with the owner word, and
# the whole label may sit in one more pair of brackets), or @#4.
LABEL_MENTION = re.compile(r'@\s*(?P<open>\[\s*)?(?:[^\s@\[\]#]{1,12}\s*)?' + LABEL + r'(?(open)(?:\s*\])?)'
                           r'|@#(?P<bare>\d{1,6})')
BARE_LABEL = re.compile(LABEL)
# A label opening her line or one of its lines, without @: it reads like a tag but leaves as a plain name.
LEADING_LABEL = re.compile(r'(?:^|\n)[ \t]*(\[[^\[\]#\n]*#\s*\d{1,6}\s*\])')
LEADING_LABEL_PROBLEM = ('开头的「%s」不会 @ 到人（发出去只是名字）：要 @ 他就写 @%s；只是提到他，就直接写名字。')


def speech_problem(speech):
    """A label she opened a line with and did not @, handed back in the same turn; None when there is none."""
    found = LEADING_LABEL.search(speech or '')
    return LEADING_LABEL_PROBLEM % (found.group(1), found.group(1)) if found else None
UNKNOWN_NAME = '还不知道名字'
REPLY_EXCERPT = 60


def safe_name(value, limit=NAME_LIMIT):
    """A shown name she can read safely: one line, visible characters only, no label characters."""
    text = unicodedata.normalize('NFKC', value if isinstance(value, str) else '')
    kept = []
    for ch in text:
        if ch.isspace():
            kept.append(' ')
        elif unicodedata.category(ch)[0] != 'C' and ch not in LABEL_BREAKERS:
            kept.append(ch)
    return ' '.join(''.join(kept).split())[:limit]


def name_key(value):
    """What a name looks like, for spotting look-alikes: its letters only (no digits, spaces, symbols or case)."""
    return ''.join(ch for ch in safe_name(value, 60).casefold() if unicodedata.category(ch).startswith('L'))


def _hours_since(stamp, moment):
    from datetime import datetime
    try:
        then = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        return (datetime.fromisoformat(moment.replace('Z', '+00:00')) - then).total_seconds() / 3600
    except ValueError:
        return None


class People:
    """Labels for the people of this store's scenes. Cheap to build; one instance per use."""

    def __init__(self, store, persona=None):
        self.store, self.db, self.config = store, store.db, store.config
        chat = self.config.get('chat') or {}
        self.owner = chat.get('person_id')
        self.self_id = self.config.get('character_id') or chat.get('persona')
        from .persona_model import effective
        from .render import model_and_policy
        persona = persona or chat.get('persona') or self.self_id
        self.persona = persona
        model, policy = model_and_policy(store, persona) if persona else ({}, {})
        self.owner_label = safe_name(effective(model, 'people.owner_label', policy)) or '本机用户'
        self.self_name = safe_name(chat.get('display_name')) or str(self.self_id or '')
        self.self_names = [n for n in (self.self_name, *(safe_name(x) for x in effective(model, 'people.self_names', policy) or []))
                           if n]
        self._rosters, self._looked_up = {}, set()

    # ---- identity ---------------------------------------------------------
    def person(self, person_id):
        """The canonical person behind an author id (configuration decides; a name never does)."""
        if not person_id or person_id == self.self_id:
            return person_id or ''
        from .scene_links import canonical_person_id
        return canonical_person_id(self.config, self.db, person_id) or person_id

    def account_person(self, scene_id, number, platform=None):
        """The person_id the host keeps for a platform account number in this scene's platform."""
        platform = platform or channel_kinds.of(scene_id)
        row = self.db.identities.find_one({'account_id': str(number)}, {'person_id': 1})
        return (row or {}).get('person_id') or (platform.person_id(number) if platform else str(number))

    def is_owner(self, doc):
        return bool(self.owner) and doc.get('person') == self.owner

    # ---- her own place in a group ----------------------------------------
    def self_role(self, scene):
        """Her role in this group as the adapter last reported it (owner/admin/member), else None."""
        doc = self.db.scene_people.find_one({'_id': scene['_id'] + '|' + str(self.self_id)}, {'role': 1})
        return (doc or {}).get('role') if (doc or {}).get('role') in ROLES else None

    def note_self(self, scene, row):
        """Keep her role from a message's raw.asuna_self (channels.kept_raw checked it); handle 0 is hers."""
        raw = ((row.get('event') or {}).get('raw') or {}).get('asuna_self') or {}
        role, moment = raw.get('role'), str(row.get('received_at') or '')
        if role not in ROLES or not self.self_id:
            return
        key = scene['_id'] + '|' + str(self.self_id)
        doc = self.db.scene_people.find_one({'_id': key})
        if doc and (doc.get('role') == role or str(doc.get('seen_at') or '') > moment):
            return
        values = {'_id': key, 'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'person': self.self_id,
                  'author': self.self_id, 'handle': 0, 'card': '', 'nickname': '', 'role': role, 'previous': [],
                  'seen_at': moment, 'created_at': (doc or {}).get('created_at') or now()}
        try:
            self.store.put('scene_people', {**(doc or {}), **values}, expected=doc['revision'] if doc else None,
                           stream='people:' + scene['_id'])
        except Conflict:
            pass                                             # a newer report won; the next message says again

    # ---- records ----------------------------------------------------------
    def roster(self, scene_id):
        if scene_id not in self._rosters:
            self._rosters[scene_id] = {doc['_id']: doc for doc in self.db.scene_people.find({'scene_id': scene_id})}
        return self._rosters[scene_id]

    def entry(self, scene, person_id, row=None, profile=None):
        """This person's record in the scene: created with the next label on first sight, refreshed from a newer verified profile.

        `profile`: their names from a message that @-mentions them (`mentioned`); `row` is then that message."""
        person = self.person(person_id)
        key = scene['_id'] + '|' + person
        roster = self.roster(scene['_id'])
        doc = roster.get(key) or self.db.scene_people.find_one({'_id': key})
        for _ in range(8):
            if doc:
                break
            last = self.db.scene_people.find_one({'scene_id': scene['_id']}, {'handle': 1}, sort=[('handle', -1)])
            try:
                doc = self.store.put('scene_people', {
                    '_id': key, 'scene_id': scene['_id'], 'scope_key': scene['scope_key'], 'person': person,
                    'author': person_id,
                    'handle': (last or {}).get('handle', 0) + 1, 'card': '', 'nickname': '', 'role': '',
                    'previous': [], 'seen_at': '', 'created_at': now()}, stream='people:' + scene['_id'])
            except Conflict:
                doc = self.db.scene_people.find_one({'_id': key})      # someone else placed it, or took the number
        if not doc:
            raise Conflict('SCENE_PERSON_UNAVAILABLE')
        if row is None and profile is None and not doc.get('seen_at') and person != self.self_id \
                and key not in self._looked_up:
            # Someone first labelled from older history: take the names from their latest saved message.
            self._looked_up.add(key)
            row = self.db.messages.find_one({'scene_id': scene['_id'], 'author': person_id, 'direction': 'inbound',
                                             'event.raw.asuna_peer': {'$exists': True}}, sort=[('received_at', -1)])
        fresh = profile if profile is not None else (
            self._profile(row) if row is not None and person != self.self_id else None)
        moment = str((row or {}).get('received_at') or '')
        if fresh and (not doc.get('seen_at') or moment > str(doc['seen_at'])):
            changed = {k: v for k, v in fresh.items() if doc.get(k) != v}
            if changed:
                old = doc.get('card') or doc.get('nickname')
                new = fresh.get('card', doc.get('card')) or fresh.get('nickname', doc.get('nickname'))
                previous = list(doc.get('previous') or [])
                if old and new and new != old:
                    previous = (previous + [{'name': old, 'until': moment}])[-PREVIOUS_NAMES:]
                try:
                    doc = self.store.put('scene_people', {**doc, **fresh, 'previous': previous, 'seen_at': moment},
                                         expected=doc['revision'], stream='people:' + scene['_id'])
                except Conflict:
                    doc = self.db.scene_people.find_one({'_id': key}) or doc
        roster[key] = doc
        return doc

    def _profile(self, row):
        """Names and group role from the verified platform profile saved with this message, or None."""
        # Bound to the host-authenticated sender and group of this message; an auto-admitted author's
        # hashed person_id does not change whose profile it is.
        peer = peer_from_message(row)
        channel = channel_of(row)
        ok, _ = verify_peer(peer, channel)
        sender = str((channel or {}).get('sender_id') or '')
        platform = channel_kinds.of(row.get('scene_id')) or channel_kinds.get((channel or {}).get('id'))
        if not ok or not platform or row.get('author') not in (platform.person_id(sender),
                                                               self.account_person(None, sender, platform)):
            return None
        return self._names(peer)

    def mentioned(self, row, account):
        """Names and group role of someone this message @-mentions, from the profile kept with it, or None."""
        from .peer_context import MENTIONED_KEY
        for item in ((row.get('event') or {}).get('raw') or {}).get(MENTIONED_KEY) or []:
            if isinstance(item, dict) and str(item.get('account_id')) == str(account):
                return self._names(item) or None
        return None

    @staticmethod
    def _names(peer):
        out = {}
        for field in ('card', 'nickname'):
            if isinstance(peer.get(field), str):
                out[field] = ' '.join(peer[field].split())[:60]
        if not (out.get('card') or out.get('nickname')) and isinstance(peer.get('display'), str):
            out['nickname'] = ' '.join(peer['display'].split())[:60]
        if peer.get('role') in ROLES:
            out['role'] = peer['role']
        return out

    # ---- what she reads ---------------------------------------------------
    def named(self, person):
        """A name the operator gave this person on this machine (identities), which outranks any self-chosen name."""
        cache = self.__dict__.setdefault('_named', {})
        if person not in cache:
            row = self.db.identities.find_one({'_id': person}, {'display_name': 1}) if person else None
            cache[person] = safe_name((row or {}).get('display_name'))
        return cache[person]

    def shown(self, doc):
        platform = safe_name(doc.get('card')) or safe_name(doc.get('nickname'))
        if self.is_owner(doc):
            return platform or self.named(doc.get('person'))
        return self.named(doc.get('person')) or platform

    def label(self, doc):
        """[name #n]; the owner's label starts with the persona's word for them; herself is her name."""
        if doc.get('person') == self.self_id:
            return self.self_name
        name = self.shown(doc)
        if self.is_owner(doc) and not name:
            return self.owner_label
        text = '[%s #%s]' % (name or UNKNOWN_NAME, doc['handle'])
        return self.owner_label + ' ' + text if self.is_owner(doc) else text

    def ref(self, doc):
        return (self.owner_label + ' #%s' if self.is_owner(doc) else '#%s') % doc['handle']

    def notes(self, scene_id, doc, moment=None):
        """What the program noticed about this person, in words: group role, look-alike names, a recent rename."""
        if doc.get('person') == self.self_id:
            return []
        out = []
        role = ROLE_NOTES.get(doc.get('role'))
        if role:
            out.append(role)
        name = self.shown(doc)
        keys = {name_key(doc.get('card')), name_key(doc.get('nickname'))} - {''}
        alike = []
        for other in self.roster(scene_id).values():
            if other['_id'] == doc['_id'] or other.get('person') == self.self_id:
                continue
            other_name = self.shown(other)
            if name and other_name == name:
                alike.append('与 %s 同名' % self.ref(other))
            elif keys & ({name_key(other.get('card')), name_key(other.get('nickname'))} - {''}):
                alike.append('与 %s 名字相近' % self.ref(other))
        out += sorted(alike)[:LOOKALIKE_NOTES]
        if keys & {name_key(n) for n in self.self_names}:
            out.append('名字和你相同或相近，但不是你')
        owner_word = name_key(self.owner_label)
        if not self.is_owner(doc) and owner_word and any(owner_word in key for key in keys):
            out.append('名字里有「%s」，但不是%s本人' % (self.owner_label, self.owner_label))
        previous = (doc.get('previous') or [])[-1:]
        if previous and moment:
            hours = _hours_since(previous[0].get('until'), moment)
            if hours is not None and hours < RENAME_NOTE_HOURS:
                out.append('原名「%s」' % safe_name(previous[0].get('name')))
        return out

    def head(self, scene_id, doc, moment=None):
        notes = self.notes(scene_id, doc, moment)
        return self.label(doc) + ('（%s）' % '；'.join(notes) if notes else '')

    def mentions(self, scene, text, account=None):
        """The adapter's real @<number> of a known person (or of her own account) reads as their label."""
        platform = channel_kinds.of(scene['_id'])
        if not platform:
            return text or ''

        def swap(match):
            number = match.group(1)
            if account and number == str(account):
                return '@' + self.self_name
            doc = self.roster(scene['_id']).get(scene['_id'] + '|' + self.person(self.account_person(scene['_id'], number)))
            return '@' + self.label(doc) if doc else match.group(0)
        return platform.INBOUND_MENTION.sub(swap, text or '')

    # ---- lookups (history tools) ------------------------------------------
    def ensure_roster(self, scene):
        """Label everyone who has written in this scene, so a lookup can name them all."""
        roster = self.roster(scene['_id'])
        for author in self.db.messages.distinct('author', {'scene_id': scene['_id'], 'direction': 'inbound'}):
            if author and author != self.self_id and scene['_id'] + '|' + self.person(author) not in roster:
                self.entry(scene, author)
        return roster

    def resolve(self, scene, text):
        """The people of this scene a lookup may mean.

        A label or #number names exactly one person; so does an id. A name matches everyone who has
        shown it here (now or before, by their own verified profile) or was given it by the operator,
        so a copied name returns both people instead of quietly picking one.
        """
        text = ' '.join(str(text or '').split())
        docs = [d for d in self.ensure_roster(scene).values() if d.get('person') != self.self_id]
        number = re.fullmatch(r'\[?[^#\[\]]*#\s*(\d{1,6})\s*\]?', text)
        if number:
            return [d for d in docs if str(d.get('handle')) == number.group(1)]
        ids = {self.person(text)} | ({self.person(self.account_person(scene['_id'], text))} if text.isdigit() else set())
        by_id = [d for d in docs if d.get('person') in ids]
        if by_id:
            return by_id
        if name_key(text) and name_key(text) == name_key(self.owner_label):
            return [d for d in docs if self.is_owner(d)]
        name = safe_name(text, 60)
        if not name:
            return []
        persons = {d.get('person') for d in docs
                   if name in {self.shown(d), self.named(d.get('person')), safe_name(d.get('card'), 60),
                               safe_name(d.get('nickname'), 60), *(safe_name(p.get('name'), 60) for p in d.get('previous') or [])}}
        for row in self.db.messages.find({'scene_id': scene['_id'], 'direction': 'inbound', '$or': [
                {'event.raw.asuna_peer.' + field: text} for field in ('card', 'nickname', 'display', 'aliases')]},
                {'author': 1, 'scene_id': 1, 'event': 1, 'received_at': 1}).limit(200):
            if self._profile(row) is not None:
                persons.add(self.person(row['author']))
        found = [d for d in docs if d.get('person') in persons]
        if found:
            return found
        key = name_key(text)
        return [d for d in docs if key and key in {name_key(self.shown(d)), name_key(d.get('card')), name_key(d.get('nickname'))}]

    def account_of(self, scene, doc):
        """The platform account behind a person in this scene, for the adapter's @ marker; None when unknown."""
        platform = channel_kinds.of(scene['_id'])
        if not platform:
            return None
        for author in [doc.get('author'), *self.authors_of(doc['person'], [scene['_id']]), doc['person']]:
            if not author:
                continue
            if platform.account_of(author):
                return platform.account_of(author)
            row = self.db.identities.find_one({'person_id': author}, {'account_id': 1})
            if row and platform.ACCOUNT.fullmatch(str(row.get('account_id') or '')):
                return str(row['account_id'])
        return None

    def outbound(self, scene, text):
        """Labels never leave the program; the stored text keeps what she wrote.

        Her @ of a label becomes the adapter's @ marker (@qq:<account>); one that names nobody here is sent as a plain
        @name, never as a number she guessed. A label without @ whose number is someone here becomes their name (the
        name she wrote when the platform gives none, a real @ when neither is known); bracketed text with a number
        that is nobody here is not a label and stays as it is.
        """
        by_handle = {str(d.get('handle')): d for d in self.roster(scene['_id']).values() if d.get('person') != self.self_id}
        kind = channel_kinds.of(scene['_id'])

        def written(match):
            name = ' '.join((match.group('name') or '').split())
            return '' if name == UNKNOWN_NAME else name

        def mention(match):
            doc = by_handle.get(match.group('handle') or match.group('bare'))
            account = self.account_of(scene, doc) if doc else None
            if account:
                return kind.outbound_mention(account)
            name = written(match) if match.group('handle') else ''
            return '@' + name if name else match.group(0).replace('#', '')

        def name(match):
            doc = by_handle.get(match.group('handle'))
            if not doc:
                return match.group(0)
            shown = self.shown(doc) or written(match)
            if shown:
                return shown
            account = self.account_of(scene, doc)
            return kind.outbound_mention(account) if account else match.group(0).replace('#', '')
        return BARE_LABEL.sub(name, LABEL_MENTION.sub(mention, text or ''))

    def authors_of(self, person, scene_ids):
        """Every stored author id in these scenes that is this person (aliases by configuration)."""
        return sorted(a for a in self.db.messages.distinct('author', {'scene_id': {'$in': list(scene_ids)}})
                      if a and self.person(a) == person)

    def row_head(self, row):
        """Who wrote a stored row, as a history result names them: her own rows read as her name."""
        if row.get('author') == self.self_id or row.get('direction') == 'outbound':
            return self.self_name
        scene = self._scene(row.get('scene_id'))
        if not scene:
            return self._author(None, row.get('author'))
        doc = self.entry(scene, row.get('author'), row if row.get('event') else None)
        return self.head(scene['_id'], doc, str(row.get('received_at') or now()))

    def speaker(self, scene, author, row=None, me=None):
        """Label for a stored author (no notes): her own rows read `me` when given."""
        if author == self.self_id:
            return me or self.self_name
        return self.label(self.entry(scene, author, row))

    def transcript(self, scene, row):
        """One platform message as it enters her conversation: the speaker's label line, then the message, indented."""
        event = row.get('event') or {}
        group = event.get('group_context') or {}
        account = (event.get('channel') or {}).get('account_id')
        for number in group.get('mentioned_account_ids') or []:
            if str(number) != str(account):
                profile = self.mentioned(row, number)
                self.entry(scene, self.account_person(scene['_id'], number), row if profile else None, profile)
        self.note_self(scene, row)
        doc = self.entry(scene, row['author'], row)
        # When it was said, on her clock face: the conversation keeps every line, so its age must be readable.
        from .schedule_rules import line_stamp, scene_timezone
        from .caught_up import CAUGHT_UP_WORD, is_caught_up, said_at
        stamp = line_stamp(scene_timezone(self.config, scene), said_at(row))
        if stamp and is_caught_up(row):
            stamp += '（%s）' % CAUGHT_UP_WORD
        lines = [self.head(scene['_id'], doc, str(row.get('received_at') or now())) + (' ' + stamp if stamp else '')]
        parent_id = group.get('reply_message_id')
        parent = self.db.messages.find_one({'_id': parent_id, 'scene_id': scene['_id']},
                                           {'author': 1, 'text': 1}) if parent_id else None
        if parent:
            quote = ' '.join(self.mentions(scene, parent.get('text'), account).split())
            lines.append('  > 回复 %s：%s' % (self.speaker(scene, parent.get('author')), excerpt(quote, REPLY_EXCERPT)))
        body = self.mentions(scene, row.get('text') or '', account)
        lines += ['  ' + line for line in body.split('\n')]
        from .stickers import PICTURE_FETCH_SECONDS, recognized
        from .vision import line_refs, media_source_url, pull_bytes
        task = {'scene_id': scene['_id'], 'scope_key': scene.get('scope_key'), 'policy_epoch': scene.get('policy_epoch')}

        def fetch(entry):               # a sticker whose md5 she does not know: the program matches its picture
            url = media_source_url(self.store, task, self.config, entry)
            return pull_bytes({**entry, 'url': url}, self.config, timeout=PICTURE_FETCH_SECONDS)[0]
        refs = line_refs(row, self.config, lambda entries: recognized(self.store, self.persona, entries, fetch))
        if refs:
            lines.append('  ' + refs)
        return '\n'.join(lines)

    def identity_line(self, scene, row):
        """The current speaker, in full: label, notes, names in quotes, and how the owner is known.

        None when this message carries no verified platform profile: then the label alone stands.
        """
        if self._profile(row) is None:
            return None
        doc = self.entry(scene, row['author'], row)
        if doc.get('person') == self.self_id:
            return None
        parts = []
        card, nickname = safe_name(doc.get('card'), 60), safe_name(doc.get('nickname'), 60)
        if scene.get('kind') == 'group' or card:
            parts.append('群名片「%s」' % card if card else '没设群名片')
        if nickname:
            parts.append('%s 昵称「%s」' % (channel_kinds.of(scene['_id']).TITLE, nickname))
        olds = [safe_name(item.get('name')) for item in (doc.get('previous') or [])][-2:]
        if olds:
            parts.append('在这里用过的名字「%s」' % '」「'.join(olds))
        line = '当前说话人：' + self.head(scene['_id'], doc, str(row.get('received_at') or now()))
        if parts:
            line += '。' + '，'.join(parts)
        if self.is_owner(doc):
            line += '。这是%s本人：按账号认定，不按名字' % self.owner_label
        return line + '。'

    # ---- program blocks ---------------------------------------------------
    def _scene(self, scene_id=None, scope_key=None):
        """A scene document by id or scope (cached), or None for scopes that are not a conversation."""
        cache = self.__dict__.setdefault('_scenes', {})
        key = scene_id or 'scope:' + str(scope_key)
        if key not in cache:
            cache[key] = self.db.scenes.find_one({'_id': scene_id} if scene_id else {'scope_key': scope_key})
        return cache[key]

    def scene_title(self, scene):
        """A conversation as she reads it: 本机私聊, 群聊「name」 or 私聊 with the person's label; never an id."""
        cache = self.__dict__.setdefault('_titles', {})
        if not scene:
            return '别处'
        if scene['_id'] not in cache:
            chat = self.config.get('chat') or {}
            if scene['_id'] == chat.get('scene_id'):
                title = '本机私聊'
            elif scene.get('kind') == 'group':
                row = self.db.messages.find_one({'scene_id': scene['_id'], 'event.raw.group_name': {'$exists': True}},
                                                {'event.raw.group_name': 1}, sort=[('received_at', -1)])
                name = safe_name(((row or {}).get('event') or {}).get('raw', {}).get('group_name'), 30)
                title = '群聊「%s」' % name if name else '一个群聊'
            else:
                others = [d for d in self.roster(scene['_id']).values() if d.get('person') != self.self_id]
                title = '私聊 · ' + self.label(others[0]) if others else '一个私聊'
            cache[scene['_id']] = title
        return cache[scene['_id']]

    def _scope_title(self, scope_key, here):
        """Where a memory belongs, for one not from this conversation; None when it is from here."""
        from .visibility import is_owner_private_scope
        if not scope_key or scope_key == (here or {}).get('scope_key'):
            return None
        if scope_key == 'global-safe':
            return '不分场合'
        if is_owner_private_scope(scope_key):
            return '只在私下'
        return self.scene_title(self._scene(scope_key=scope_key))

    def _author(self, scene, author):
        """A stored author as she reads it; her own rows read 你, the owner reads by the persona's word."""
        if author == self.self_id:
            return '你'
        if scene is None:
            return self.owner_label if self.person(author) == self.owner else '某人'
        return self.speaker(scene, author)

    def _row(self, scene, row):
        if not isinstance(row, dict):
            return row
        here = scene
        scene = self._scene(row['scene_id']) if row.get('scene_id') and row.get('scene_id') != (scene or {}).get('_id') else scene
        account = (scene or {}).get('channel_account_id')
        if 'scene_id' in row:
            # Which conversation a row came from, by name, only when it is not this one.
            if row.pop('scene_id') != (here or {}).get('_id'):
                row['scene'] = self.scene_title(scene)
        row.pop('scope_key', None)
        for key in ('reply_to', 'platform_event_id'):     # platform message numbers; reply_to_message says what it answered
            row.pop(key, None)
        if 'author' in row:
            row['speaker'] = self._author(scene, row.pop('author'))
        if 'mentioned_account_ids' in row:
            ids = row.pop('mentioned_account_ids') or []
            row['mentions'] = ['你' if str(n) == str(account) else
                               self._author(scene, self.account_person((scene or {}).get('_id'), n)) for n in ids]
        if isinstance(row.get('text'), str) and scene:
            row['text'] = self.mentions(scene, row['text'], account)
        if isinstance(row.get('reply_to_message'), dict):
            self._row(scene, row['reply_to_message'])
        return row

    def relabel(self, context, scene, author):
        """Turn the author ids in her context blocks into the labels her conversation uses.

        Rows keep their ids (the program needs them); who wrote a row reads as `speaker`. A recalled
        summary says in words who is in it and whether the current speaker is, instead of listing ids.
        """
        current = self.person(author)
        for key in ('person_id', 'scene_id', 'scope_key', 'policy_epoch'):
            context.pop(key, None)
        context['scene'] = self.scene_title(scene)
        context['speaker'] = self._author(scene, author)
        linked = context.get('linked_scenes_from_program')
        if isinstance(linked, dict):
            linked['readable'] = [self.scene_title(self._scene(s)) for s in linked.get('readable') or []]
            linked['canonical_person'] = self._author(scene, linked.get('canonical_person'))
        shared = context.get('relationship_shared_from_program')
        if isinstance(shared, dict) and 'scope' in shared:
            shared['scope'] = self._scope_title(shared['scope'], None)
        for key in ('delivered_history', 'undelivered_outbound_not_public'):
            for row in context.get(key) or []:
                self._row(scene, row)
        group = context.get('group_continuity_from_program')
        if isinstance(group, dict):
            self._row(scene, group)
            for key in ('related_messages', 'current_speaker_tail'):
                for row in group.get(key) or []:
                    self._row(scene, row)
        experience = context.get('recent_experience_from_program')
        if isinstance(experience, dict):
            for row in experience.get('messages') or []:
                self._row(scene, row)
        if isinstance(context.get('event'), dict) and isinstance(context['event'].get('text'), str):
            context['event']['text'] = self.mentions(scene, context['event']['text'], scene.get('channel_account_id'))
        for fact in context.get('memories') or []:
            self._memory(fact, current, scene)
        return context

    def _memory(self, fact, current, here=None):
        scene = self._scene(fact['scene_id']) if fact.get('scene_id') else self._scene(scope_key=fact.get('scope_key'))
        fact.pop('scene_id', None)
        where = self._scope_title(fact.pop('scope_key', None), here)
        if where:
            fact['scene'] = where
        if 'speaker' in fact:
            fact['speaker'] = self._author(scene, fact['speaker'])
        if isinstance(fact.get('body_markdown'), str) and scene:
            fact['body_markdown'] = self.mentions(scene, fact['body_markdown'], scene.get('channel_account_id'))
        participants = fact.pop('participants', None)
        fact.pop('source_by_speaker', None)
        attribution = fact.pop('attribution', None) or {}
        if participants is None:
            return
        fact['who'] = '、'.join(self._author(scene, p) for p in participants)
        fact['about_current_speaker'] = ('这段里有当前说话人自己说的话' if current in {self.person(p) for p in participants}
                                         else '这段只有别人的话，对当前说话人只是背景')
        corrections = self.corrections(scene, attribution.get('corrections'))
        if corrections:
            fact['corrections'] = corrections

    def corrections(self, scene, items):
        """Program-found corrections (summary_attribution) as sentences with labels."""
        out = []
        for item in items or []:
            who = self._author(scene, item.get('actor'))
            whom = self._author(scene, item.get('target_author')) if item.get('target_author') else None
            said = ' '.join(str(item.get('snippet') or '').split())
            if scene:
                said = self.mentions(scene, said, scene.get('channel_account_id'))
            out.append(('%s 更正了自己' % who if item.get('self_correction') else
                        '%s 更正了 %s' % (who, whom) if whom else '%s 提出了更正' % who)
                       + ('：「%s」' % excerpt(said, REPLY_EXCERPT) if said else ''))
        return out
