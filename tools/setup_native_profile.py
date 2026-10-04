"""Install the core plus one persona package into a local-only native Web profile.

Does not start a model turn or consume QQ routes. Preserves saved profile values.
Run after tools/pack_plugins.py --persona <dir>. Local providers retain independent
lane routes. The persona package is an argument; the core names no persona.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import yaml

from asuna.config import ROOT, load


def profile_base(profile):
    """The owner's original profile keeps its existing location; others are isolated."""
    base = ROOT / '.runtime/adr008'
    return base if profile == 'asuna-native' else base / 'profiles' / profile


def persona_package(directory):
    """Read the persona package's npm name, project id and agent preset from its own files."""
    directory = directory.resolve()
    package = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
    patch = yaml.safe_load((directory / 'cordis.patch.yml').read_text(encoding='utf-8')) or []
    presets = [row['config']['id'] for item in patch for row in item.get('insert', [])
               if row.get('name') == '@deepseek-ai/dsh-agent-preset']
    if len(presets) != 1:
        raise ValueError('PERSONA_PACKAGE_PRESET_REQUIRED')
    project = package['name'].rsplit('/', 1)[-1]
    if not project.replace('-', '').isalnum():
        raise ValueError('PERSONA_PACKAGE_NAME_INVALID')
    return {'name': package['name'], 'project': project, 'preset': presets[0], 'root': directory}


def profile_patch(config, config_path, persona, shared_action_model=False, state_dir=None):
    providers, routes = {}, {}
    for lane, source in (('character', 'executor' if shared_action_model else 'character'), ('action', 'executor')):
        model = config[source]
        provider = 'asuna-' + lane
        providers[provider] = {
            'api': model['api'], 'baseURL': model['base_url'], 'compat': model['compat'],
            'apiKeyEnv': 'ASUNA_NATIVE_' + lane.upper() + '_KEY',
            'timeoutMs': config['provider_idle_timeout_seconds'] * 1000,
            'streamIdleTimeoutMs': config['provider_idle_timeout_seconds'] * 1000,
            'models': [{'id': model['model'], 'contextWindow': model['context_window'],
                        'maxTokens': model['max_tokens'], 'reasoningEfforts': model['reasoning_efforts'],
                        'input': model.get('input_modalities', ['text'])}],
        }
        routes[lane] = {'provider': provider, 'model': model['model'],
                        'reasoningEffort': model['reasoning_effort'], 'maxTokens': model['max_tokens']}
    return [
        {'id': 'llm-pi-ai', 'config': {'providers': providers}},
        {'id': 'agent-default-model', 'config': routes['character']},
        {'id': 'session-title-llm', 'disabled': True},
        {'id': 'agent-preset-registry', 'config': {'default': persona['preset']}},
        {'id': 'asuna-publication-floor', 'config': {
            'workspace': str(ROOT), 'python': sys.executable, 'configPath': str(config_path.resolve()),
            'defaultProject': persona['project'], 'route': routes['action'],
            **({'stateDir': state_dir} if state_dir else {}),
            'projects': [{'id': persona['project'], 'root': str(persona['root']), 'format': 'package'},
                         {'id': 'core', 'root': str(ROOT), 'format': 'repository'}]}},
        {'id': 'asuna-cognition-core', 'config': {
            'python': sys.executable, 'workspace': str(ROOT),
            'configPath': str(config_path.resolve()), 'persona': config['chat']['persona'], 'routes': routes}},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/local.json')
    parser.add_argument('--persona-package', type=Path, required=True,
                        help='persona package directory (its packed artifact must be in the pack manifest)')
    parser.add_argument('--profile', default='asuna-native', help='DSH profile name (asuna-demo for the demo environment)')
    parser.add_argument('--shared-action-model', action='store_true', help='Route both brains to the configured action model')
    args = parser.parse_args()
    if not args.profile.replace('-', '').isalnum():
        raise ValueError('INVALID_PROFILE_NAME')
    config = load(args.config)
    persona = persona_package(args.persona_package)
    base = profile_base(args.profile)
    state_dir = None if args.profile == 'asuna-native' else base.relative_to(ROOT).as_posix()
    home = base / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'DSH_HOME': str(home), 'DSH_TELEMETRY_DISABLED': '1'}
    dsh = str(ROOT / 'node_modules/.bin/dsh.cmd')
    if not (home / 'profiles' / args.profile / 'package.json').exists():
        subprocess.run([dsh, '--profile', args.profile, '--from-default-profile', 'web', '--help'],
                       env=env, cwd=ROOT, check=True, capture_output=True)
    packed = json.loads((ROOT / '.runtime/adr008/packages/manifest.json').read_text(encoding='utf-8'))
    manifest = [a for a in packed if a['name'] in ('@asuna/cognition-core', persona['name'])]
    if {a['name'] for a in manifest} != {'@asuna/cognition-core', persona['name']}:
        raise ValueError('PACKED_ARTIFACT_MISSING: run tools/pack_plugins.py --persona ' + str(args.persona_package))
    subprocess.run([dsh, 'plugin', '--profile', args.profile, 'add', *[a['path'] for a in manifest]],
                   env=env, cwd=ROOT, check=True)
    for artifact in manifest:
        installed = home / 'profiles' / args.profile / 'node_modules' / artifact['name']
        with tarfile.open(artifact['path'], 'r:gz') as archive:
            for entry in archive.getmembers():
                if entry.isfile() and (installed / entry.name.removeprefix('package/')).read_bytes() != archive.extractfile(entry).read():
                    raise ValueError('Installed artifact does not match: ' + entry.name)
    patch = base / 'native.patch.yml'
    patch.write_text(yaml.safe_dump(profile_patch(config, args.config, persona, args.shared_action_model, state_dir),
                                   allow_unicode=True, sort_keys=False), encoding='utf-8')
    # Initial composition belongs in the editable profile layer. A command-line
    # overlay would silently override native Settings writes on every launch.
    editable = home / 'profiles' / args.profile / 'cordis.patch.yml'
    prior = yaml.safe_load(editable.read_text(encoding='utf-8')) if editable.exists() else []
    defaults = profile_patch(config, args.config, persona, args.shared_action_model, state_dir)
    def merge(base, override):
        if isinstance(base, dict) and isinstance(override, dict):
            return {**base, **{key: merge(base.get(key), val) for key, val in override.items()}}
        return override
    by_id = {row.get('id'): row for row in prior or [] if 'id' in row}
    merged = [merge(row, by_id.get(row['id'], {})) for row in defaults]
    ids = {row['id'] for row in defaults}
    merged.extend(row for row in prior or [] if row.get('id') not in ids)
    editable.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (base / 'launch.json').write_text(json.dumps({'config': str(args.config.resolve()),
        'profile': args.profile, 'shared_action_model': args.shared_action_model}), encoding='utf-8')
    suffix = '' if args.profile == 'asuna-native' else ' --profile %s --config %s' % (args.profile, args.config)
    print('Installed native profile. Start with start-asuna.cmd' + suffix + ' --port 8780')


if __name__ == '__main__':
    main()
