"""The project map (docs/map) says what the code says: every module has a description and an area, the generated
pages are current, and every name and link the hand-written answers use exists."""
import ast
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_map', ROOT / 'tools' / 'project_map.py')
project_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project_map)
CORE = ROOT / 'src' / 'asuna'


def test_every_module_has_an_area_and_a_description():
    listed = [name for _, _, names in project_map.AREAS.values() for name in names]
    modules = {path.stem for path in CORE.glob('*.py') if path.stem != '__init__'}
    assert len(listed) == len(set(listed)), 'a module is in two areas'
    assert modules - set(listed) == set(), 'give these modules an area in tools/project_map.py'
    assert set(listed) - modules == set(), 'these modules in tools/project_map.py no longer exist'
    undescribed = [path.relative_to(ROOT).as_posix() for _, _, _, files in project_map.mapped_files()
                   for _, path in files if not project_map.entry(path)[0]]
    assert undescribed == [], 'each module starts with what it owns (a docstring or a /** */ header)'


def test_the_generated_map_is_current():
    pages, index = project_map.render()
    pages['README.md'] = project_map.readme_with(index)
    stale = [name for name, text in pages.items()
             if not (project_map.MAP / name).exists() or (project_map.MAP / name).read_text(encoding='utf-8') != text]
    assert stale == [], 'run python tools/project_map.py and commit docs/map'


def defined(module, dotted):
    """Whether module (a src/asuna file) defines dotted: a top-level name, or a class and one of its methods."""
    tree = ast.parse((CORE / (module + '.py')).read_text(encoding='utf-8'))
    head, *rest = dotted.split('.')
    for node in tree.body:
        names = [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else \
            [target.id for target in getattr(node, 'targets', [getattr(node, 'target', None)]) if isinstance(target, ast.Name)]
        if head in names:
            return not rest or isinstance(node, ast.ClassDef) and any(
                getattr(item, 'name', None) == rest[0] for item in node.body)
    return False


def test_the_answers_name_what_exists():
    readme = (project_map.MAP / 'README.md').read_text(encoding='utf-8').split(project_map.BEGIN)[0]
    modules = {path.stem for path in CORE.glob('*.py')}
    missing = [token for token in re.findall(r'`([a-z_]+(?:\.[A-Za-z_]\w*)+)`', readme)
               if token.split('.')[0] in modules and not defined(token.split('.')[0], token.split('.', 1)[1])]
    missing += [token for token in re.findall(r'`([a-z_]+)`', readme)
                if token in {'notes', 'places', 'grants', 'attend', 'integration'} and token not in modules]
    assert missing == [], 'the map names things the code does not have'
    links = [target.split('#')[0] for target in re.findall(r'\]\(([^)\s]+)\)', readme) if '://' not in target]
    broken = [target for target in links if target and not (project_map.MAP / target).resolve().exists()]
    assert broken == [], 'the map links to files that are not there'
