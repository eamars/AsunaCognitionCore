"""The two schemas of one tool of hers (ADR-108 D4b), and the shapes the program repairs.

The STRICT schema is what the program asks for: her tools' parameters as the model is shown them (role_tools.TOOLS). The
DECLARED schema is what DSH registers, validates and shows the model, and what the plugin's guard checks (tool-args.js): it
is permissive, so that a call whose only fault is a shape the program repairs, or a value the program can name the fix for,
reaches the worker. The worker repairs a copy of the call, checks the copy against the strict schema and collects every
violation with the other layers' problems into one refusal (role_tools.RoleTools.call).

Declared is derived from strict by this module alone, so the two cannot drift:
- a field the program fills in or repairs is no longer required (`REQUIRED_FILLED`), and its description says what the
  program does when it is missing;
- `speak`'s `parts` is declared `json`: a list written as a string is parsed, a part without a `kind` is completed, and the
  part's own fields (and their descriptions) are written into the field's description, which is all the model then reads;
- no field declares an enum: each field's description lists its values, and a value outside them is one problem among the
  others, not a refusal of its own.
What stays declared is what the program cannot repair: a value of the wrong type, a missing field it cannot infer.
"""
from __future__ import annotations

import json
import re

from . import param_names as _names

# (tool, field): what the program does when the field is missing. These fields are not required in the declared schema.
REQUIRED_FILLED = {
    ('write_document', 'doc'): '；不写时按 section 找：你能写的文档里只有一份有那一节就是它，在群里就是 group_notes',
    ('write_document', 'do'): ('；不写时按你写的字段定：有 heading、没有 section 是 append_section，有 section 和 content 是 '
                               'replace_section，只写 visibility、when_shown、tags 这类是 set_tags'),
    ('delegate', 'title'): '；不写时取 brief 的第一句',
}
# Missing, these are not a violation of layer 3: the program fills them in where it can read the state (a document by the
# section's name, a title from the brief) and names what it cannot find as a problem of layer 4, with the candidates.
FILLED_LATER = {('write_document', 'doc'), ('delegate', 'title')}
# Declared as json: the program parses and completes it, then checks it against the strict schema.
JSON_FIELDS = {('speak', 'parts')}
PART_KIND_WORDS = '；kind 不写时按这一条只有的字段定'

TYPE_WORDS = {'string': '一段文字', 'integer': '整数', 'number': '数字', 'boolean': 'true 或 false', 'array': '一个列表',
              'object': '一个对象（{字段: 值}）', 'json': '能写成 JSON 的值'}
HEAD_CHARS = 40
YES_NO = ('yes', 'no')


# ── declared ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _listed(field):
    """The field's description with its enum values in it, and no enum."""
    out = {key: value for key, value in field.items() if key != 'enum'}
    values = field.get('enum')
    if values:
        text = out.get('description', '')
        if not all(str(value) in text for value in values):
            out['description'] = text + '（只能是：%s）' % '、'.join(str(value) for value in values)
    return out


def _without_enums(field):
    """A field with every enum below it listed in a description instead (a list's items, an object's properties)."""
    out = _listed(field)
    if isinstance(out.get('properties'), dict):
        out['properties'] = {key: _without_enums(value) for key, value in out['properties'].items()}
    if isinstance(out.get('items'), dict):
        out['items'] = _without_enums(out['items'])
    return out


def _parts_words(field):
    """`parts` as one description: what the list is, then each part field's own words (the model reads no more)."""
    item = (field.get('items') or {}).get('properties') or {}
    fields = '；'.join(spec.get('description', '') for name, spec in item.items() if name != 'kind' and spec.get('description'))
    kinds = (item.get('kind') or {}).get('enum')
    head = field.get('description', '') + '。一个列表，每条一个对象'
    if kinds:
        head += '，kind 选 ' + '、'.join(kinds)
    return head + ('，各写它的字段：' + fields if fields else '') + PART_KIND_WORDS


def declared(tool, parameters):
    """A tool's parameters as DSH registers them and the model reads them (see the module docstring)."""
    out = {}
    for name, field in parameters.items():
        if (tool, name) in JSON_FIELDS:
            out[name] = {'type': 'json', 'description': _parts_words(field), **({'required': True} if field.get('required') else {})}
            continue
        relaxed = _without_enums(field)
        if (tool, name) in REQUIRED_FILLED:
            relaxed.pop('required', None)
            relaxed['description'] = relaxed.get('description', '') + REQUIRED_FILLED[(tool, name)]
        out[name] = relaxed
    return out


# ── strict ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _head(field):
    """What a missing field is for: the first clause of its description, cut."""
    text = str((field or {}).get('description') or '').strip()
    clause = re.split(r'[。；;\n]', text)[0].strip()
    return '（%s）' % (clause if len(clause) <= HEAD_CHARS else clause[:HEAD_CHARS] + '…') if clause else ''


