"""ADR-009 P0 offline cases (T0.1–T0.3, T0.7, T0.9–T0.11). No MongoDB, model or network.

Prints one ``PASS <id>`` / ``FAIL <id> <reason>`` / ``SKIP <id> <reason>`` line per case.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def git_grep(*args):
    proc = subprocess.run(['git', 'grep', '-n', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    return [line for line in proc.stdout.splitlines() if line]


@case
def t0_1_runtime_without_design_docs():
    """Import the worker from a copy that has no docs/ at all; prepare packaged resources without npm."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copytree(ROOT / 'src', tmp / 'src', ignore=shutil.ignore_patterns('__pycache__'))
        assert not (tmp / 'docs').exists()
        proc = subprocess.run([sys.executable, '-c', 'import asuna.coordinator, asuna.tasks, asuna.memory, asuna.native_worker'],
                              cwd=tmp, env={**os.environ, 'PYTHONPATH': str(tmp / 'src'), 'ASUNA_DATA_ROOT': str(tmp),
                                            'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-400:]
        import pack_plugins
        mappings = pack_plugins.prepare_resources(tmp / 'out' / 'asuna')
        out = tmp / 'out' / 'asuna' / 'resources'
        assert (out / 'schemas/decision.schema.json').is_file()
        prompts = {p.name for p in (ROOT / 'src/asuna/resources/prompts').glob('*.md')}
        assert prompts >= {'common.md', 'executor.md', 'stage_decide.md', 'stage_monologue.md', 'stage_speak.md'}
        assert prompts == {p.name for p in (out / 'prompts').glob('*.md')}
        assert all(not source.startswith('docs/') for source, _ in mappings)


@case
def t0_2_no_design_doc_paths_in_runtime():
    hits = git_grep('docs/development_plans', '--', 'src', 'packages', 'tools/pack_plugins.py')
    assert not hits, hits[:3]


class FakeIdentities:
    def find(self, _query=None):
        return []


class FakeDB:
    identities = FakeIdentities()
    scenes = FakeIdentities()


def owner_config():
    return {'chat': {'scene_id': 'local-dm', 'person_id': 'owner'},
            'canonical_persons': {'demo-user-1': 'owner'},
            'channels': {'demo': {'routes': {
                'owner-dm': {'scene_id': 'demo-dm-owner', 'person_id': 'demo-user-1', 'sender_id': '100001',
                             'target': {'type': 'dm', 'id': '100001'}},
                'other-dm': {'scene_id': 'demo-dm-other', 'person_id': 'demo-user-2', 'sender_id': '100002',
                             'target': {'type': 'dm', 'id': '100002'}},
                'group': {'scene_id': 'demo-group-1', 'target': {'type': 'group', 'id': '200001'},
                          'members': {'100001': {'person_id': 'demo-user-1'}}}}}}}


@case
def t0_3_session_class_truth_table_and_link_downgrade():
    from asuna import visibility as v
    config, db = owner_config(), FakeDB()
    table = [({'_id': 'local-dm', 'kind': 'dm'}, 'owner', v.OWNER_PRIVATE),
             ({'_id': 'demo-dm-owner', 'kind': 'dm'}, 'demo-user-1', v.OWNER_PRIVATE),
             ({'_id': 'demo-group-1', 'kind': 'group'}, 'demo-user-1', v.PUBLIC),
             ({'_id': 'demo-group-1', 'kind': 'group'}, 'owner', v.PUBLIC),
             ({'_id': 'demo-dm-other', 'kind': 'dm'}, 'demo-user-2', v.PUBLIC)]
    for scene, person, expected in table:
        assert v.session_class(config, db, scene, person) == expected, (scene, person)
    # Links never raise a class: a group linked to the owner's scene stays public.
    linked = {**owner_config(), 'context_links': {'demo-group-1': ['local-dm', 'demo-dm-other'],
                                                  'local-dm': ['demo-dm-owner'], 'demo-dm-owner': ['local-dm']}}
    assert v.session_class(linked, db, {'_id': 'demo-group-1', 'kind': 'group'}, 'owner') == v.PUBLIC
    cleaned, rejected = v.without_link_downgrades(linked)
    assert rejected == [{'reader': 'demo-group-1', 'target': 'local-dm', 'code': 'LINK_PRIVACY_DOWNGRADE'}], rejected
    assert cleaned['context_links'] == {'demo-group-1': ['demo-dm-other'], 'local-dm': ['demo-dm-owner'],
                                        'demo-dm-owner': ['local-dm']}
    assert linked['context_links']['demo-group-1'] == ['local-dm', 'demo-dm-other'], 'input config is not mutated'
    route = {**owner_config()}
    route['channels']['demo']['routes']['group']['read_scenes'] = ['demo-dm-owner']
    cleaned, rejected = v.without_link_downgrades(route)
    assert [r['target'] for r in rejected] == ['demo-dm-owner']
    assert cleaned['channels']['demo']['routes']['group']['read_scenes'] == []
    # Retrieval never accepts an owner-private scope as an ordinary or linked scope.
    assert v.readable_scope('owner-private:demo', v.PUBLIC) is False
    assert v.readable_scope('owner-private:demo', v.OWNER_PRIVATE) is True
    assert v.readable_scope('scene:x', v.PUBLIC) is True


@case
def t0_3_host_applies_link_refusal():
    source = (ROOT / 'src/asuna/host.py').read_text(encoding='utf-8')
    assert 'without_link_downgrades(self.config)' in source and "'config.link_rejected'" in source


@case
def t0_7_terminal_adapter_removed():
    hits = git_grep('-E', r'def terminal|def chat\(|prompt_toolkit|prompt-toolkit', '--', 'src', 'pyproject.toml')
    assert not hits, hits[:3]
    uv = ROOT / '.venv' / ('Scripts' if os.name == 'nt' else 'bin') / ('uv.exe' if os.name == 'nt' else 'uv')
    uv = str(uv) if uv.exists() else shutil.which('uv')
    if uv:
        proc = subprocess.run([uv, 'lock', '--check'], cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-300:]
    agents = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    assert 'There is no terminal chat adapter; all interaction goes through the Web UI.' in agents
    assert 'The core is persona-agnostic.' in agents and 'Personal data stays local.' in agents


@case
def t0_8_personal_scan_all_tracked_is_zero():
    proc = subprocess.run([sys.executable, str(ROOT / 'tools/check_staged_secrets.py'), '--personal', '--all'],
                          cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert proc.returncode == 0
    summary = proc.stdout.strip().splitlines()[-1]
    assert summary == 'personal-scan: 0 hit(s)', summary + ' (' + str(len([l for l in proc.stdout.splitlines() if not l.startswith(('report-only:', 'personal-scan'))])) + ' counted lines)'
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    assert 'config/personal-denylist.local.txt' in ignore and 'config/group-*.json' in ignore


@case
def t0_9_core_is_persona_neutral():
    hits = git_grep('-niE', 'xiaoman|小满', '--', 'src/asuna', 'packages/cognition-core', 'config', 'tools')
    assert not hits, hits[:3]
    for prompt in sorted((ROOT / 'src/asuna/resources/prompts').glob('*.md')):
        text = prompt.read_text(encoding='utf-8')
        # No gendered pronoun for the persona ("其他"/"他人" are ordinary words).
        assert '她' not in text and not re.search(r'(?<!其)他(?!人)', text), prompt.name


@case
def t0_10_unset_timezone_is_explicit_utc():
    from asuna import schedule_rules as rules
    source = (ROOT / 'src/asuna/schedule_rules.py').read_text(encoding='utf-8')
    assert 'DEFAULT_TIMEZONE' not in source
    zone = rules.scene_timezone({}, {'_id': 'local-dm'})
    clock = rules.local_clock(zone, '2026-01-01T00:00:00+00:00')
    assert (zone['name'], zone['source']) == ('UTC', 'unset')
    assert clock['tz_note'] == '未设置时区，以 UTC 显示' and clock['utc_offset_minutes'] == 0
    configured = rules.scene_timezone({'timezone': 'Etc/GMT-3'}, {'_id': 'local-dm'})
    assert (configured['name'], configured['source']) == ('Etc/GMT-3', 'config')
    assert rules.local_clock(configured, '2026-01-01T00:00:00+00:00')['utc_offset_minutes'] == 180


@case
def t0_11_launcher_profile_and_config():
    node = shutil.which('node')
    if not node:
        raise SkipCase('node not installed')
    # An installed demo profile is bound to its generated config; otherwise resolve the template.
    demo_config = 'config/demo.local.json' if (ROOT / 'config/demo.local.json').exists() else 'config/demo.example.json'
    demo = subprocess.run([node, 'tools/asuna-launch.mjs', 'ui', '--profile', 'asuna-demo', '--config',
                           demo_config, '--dry-run'], cwd=ROOT, capture_output=True, text=True)
    assert demo.returncode == 0, demo.stderr[-300:]
    value = json.loads(demo.stdout)
    assert value['profile'] == 'asuna-demo' and value['database'].startswith('asuna_v2_demo_')
    assert Path(value['config']) == (ROOT / demo_config).resolve()
    assert Path(value['home']).resolve().is_relative_to((ROOT / '.runtime/adr008/profiles/asuna-demo').resolve())
    if not (ROOT / 'config/local.json').exists():
        raise SkipCase('no local config for the default-profile half')
    plain = subprocess.run([node, 'tools/asuna-launch.mjs', 'ui', '--dry-run'], cwd=ROOT, capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k not in ('ASUNA_PROFILE', 'ASUNA_CONFIG')})
    assert plain.returncode == 0, plain.stderr[-300:]
    value = json.loads(plain.stdout)
    assert value['profile'] == 'asuna-native' and Path(value['config']) == (ROOT / 'config/local.json').resolve()
    assert Path(value['home']) == (ROOT / '.runtime/adr008/home').resolve() and value['port'] == 8780
    env = subprocess.run([node, 'tools/asuna-launch.mjs', 'ui', '--dry-run'], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, 'ASUNA_PROFILE': 'asuna-demo', 'ASUNA_CONFIG': demo_config})
    assert json.loads(env.stdout)['profile'] == 'asuna-demo'


class SkipCase(Exception):
    pass


def main():
    for fn in CASES:
        name = fn.__name__
        try:
            fn()
            print('PASS', name)
        except SkipCase as exc:
            print('SKIP', name, exc)
        except Exception as exc:
            detail = str(exc) or traceback.format_exc().strip().splitlines()[-1]
            print('FAIL', name, detail[:300].replace('\n', ' '))


if __name__ == '__main__':
    main()
