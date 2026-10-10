"""Write the project map (docs/map): what each module owns and what it offers, from the code's own docstrings.

The map has three levels. docs/map/README.md answers "how is it done" questions in words, with entry points (written
by hand) and an index of every module by area, one line each (written here). One page per area lists each module's
docstring and its public functions and classes with their first doc line, no code. The code itself is the third
level. Run after changing a module's docstring or its public names; tests/test_project_map.py fails while the map
is stale.

  python tools/project_map.py           write docs/map
  python tools/project_map.py --check   exit 1 when docs/map is not what the code says
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / 'docs' / 'map'
BEGIN, END = '<!-- map:modules -->', '<!-- /map:modules -->'

# Python modules of the core by area (src/asuna). A module missing here fails the test: give it an area.
AREAS = {
    'hosting': ('Entry and hosting', 'The worker the Host plugin starts, its store, configuration and audit.', [
        'native_worker', 'host', 'application', 'cli', 'config', 'native_settings', 'lanes', 'queue', 'state',
        'audit', 'evidence', 'testing', 'restarts', 'host_stops', 'host_lease', 'local_time']),
    'turn': ('A turn', 'From an input to her words: queueing, context, her tools, the checks, publishing.', [
        'ingress', 'router', 'coordinator', 'context', 'context_budget', 'render', 'role_tools', 'tool_args',
        'answers', 'publish', 'lines', 'chat', 'handover']),
    'people': ('Groups and people', 'Who is talking, whether she joins in, her places, notes between conversations.', [
        'attend', 'proactive', 'rhythm', 'people', 'peer_context', 'familiarity', 'group_admin', 'group_members',
        'watches', 'places', 'focus', 'notes', 'scene_links', 'visibility', 'understanding', 'private_words']),
    'memory': ('Memory', 'What she remembers, how it is recalled, her documents, mood and blobs.', [
        'memory', 'memory_indexer', 'retrieval', 'history_query', 'dialogue_summary', 'discussion_digest',
        'summary_trigger', 'summary_attribution', 'documents', 'self_state', 'affect', 'blobs', 'privacy']),
    'persona': ('Persona', 'The persona package, its model and policies, her skills and ideas.', [
        'persona_model', 'persona_data', 'persona_jobs', 'policy', 'skills']),
    'channels': ('Channels and pictures', 'The channel API, platform kinds, stickers, seeing and sending pictures.', [
        'channels', 'channel_kinds', 'channel_admission', 'caught_up', 'stickers', 'vision', 'outbound_media', 'animated']),
    'work': ('Work and tools', 'The action brain\'s tasks, grants, schedules, sandbox, development and integrations.', [
        'tasks', 'grants', 'schedule', 'schedule_rules', 'sandbox', 'sandbox_backend', 'development', 'credentials',
        'image_generation', 'svg_render', 'integration', 'integration_fetch', 'integration_image',
        'integration_import', 'developer_inbox']),
    'page': ('The Web page\'s data', 'What the Web page reads and changes through the worker.', [
        'native_api', 'native_cognition', 'native_ui']),
}
SKIP_PARTS = {'tests', 'test', 'vendor', 'node_modules', '__pycache__'}


def first_sentence(text):
    """The summary: the docstring's first sentence (a full stop, not "e.g.", ends it)."""
    text = ' '.join((text or '').strip().split('\n\n')[0].split())
    found = re.search(r'(.+?(?<!e\.g)(?<!i\.e)[.。])(\s|$)', text)
    return (found.group(1) if found else text)[:240]


def first_paragraph(text):
    return ' '.join((text or '').strip().split('\n\n')[0].split())