def _kind_of(value):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return 'null'


def _jsonable(value):
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _fits(kind, value):
    if kind == 'json':
        return _jsonable(value)
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return _kind_of(value) == kind


def _check(field, value, path, found, top=None):
    """Append what is wrong with `value` as a `field` to `found` as (code, text, top-level field); `path` names it as she
    wrote it."""
    kind = field.get('type', 'string')
    if kind == 'string' and field.get('enum') == list(YES_NO) and isinstance(value, bool):
        return                                            # true and false still work for a yes or no
    if not _fits(kind, value):
        found.append(('ARGS_TYPE', '%s 要是%s' % (path, TYPE_WORDS.get(kind, kind)), top))
        return
    values = field.get('enum')
    if values and value not in values:
        found.append(('ARGS_ENUM', '%s 只能是 %s 之一（给的是「%s」）' % (path, '、'.join(str(v) for v in values), str(value)[:HEAD_CHARS]), top))
        return
    if kind == 'object' and isinstance(field.get('properties'), dict):
        _object(field, value, path, found, top)
    elif kind == 'array' and isinstance(field.get('items'), dict):
        for index, item in enumerate(value, 1):
            _check(field['items'], item, '%s 第 %d 条' % (path, index) if path else '第 %d 条' % index, found, top)


def _object(schema, value, path, found, top=None, skip=()):
    properties = schema.get('properties') or {}
    for name, field in properties.items():
        shown = '%s的 %s' % (path, name) if path else name
        here = top or name                                # the field of the call this belongs to
        if name not in value:
            if field.get('required') and not (top is None and name in skip):
                found.append(('ARGS_MISSING', '缺 %s%s' % (shown, _head(field)), here))
            continue
        if value[name] is None and not field.get('required'):
            continue                                      # an optional field written as null is not written
        _check(field, value[name], shown, found, here)
    if schema.get('additionalProperties') is False:
        for name in value:
            if name not in properties:
                found.append(('ARGS_UNDECLARED', '%s 里没有 %s 这个字段' % (path or '参数', str(name)[:HEAD_CHARS]), top))


def violations(tool, parameters, args):
    """Every way `args` fails the strict `parameters` of `tool`, as [(code, text, field)], in field order. Old names that still
    work are read as the new ones; the root is open, so a key nobody declared is not a violation."""
    if not isinstance(args, dict):
        return []
    table = {old: new for new, old in _names.names(tool).items()}
    view = {table[key] if key in table and table[key] not in args else key: value for key, value in args.items()}
    found = []
    _object({'properties': parameters}, view, '', found, skip={field for (name, field) in FILLED_LATER if name == tool})
    return found


# ── repairs ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# A part of speak with no `kind` is the kind its one telling field names (artifact_id is a picture or a file, and line
# a react or a recall: those stay problems).
PART_TELLS = {'text': 'text', 'name': 'sticker', 'who': 'poke', 'face': 'react', 'why': 'recall'}
# speak's own fields, written inside a part by mistake: lifted to the call when the call has none.
SPEAK_OWN = ('quote', 'wait')
TITLE_CHARS = 64
SENTENCE_END = re.compile(r'[。！？!?\n]')


def title_of(brief):
    """The brief's first sentence, cut to the aim (a title is a name, not her words repeated)."""
    first = SENTENCE_END.split(str(brief or '').strip(), 1)[0].strip()
    return first[:TITLE_CHARS] if first else ''


def repair(tool, args):
    """(a copy of the call's arguments repaired, what was repaired): the stateless shapes she writes that the program
    reads as she meant (ADR-108 D4d). Anything it cannot read stays as written and is a problem of the strict schema."""
    if not isinstance(args, dict):
        return args, []
    out, done = dict(args), []
    if tool == 'speak':
        parts = out.get('parts')
        if isinstance(parts, str):
            try:
                parsed = json.loads(parts)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                out['parts'], done = parsed, [*done, 'parts_json']
        if isinstance(out.get('parts'), list):
            fixed = []
            for part in out['parts']:
                if not isinstance(part, dict):
                    fixed.append(part)
                    continue
                part = dict(part)
                for key in SPEAK_OWN:
                    if key in part and out.get(key) is None:
                        out[key] = part.pop(key)
                        done.append('part_lifted_' + key)
                if part.get('kind') is None:
                    kinds = {PART_TELLS[key] for key in PART_TELLS if part.get(key) is not None}
                    if len(kinds) == 1:
                        part['kind'] = kinds.pop()
                        done.append('part_kind')
                fixed.append(part)
            out['parts'] = fixed
    elif tool == 'delegate':
        if not str(out.get('title') or '').strip() and isinstance(out.get('brief'), str) and title_of(out['brief']):
            out['title'] = title_of(out['brief'])
            done.append('title')
    return out, done
