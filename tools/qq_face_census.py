"""ADR-103: what the faces, stickers and face clicks people send her look like in the stored rows, in counts only.

Usage: python tools/qq_face_census.py [--days 30] [--kind qq] [--max-lines 300000] [--config config/local.json]

Reads the inbound lines of a window from every conversation of one channel kind, through the `messages` and `scenes`
owners, and prints one JSON report. Read-only; writes nothing. The report holds counts, face names and ids (the
platform's table) and segment type tags, never a line's text, a conversation or a person. Exit status 0; 2 when no
line was read (nothing was checked).

What it can see is what Core stored of a line: its text with the adapter's placeholders and the media items
(`type`, `placeholder`, `face_id`, `shape`, ...). NapCat's own segment is not stored; from napcat-qq 0.17.0 on a face's
and an unrecognized segment's item carries `shape` (which fields the platform sent, never their words), so the
report's `shapes` and `throws` fill only from lines that arrived after that version was installed.

This tool is the measuring step of ADR-103 (decision D4); it is removed once the numbers are written into that page.
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asuna import clock                                  # noqa: E402
from asuna.config import load                            # noqa: E402
from asuna.records import messages as message_records    # noqa: E402
from asuna.records import scenes as scene_records        # noqa: E402
from asuna.state import Store                            # noqa: E402

FACE = re.compile(r'\[表情(?::([^\[\]\s:]{1,12}))?\]')            # a face as the adapter writes it, with its name if it has one
STICKER = re.compile(r'\[表情包(?::([^\[\]\n]{1,24}))?\]')        # a sticker likewise
UNREAD = re.compile(r'\[([a-z0-9_-]{1,16})消息（未解析）\]')       # a segment type the adapter has no word for
UNNAMED_CLICK = ('一个表情', '一个认不出名字的小黄脸')                # a click whose emoji the adapter could not name
FIELDS = ['text', 'received_at', 'event.raw.asuna_media', 'event.raw.asuna_notice']
TOP = 20
THROWS = 20
DICE_FACES = ('358', '359')        # 骰子 and 包剪锤 in the faces table: thrown dice may arrive as faces


def top(counter, size=TOP):
    return [[key, count] for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))[:size]]


class Tally:
    """The counts of one run."""

    def __init__(self):
        self.lines = Counter()
        self.media_types = Counter()
        self.faces = Counter()
        self.face_names = Counter()
        self.nameless_ids = Counter()
        self.stickers = Counter()
        self.unread = Counter()
        self.clicks = Counter()
        self.typed = Counter()
        self.shapes = Counter()
        self.throws = []

    def add(self, row):
        """Count one stored inbound line."""
        text = row.get('text') if isinstance(row.get('text'), str) else ''
        raw = (row.get('event') or {}).get('raw') or {}
        block = raw.get('asuna_media') if isinstance(raw.get('asuna_media'), dict) else {}
        items = [item for item in block.get('items') or [] if isinstance(item, dict)]
        notice = raw.get('asuna_notice') if isinstance(raw.get('asuna_notice'), dict) else {}
        self.lines['read'] += 1
        for tag in UNREAD.findall(text):
            self.unread[tag] += 1
        if notice.get('kind') in ('reaction', 'reaction_removed'):
            self.clicks['lines'] += 1
            self.clicks['removed'] += notice['kind'] == 'reaction_removed'
            self.clicks['unnamed_emoji'] += any(words in text for words in UNNAMED_CLICK)
        self.lines['with_media_block'] += bool(items)
        faces = stickers = 0
        for item in items:
            self.media_types[str(item.get('type'))[:16]] += 1
            self.shape(item, str(row.get('received_at') or '')[:16])
            if item.get('type') == 'face':
                faces += 1
                found = FACE.fullmatch(str(item.get('placeholder') or ''))
                self.faces['items'] += 1
                if found and found.group(1):
                    self.faces['named'] += 1
                    self.face_names[found.group(1)] += 1
                else:
                    self.faces['nameless' if found else 'odd'] += 1
                    self.nameless_ids[str(item.get('face_id') or 'no id')[:8]] += 1
            elif item.get('sticker') in ('custom', 'market'):
                stickers += 1
                self.stickers['items'] += 1
                self.stickers[item['sticker']] += 1
                found = STICKER.fullmatch(str(item.get('placeholder') or ''))
                self.stickers['named' if found and found.group(1) else 'unnamed'] += 1
        self.lines['with_face'] += bool(faces)
        self.lines['with_sticker'] += bool(stickers)
        if block.get('truncated') or (block.get('count') or len(items)) != len(items):
            self.lines['truncated_blocks'] += 1
            return                                       # the text holds more placeholders than the items: no count
        self.typed['face_shape'] += max(0, len(FACE.findall(text)) - faces)
        self.typed['sticker_shape'] += max(0, len(STICKER.findall(text)) - stickers)

    def shape(self, item, when):
        """The item's shape (napcat-qq 0.17.0 on), and a dice or rock-paper-scissors throw in order."""
        shape = item.get('shape')
        if not isinstance(shape, str):
            return
        kind = str(item.get('type'))[:16]
        label = 'face:%s' % str(item.get('face_id'))[:8] if kind == 'face' else kind
        self.shapes['%s %s' % (kind, shape[:200])] += 1
        if kind in ('dice', 'rps') or (kind == 'face' and str(item.get('face_id')) in DICE_FACES):
            self.throws.append([when, label, shape.partition('values:')[2][:60]])

    def report(self):
        names = self.face_names
        return {
            'lines': dict(self.lines),
            'faces': {'items': self.faces['items'], 'named': self.faces['named'], 'nameless': self.faces['nameless'],
                      'odd': self.faces['odd'], 'nameless_ids': top(self.nameless_ids), 'distinct_names': len(names), 'names': top(names)},
            'stickers': {key: self.stickers[key] for key in ('items', 'custom', 'market', 'named', 'unnamed')},
            'media_types': top(self.media_types),
            'unread_types': top(self.unread),
            'clicks': {key: self.clicks[key] for key in ('lines', 'removed', 'unnamed_emoji')},
            'typed_lookalikes': {key: self.typed[key] for key in ('face_shape', 'sticker_shape')},
            'shapes': top(self.shapes, 30),
            'throws': sorted(self.throws)[-THROWS:],
        }


def read(store, kind, days, max_lines):
    """(the tally, the scenes read by kind, the first moment, whether the cap cut the read)."""
    since = (clock.now() - timedelta(days=days)).isoformat()
    tally, kinds, cut = Tally(), Counter(), False
    for scene in scene_records.all(store, fields=['_id', 'kind']):
        if not str(scene['_id']).startswith(kind + ':'):
            continue
        kinds[scene.get('kind') or 'other'] += 1
        for row in message_records.inbound(store, scene['_id'], since=since, by=None).each(fields=FIELDS):
            if tally.lines['read'] >= max_lines:
                cut = True
                break
            tally.add(row)
        if cut:
            break
    return tally, dict(kinds), since, cut


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--kind', default='qq', help='the channel kind whose conversations are read')
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--max-lines', type=int, default=300000)
    args = parser.parse_args()
    store = Store(load(args.config))
    try:
        tally, kinds, since, cut = read(store, args.kind, args.days, args.max_lines)
    finally:
        store.close()
    report = {'window': {'since': since, 'days': args.days, 'max_lines': args.max_lines, 'cut': cut},
              'scenes': kinds, **tally.report()}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if tally.lines['read'] else 2


if __name__ == '__main__':
    sys.exit(main())
