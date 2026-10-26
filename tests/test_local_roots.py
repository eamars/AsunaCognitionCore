"""ADR-098: no local root of this computer reaches her character brain. The shared case file
(`fixtures/path_placeholders.json`) runs here and under `node --test` (packages/cognition-core/test/roots.test.js), so
the Python and JavaScript matchers cannot drift; its `tables` are what `local_roots.build` makes of its hosts."""
import json
import os
from pathlib import Path

import pytest

from asuna import local_roots

FIXTURE = Path(__file__).with_name('fixtures') / 'path_placeholders.json'
DOC = json.loads(FIXTURE.read_text(encoding='utf-8'))
TABLES = {name: local_roots.build(facts) for name, facts in DOC['hosts'].items()}


def test_the_fixture_tables_are_what_the_builder_makes():
    built = {name: table.wire() for name, table in TABLES.items()}
    if os.environ.get('ASUNA_REGEN_PATH_FIXTURE'):
        FIXTURE.write_text(json.dumps({**DOC, 'tables': built}, ensure_ascii=False, indent=1) + '\n',
                           encoding='utf-8', newline='\n')
    assert DOC['tables'] == built, 'regenerate: ASUNA_REGEN_PATH_FIXTURE=1 pytest tests/test_local_roots.py'


@pytest.mark.parametrize('case', DOC['cases'], ids=lambda case: case['host'] + ': ' + case['note'])
def test_case(case):
    table = TABLES[case['host']]
    contracted = table.contract(case['input'])
    assert contracted == case['contracted']
    assert table.contract(contracted) == contracted, 'contracting twice is contracting once'
    for place, home in (('home', True), ('public', False)):
        if place in case:
            out = table.outbound(contracted, home)
            assert out == case[place]
            # Expanding then contracting gives the placeholder text back (its separators the host's after expanding).
            assert table.contract(out) in (contracted, case.get('recontracted', contracted))
        if place + '_refused' in case:
            with pytest.raises(local_roots.PathRefused) as refused:
                table.outbound(case['input'], home)
            assert str(refused.value).startswith(case[place + '_refused'] + ':')


@pytest.mark.parametrize('case', DOC['refused'], ids=lambda case: case['note'])
def test_a_filesystem_or_drive_root_refuses_the_table(case):
    with pytest.raises(local_roots.TableRefused) as refused:
        local_roots.build(case['facts'])
    assert str(refused.value).startswith('ROOT_TABLE_REFUSED:')


def test_a_raw_root_refusal_offers_the_string_rewritten():
    with pytest.raises(local_roots.PathRefused) as refused:
        TABLES['windows'].outbound('改 C:\\workplace\\asuna_core\\src\\a.py 里的函数', True)
    assert str(refused.value).endswith('改成这样就能交：\n改 ${ASUNA_WORKSPACE}\\src\\a.py 里的函数')


def test_an_unknown_name_refusal_lists_the_names_there_are():
    with pytest.raises(local_roots.PathRefused) as refused:
        TABLES['linux'].outbound('${ASUNA_WORKSPACEE}/x', True)
    text = str(refused.value)
    assert '${ASUNA_WORKSPACE}' in text and '${ASUNA_HOME}' in text and '${ASUNA_DRIVE_Q}' not in text


def test_the_bare_climb_refusal_says_it_is_this_lines_strict_rule():
    with pytest.raises(local_roots.PathRefused) as refused:
        TABLES['windows'].outbound('cd ..', False)
    assert '这条线从严' in str(refused.value) and '从家里派' in str(refused.value)


def test_the_machine_facts_build_a_table_here():
    facts = local_roots.machine()
    table = local_roots.build(facts)
    wire = table.wire()
    assert wire['roots'] >= 2 and wire['groups'][0] in (local_roots.WORKSPACE, local_roots.DATA,
                                                         local_roots.HOME, local_roots.TEMP, local_roots.DSH_HOME)
    workspace = facts['workspace']
    assert workspace not in table.contract('at ' + workspace + ' and ' + json.dumps(workspace))


def test_no_deployment_variable_is_named_like_a_placeholder():
    """The deployment's own `${ASUNA_…}` variables (deploy/) stay text toward the action brain; one named like a
    placeholder would be expanded as a path, so none may be."""
    import re
    ours = {local_roots.WORKSPACE, local_roots.DATA, local_roots.DSH_HOME, local_roots.HOME, local_roots.TEMP,
            local_roots.PROGRAMS, local_roots.FS, local_roots.LOCAL_PATH, local_roots.USER}
    deploy = Path(__file__).resolve().parents[1] / 'deploy'
    names = {name for path in deploy.rglob('*') if path.is_file()
             for name in re.findall(r'ASUNA_([A-Z0-9_]+)', path.read_text(encoding='utf-8', errors='replace'))}
    assert names, 'deploy/ names no ASUNA_ variable: this test reads the wrong folder'
    clash = sorted(name for name in names if name in ours or name.startswith(local_roots.DRIVE))
    assert not clash, 'a deployment variable is named like a placeholder: ' + ', '.join(clash)
