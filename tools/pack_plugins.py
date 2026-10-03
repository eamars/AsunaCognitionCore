"""Build the two ADR-008 plugin artifacts without local state or secrets."""
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import tarfile
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / '.runtime/adr008/packages'
RUNTIME_MODULES = '''__init__ application audit blobs channel_admission channels chat config context
coordinator development dialogue_summary discussion_digest evidence history_query host ingress
integration integration_worker lanes memory memory_indexer model_settings native_settings native_worker native_api native_cognition peer_context
privacy proactive publish queue resources retrieval router sandbox scene_links schedule schedule_rules
self_state skills state summary_attribution summary_trigger tasks tokens vision'''.split()


def bundle_python():
    """An explicit runtime allowlist; no SDK, old Web server, trials or secrets."""
    destination = ROOT / 'packages/cognition-core/python/asuna'
    destination.mkdir(parents=True, exist_ok=True)
    for cache in destination.rglob('__pycache__'):
        if not cache.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unexpected cache outside the package')
        shutil.rmtree(cache)
    expected = {name + '.py' for name in RUNTIME_MODULES}
    for existing in destination.glob('*.py'):
        if existing.name not in expected:
            existing.unlink()
    for filename in sorted(expected):
        shutil.copyfile(ROOT / 'src/asuna' / filename, destination / filename)
    resources = destination / 'resources'
    for group in ('schemas', 'prompts'):
        (resources / group).mkdir(parents=True, exist_ok=True)
    bundle = ROOT / 'docs/development_plans/ADR-001-asuna_v2_v1_handoff'
    for name in ('decision', 'reflection', 'mutation', 'task_result'):
        shutil.copyfile(bundle / 'schemas' / (name + '.schema.json'), resources / 'schemas' / (name + '.schema.json'))
    for name in ('common', 'executor', 'stage_decide', 'stage_monologue', 'stage_reflect', 'stage_self', 'stage_speak'):
        shutil.copyfile(ROOT / 'config/prompts' / (name + '.md'), resources / 'prompts' / (name + '.md'))
    shutil.copyfile(bundle / 'prompts/reflect.md', resources / 'prompts/reflect.md')
    shutil.copyfile(ROOT / 'RUNTIME_API.md', resources / 'RUNTIME_API.md')
    from asuna.development import DEVELOPMENT_TOOLS
    mappings = [[f'src/asuna/{name}.py', f'python/asuna/{name}.py'] for name in RUNTIME_MODULES]
    mappings += [[f'config/prompts/{name}.md', f'python/asuna/resources/prompts/{name}.md']
        for name in ('common', 'executor', 'stage_decide', 'stage_monologue', 'stage_reflect', 'stage_self', 'stage_speak')]
    mappings += [[f'docs/development_plans/ADR-001-asuna_v2_v1_handoff/schemas/{name}.schema.json',
        f'python/asuna/resources/schemas/{name}.schema.json'] for name in ('decision','reflection','mutation','task_result')]
    mappings += [['docs/development_plans/ADR-001-asuna_v2_v1_handoff/prompts/reflect.md',
                  'python/asuna/resources/prompts/reflect.md'], ['RUNTIME_API.md','python/asuna/resources/RUNTIME_API.md']]
    (ROOT / 'packages/cognition-core/runtime-manifest.json').write_text(
        json.dumps({'files': mappings, 'developmentTools': DEVELOPMENT_TOOLS}, indent=2), encoding='utf-8', newline='\n')
    (destination.parent / 'pyproject.toml').write_text('''[build-system]
requires = ["hatchling==1.30.1"]
build-backend = "hatchling.build"
[project]
name = "asuna-cognition-worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx==0.28.1", "pymongo==4.16.0", "jsonschema==4.26.0", "pydantic==2.12.5", "PyYAML==6.0.3"]
[tool.hatch.build.targets.wheel]
packages = ["asuna"]
''', encoding='utf-8')
    subprocess.run([sys.executable, '-c',
        "import sys; import asuna.native_worker; assert 'asuna.dsh_lane' not in sys.modules"],
        cwd=destination.parent, env={**os.environ, 'ASUNA_DATA_ROOT': str(ROOT),
            'PYTHONPATH': str(destination.parent), 'PYTHONDONTWRITEBYTECODE': '1'}, check=True, capture_output=True)


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    native = json.loads((DESTINATION / 'native-inline-manifest.json').read_text(encoding='utf-8'))
    patch_digest = hashlib.sha256((ROOT / 'tools/dsh-inline/rc2-inline.patch').read_bytes()).hexdigest()
    for artifact in native:
        if artifact['patchSha256'] != patch_digest or hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('Rebuild the current native inline extension before packing plugins')
    bundle_python()
    artifacts = list(native)
    for name in ('cognition-core', 'xiaoman'):
        result = subprocess.run(['npm.cmd', 'pack', '--json', '--pack-destination', str(DESTINATION)],
                                cwd=ROOT / 'packages' / name, capture_output=True, text=True, check=True)
        package = json.loads(result.stdout)[0]
        path = DESTINATION / package['filename']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        addressed = path.with_name(path.stem + '-' + digest[:12] + '.tgz')
        if addressed.exists():
            if addressed.read_bytes() != path.read_bytes():
                raise ValueError('Artifact digest collision')
        else:
            shutil.copyfile(path, addressed)
        path = addressed
        with tarfile.open(path, 'r:gz') as archive:
            allowed = ('package/src/', 'package/persona/', 'package/skills/', 'package/python/', 'package/integrations/')
            exact = {'package/package.json', 'package/cordis.patch.yml', 'package/README.md', 'package/runtime-manifest.json', 'package/resources-provenance.json'}
            for entry in archive.getmembers():
                if '/__pycache__/' in entry.name or entry.name.endswith('.pyc'):
                    raise ValueError('Generated bytecode in package: ' + entry.name)
                if not entry.isfile() or not (entry.name in exact or entry.name.startswith(allowed)):
                    raise ValueError('Unexpected packaged entry: ' + entry.name)
        artifacts.append({'name': package['name'], 'path': str(path), 'integrity': package['integrity'],
                          'sha256': digest,
                          'files': [row['path'] for row in package['files']]})
    (DESTINATION / 'manifest.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    print(json.dumps([{k:v for k,v in item.items() if k != 'files'} for item in artifacts], indent=2))


if __name__ == '__main__':
    main()
