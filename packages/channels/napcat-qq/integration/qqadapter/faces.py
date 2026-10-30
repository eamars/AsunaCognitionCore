"""QQ's own faces (小黄脸): id <-> name, from faces.json next to this file.

Inbound a `face` segment reads as `[表情:名字]` (this table's name for its id first, NapCat's own
faceText only where the table has no name for that id); outbound the host's text may carry the same
`[表情:名字]` and each known name becomes a real `face` segment.
A name that is not in the table stays text -- the adapter never guesses an id.
"""
import json
import re
from pathlib import Path

TOKEN = re.compile(r'\[表情:([^\[\]\s:]{1,12})\]')

_TABLE = json.loads((Path(__file__).with_name('faces.json')).read_text(encoding='utf-8'))
BY_ID = {row['id']: row['name'] for row in _TABLE['faces']}
BY_NAME = {row['name']: row['id'] for row in _TABLE['faces']}
# A row may keep its former names in `aliases`: they still resolve to the id, so text written under an old
# name keeps working after a rename. A table name always wins over an alias if the two ever collide.
ALIASES = {alias: row['id'] for row in _TABLE['faces'] for alias in (row.get('aliases') or ())
           if alias not in BY_NAME}
BY_NAME.update(ALIASES)


def clean_name(value):
    """NapCat writes a face's name as '/狗头' or '[捂脸]' (upstream may still say a renamed face's old '/汪汪'); the bare name, or ''."""
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split()).strip('/[]【】 ')[:12]


def name_of(data):
    """A face segment's name: this table's current name for its id, else what NapCat said it is, else ''.

    The table goes first (the owner, 2026-10-30, about face 424): NapCat still writes an old word for a face
    she renamed -- `/续标识` for the one she calls 不对劲 -- and reading the literal first meant her own name
    for it disappeared from what she reads. Her current name is the one shown, so the row's `aliases` are only
    for text she writes. Where the id is not in the table (a face newer than it) or there is no id, what NapCat
    called it is the only name there is, and an alias among her words still maps to the table's current name.
    """
    raw = data.get('raw') if isinstance(data.get('raw'), dict) else {}
    literal = clean_name(raw.get('faceText')) or clean_name(data.get('text') or data.get('Text'))
    return (BY_ID.get(str(data.get('id') or '').strip(), '')
            or (BY_ID[ALIASES[literal]] if literal in ALIASES else literal))
