"""QQ's own faces (小黄脸): id <-> name, from faces.json next to this file.

Inbound a `face` segment reads as `[表情:名字]` (NapCat's own faceText first, this table second);
outbound the host's text may carry the same `[表情:名字]` and each known name becomes a real `face`
segment. A name that is not in the table stays text -- the adapter never guesses an id.
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
    """NapCat writes a face's name as '/汪汪' or '[捂脸]'; the bare name, or ''."""
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split()).strip('/[]【】 ')[:12]


def name_of(data):
    """A face segment's name: what NapCat said it is, else the table's name for its id, else ''."""
    raw = data.get('raw') if isinstance(data.get('raw'), dict) else {}
    name = (clean_name(raw.get('faceText')) or clean_name(data.get('text') or data.get('Text'))
            or BY_ID.get(str(data.get('id') or '').strip(), ''))
    # NapCat may still say a renamed face by its old name: show the table's current one
    return BY_ID[ALIASES[name]] if name in ALIASES else name
