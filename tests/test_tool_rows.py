"""Her tool rows on the Web page read the call as DSH records it: the parameter names she is shown (ADR-060), not the
names the handlers read. A row that looks for a handler's name finds nothing and cannot open."""
import re
from pathlib import Path

from asuna import param_names, role_tools, tasks

CLIENT = (Path(__file__).resolve().parents[1] / 'packages/cognition-core/src/client.js').read_text(encoding='utf-8')


def table(name):
    body = re.search(r'const %s = \{(.*?)\};' % name, CLIENT, re.S).group(1)
    return dict(re.findall(r"'?([\w.]+)'?: '(\w+)'", body))


def shown(row):
    """The parameter names she is shown for the tool behind a row."""
    options = {row_name: key.split('.')[0] for key, row_name in table('OPTION_ROWS').items()}
    tool = options.get(row, row)
    action = {spec['name']: spec for spec in (tasks.ASK_TOOL, tasks.PROGRESS_TOOL)}
    spec = role_tools.TOOLS.get(tool) or action[tool]
    return set(spec['parameters'] if tool in role_tools.TOOLS else param_names.shown(tool, spec['parameters']))


def test_every_field_a_row_reads_is_one_she_is_shown():
    for which in ('TOOL_SUMMARY', 'TOOL_BODY'):
        for row, field in table(which).items():
            assert field in shown(row), '%s reads %s.%s, which she is not shown' % (which, row, field)


def test_old_names_and_options_follow_the_program():
    # A call by an old name still runs, so a row falls back to it: the old name of each field it reads.
    old, options = table('OLD_NAMES'), {row: key.split('.')[0] for key, row in table('OPTION_ROWS').items()}
    fields = re.search(r'const OPTION_FIELDS = \{(.*?)\};', CLIENT, re.S).group(1)
    client = {tool: dict(re.findall(r"(\w+): '(\w+)'", inner)) for tool, inner in re.findall(r'(\w+): \{([^}]*)\}', fields)}
    read = [(options.get(row, row), field) for which in ('TOOL_SUMMARY', 'TOOL_BODY') for row, field in table(which).items()]
    read += [(tool, field) for tool, by_field in client.items() for field in ('do', *by_field)]
    for tool, field in read:
        handler = param_names.names(tool).get(field, field)
        assert handler == field or old.get(field) == handler, (tool, field)
    for tool, by_field in client.items():
        to_shown = {handler: new for new, handler in param_names.names(tool).items()}
        assert by_field == {to_shown.get(f, f): op for f, op in role_tools.OP_FIELDS[tool].items()}, tool