def python_entry(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith('_'):
            kind = 'class' if isinstance(node, ast.ClassDef) else 'def'
            methods = [(item.name, first_sentence(ast.get_docstring(item))) for item in node.body
                       if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and not item.name.startswith('_')] if kind == 'class' else []
            symbols.append((kind, node.name, first_sentence(ast.get_docstring(node)), methods))
    return ast.get_docstring(tree) or '', symbols


JSDOC = re.compile(r'/\*\*(.*?)\*/', re.S)
EXPORT = re.compile(r'(?:/\*\*((?:(?!\*/).)*?)\*/\s*)?export\s+(?:default\s+)?(?:async\s+)?(function|class|const)\s+(\w+)', re.S)
# A class method at the class body's indent, with the /** */ right above it when there is one.
METHOD = re.compile(r'(?:/\*\*((?:(?!\*/).)*?)\*/\s*\n)?^  (?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(\w+)\s*\([^)]*\)\s*\{',
                    re.S | re.M)


def js_methods(source, name):
    """The public methods of class `name`: its body runs to the next line that closes at column 0."""
    start = re.search(r'^(?:export\s+)?(?:default\s+)?class\s+%s\b[^\n]*\n' % name, source, re.M)
    if not start:
        return []
    end = re.search(r'^\}', source[start.end():], re.M)
    body = source[start.end():start.end() + (end.start() if end else len(source))]
    return [(method, first_sentence(js_text(comment or ''))) for comment, method in METHOD.findall(body)
            if method not in ('constructor', 'if', 'for', 'while', 'switch', 'catch') and not method.startswith('_')]


def js_text(comment):
    return '\n'.join(line.strip().lstrip('*').strip() for line in comment.splitlines()).strip()


def js_entry(path):
    source = path.read_text(encoding='utf-8')
    head = JSDOC.match(source.lstrip())
    doc = js_text(head.group(1)) if head else ''
    symbols = [('class' if kind == 'class' else 'def', name, first_sentence(js_text(comment or '')),
                js_methods(source, name) if kind == 'class' else [])
               for comment, kind, name in EXPORT.findall(source)]
    return doc, symbols


def entry(path):
    return python_entry(path) if path.suffix == '.py' else js_entry(path)


def mapped_files():
    """(page, title, about, [(display name, path)]) for every page of the map."""
    core = ROOT / 'src' / 'asuna'
    pages = [(key, title, about, [(name, core / (name + '.py')) for name in names])
             for key, (title, about, names) in AREAS.items()]
    plugin = sorted((ROOT / 'packages' / 'cognition-core' / 'src').glob('*.js'))
    pages.append(('plugin', 'The Host plugin', 'The DSH plugin (JavaScript): the worker it starts, her sessions, '
                  'the action brain\'s children, the publication floor and the Web page contributions.',
                  [(path.name, path) for path in plugin]))
    # A package's empty __init__.py says nothing; a kind module (python/<kind>/__init__.py) has its docstring.
    channels = sorted(path for path in (ROOT / 'packages' / 'channels').rglob('*')
                      if path.suffix in ('.py', '.js', '.mjs') and not SKIP_PARTS & set(path.parts)
                      and (path.name != '__init__.py' or path.stat().st_size))
    pages.append(('channel-packages', 'Channel packages', 'Each platform plugin: its kind module (ids and formats), '
                  'its Host plugin and its adapter.',
                  [(path.relative_to(ROOT / 'packages' / 'channels').as_posix(), path) for path in channels]))
    tools = sorted(path for path in (ROOT / 'tools').iterdir() if path.suffix in ('.py', '.mjs') and path.is_file())
    pages.append(('tools', 'Tools', 'Commands for setup, packing, launching, probes and maintenance.',
                  [(path.name, path) for path in tools]))
    return pages


def link(path, page_dir):
    return Path('../..', path.relative_to(ROOT)).as_posix() if page_dir == MAP else path.relative_to(ROOT).as_posix()


def render():
    """{relative path under docs/map: text} for every generated page, and the README's module index."""
    pages, index = {}, []
    for key, title, about, files in mapped_files():
        lines = ['# %s' % title, '', about, '',
                 'Generated by `tools/project_map.py` from each module\'s docstring and public names; '
                 '[the map](README.md) says how things fit together.', '']
        index += ['', '### [%s](%s.md)' % (title, key), '', about, '']
        for name, path in files:
            doc, symbols = entry(path)
            target = link(path, MAP)
            index.append('- [`%s`](%s) — %s' % (name, target, first_sentence(doc) or '(no description)'))
            lines += ['## `%s`' % name, '', '[%s](%s)' % (path.relative_to(ROOT).as_posix(), target), '',
                      first_paragraph(doc) or '(no description)', '']
            for kind, symbol, said, methods in symbols:
                lines.append('- %s `%s`%s' % (kind, symbol, ' — ' + said if said else ''))
                lines += ['  - `%s`%s' % (method, ' — ' + told if told else '') for method, told in methods]
            lines.append('')
        pages[key + '.md'] = '\n'.join(lines).rstrip() + '\n'
    return pages, '\n'.join(index).strip()


def readme_with(index):
    readme = (MAP / 'README.md').read_text(encoding='utf-8')
    start, end = readme.index(BEGIN) + len(BEGIN), readme.index(END)
    return readme[:start] + '\n' + index + '\n' + readme[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    pages, index = render()
    pages['README.md'] = readme_with(index)
    stale = [name for name, text in pages.items()
             if not (MAP / name).exists() or (MAP / name).read_text(encoding='utf-8') != text]
    if args.check:
        if stale:
            print('stale: ' + ', '.join(stale) + '; run python tools/project_map.py')
        return 1 if stale else 0
    for name in stale:
        (MAP / name).write_text(pages[name], encoding='utf-8', newline='\n')
    print('wrote ' + (', '.join(stale) or 'nothing (up to date)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
