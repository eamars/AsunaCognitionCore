"""ADR-060: one name per idea in what a tool shows, and the old names still working for a while.

A tool's parameters are shown by their new name (`do`, `why`, `content`…). The handlers read the names they always
read: a call is mapped to them before anything else looks at it, so records, replays and every reader keep one
vocabulary. A call written with an old name runs and its result says the new one; an old name leaves once her calls
use it fewer than 5 times in a week. A yes/no is the words yes and no, on any model; true and false still work.
"""
from __future__ import annotations

# tool -> {shown name: name the handler reads}. '*' applies to every tool that has the shown name's old field.
RENAMED = {
    '*': {'do': 'op'},
    'group_action': {'do': 'kind', 'why': 'reason'},
    'plan': {'place': 'line'},
    'peer_line': {'place': 'line'},
    'stay_silent': {'why': 'reason'},
    'task': {'why': 'reason'},
    'write_document': {'why': 'reason', 'section': 'sid', 'content': 'body', 'when_shown': 'inject'},
    'update_self': {'why': 'reason', 'content': 'body'},
    'set_policy': {'why': 'reason'},
    'understand_person': {'content': 'body', 'block_hours': 'block'},
    'feel': {'feeling': 'kind', 'unresolved': 'open'},
    'watch': {'how_often': 'mode'},
    'note': {'deliver': 'mode'},
    'sticker': {'use_for': 'when'},
    'quote': {'quote_whom': 'how'},
    'recall': {},
    'write_file': {'content': 'text'},
    'development_write': {'content': 'text'},
    'generate_image': {'list_routes': 'workflows'},
}
# Inside a list or object parameter: (tool, parameter) -> {shown: handler's}.
NESTED = {('recall', 'sections'): {'section': 'sid'}, ('feel', 'edit'): {'feeling': 'kind', 'unresolved': 'open'}}
# (tool, shown name) taking yes/no as words; the handler reads a boolean.
YES_NO = {('feel', 'unresolved'), ('speak', 'force'), ('errand', 'exactly'), ('generate_image', 'list_routes'), ('write_file', 'overwrite'),
          ('development_write', 'overwrite')}
# (tool, object parameter, shown name inside it) taking yes/no as words, as YES_NO for a top-level one.
NESTED_YES_NO = {('feel', 'edit', 'unresolved')}
# feel's decision on a proposal is a `do` of its own (ADR-060 item 8).
FEEL_DECISIONS = ('accept', 'decline', 'edit')
NOTE = '%s 现在叫 %s，这次照办，下次直接用新名字。'
# ADR-069: her calls' old names that are still taken (used 5 times or more in the last week); every other old name in
# her calls is refused by name. The action brain's calls keep taking theirs.
STILL_TAKEN = {('plan', 'op')}
GONE = '%s已经不用了，这次什么都没做；改成新名字再调用。'


def names(tool):
    """{shown: handler's} for a tool."""
    return {**RENAMED['*'], **RENAMED.get(tool, {})}


def _words(value):
    if isinstance(value, str) and value.strip().lower() in ('yes', 'no', 'true', 'false'):
        return value.strip().lower() in ('yes', 'true')
    return value


def old_used(tool, args):
    """The old names this call was written with (each counted toward retiring it)."""
    if not isinstance(args, dict):
        return []
    old_to_new = {old: new for new, old in names(tool).items()}
    return sorted(key for key in args if key in old_to_new and old_to_new[key] not in args)


def retired(tool, olds):
    """The old names among `olds` (old_used) that her calls no longer take."""
    table = names(tool)
    return [(old, next(new for new, was in table.items() if was == old)) for old in olds if (tool, old) not in STILL_TAKEN]


def gone(pairs):
    """The refusal for a call written with retired names."""
    return GONE % '、'.join('%s（现在叫 %s）' % pair for pair in pairs)


def inbound(tool, args):
    """(arguments under the handler's names, notes for each old name she used)."""
    if not isinstance(args, dict):
        return args, []
    table, notes, out = names(tool), [], {}
    old_to_new = {old: new for new, old in table.items()}
    for key, value in args.items():
        if key in table:
            out[table[key]] = value
        else:
            if key in old_to_new and old_to_new[key] not in args:
                notes.append(NOTE % (key, old_to_new[key]))
            out[key] = value
    for (name, field), inner in NESTED.items():
        if name == tool:
            handler = table.get(field, field)
            items = out.get(handler)
            if isinstance(items, list):
                out[handler] = [{inner.get(k, k): v for k, v in item.items()} if isinstance(item, dict) else item
                                for item in items]
            elif isinstance(items, dict):
                out[handler] = {inner.get(k, k): v for k, v in items.items()}
    for name, field in YES_NO:
        if name == tool:
            handler = table.get(field, field)
            if handler in out:
                out[handler] = _words(out[handler])
    for name, field, inner_field in NESTED_YES_NO:
        holder = out.get(table.get(field, field)) if name == tool else None
        handler = NESTED.get((name, field), {}).get(inner_field, inner_field)
        if isinstance(holder, dict) and handler in holder:
            holder[handler] = _words(holder[handler])
    if tool == 'feel' and out.get('op') in FEEL_DECISIONS:
        out['decision'], out['op'] = out['op'], 'adopt'
    return out, notes


def _rename_props(props, table):
    return {next((new for new, old in table.items() if old == key), key): value for key, value in props.items()}


def shown(tool, parameters):
    """A tool's parameters as the model is shown them: new names, yes/no as words. `parameters` is either the
    {name: schema} map of her tools or a JSON schema ({type: object, properties, required}) of the action brain's."""
    if not isinstance(parameters, dict):
        return parameters
    table = names(tool)
    schema = parameters.get('type') == 'object' and isinstance(parameters.get('properties'), dict)
    props = dict(parameters['properties'] if schema else parameters)
    out = _rename_props(props, table)
    for (name, field), inner in NESTED.items():
        if name == tool and field in out:
            spec = dict(out[field])
            if isinstance(spec.get('items'), dict) and isinstance(spec['items'].get('properties'), dict):
                spec['items'] = {**spec['items'], 'properties': _rename_props(spec['items']['properties'], inner)}
                if spec['items'].get('required'):
                    spec['items']['required'] = [next((n for n, o in inner.items() if o == r), r) for r in spec['items']['required']]
            elif isinstance(spec.get('properties'), dict):
                spec['properties'] = _rename_props(spec['properties'], inner)
                for _name, _field, shown_name in NESTED_YES_NO:
                    if (_name, _field) == (name, field) and isinstance(spec['properties'].get(shown_name), dict):
                        yes = {k: v for k, v in spec['properties'][shown_name].items() if k not in ('type', 'oneOf')}
                        spec['properties'] = {**spec['properties'], shown_name: {'type': 'string', **yes, 'enum': ['yes', 'no']}}
            out[field] = spec
    for name, field in YES_NO:
        if name == tool and field in out and isinstance(out[field], dict):
            spec = {k: v for k, v in out[field].items() if k not in ('type', 'oneOf')}
            out[field] = {'type': 'string', **spec, 'enum': ['yes', 'no']}
    if not schema:
        return out
    required = [next((new for new, old in table.items() if old == r), r) for r in parameters.get('required') or []]
    return {**parameters, 'properties': out, **({'required': required} if parameters.get('required') else {})}
