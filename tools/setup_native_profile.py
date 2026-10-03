"""Install ADR-008 packages and generate a local-only native Web profile.

Does not start a model turn or consume QQ routes. Preserves saved profile values.
Run after tools/pack_plugins.py. Local providers retain independent lane routes.
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
from asuna.native_settings import export_settings


def profile_patch(config, config_path, shared_action_model=False):
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
        {'id': 'agent-default-model', 'config': {key: routes['character'][key]
            for key in ('provider', 'model', 'reasoningEffort')}},
        {'id': 'session-title-llm', 'disabled': True},
        {'id': 'agent-preset-registry', 'config': {'default': 'asuna-xiaoman'}},
        {'id': 'asuna-publication-floor', 'config': {
            'workspace': str(ROOT), 'python': sys.executable, 'configPath': str(config_path.resolve()),
            'defaultProject': 'xiaoman', 'route': routes['action'],
            'projects': [{'id': 'xiaoman', 'root': str(ROOT / 'packages/xiaoman'), 'format': 'package'},
                         {'id': 'core', 'root': str(ROOT), 'format': 'repository'}]}},
        {'id': 'asuna-cognition-core', 'config': {
            'python': sys.executable, 'workspace': str(ROOT),
            'configPath': str(config_path.resolve()), 'persona': config['chat']['persona'], 'routes': routes,
            **export_settings(config)}},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/local.json')
    parser.add_argument('--shared-action-model', action='store_true', help='Route both brains to the configured action model')
    args = parser.parse_args()
    config = load(args.config)
    base = ROOT / '.runtime/adr008'
    home = base / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'DSH_HOME': str(home), 'DSH_TELEMETRY_DISABLED': '1'}
    dsh = str(ROOT / 'node_modules/.bin/dsh.cmd')
    if not (home / 'profiles/asuna-native/package.json').exists():
        subprocess.run([dsh, '--profile', 'asuna-native', '--from-default-profile', 'web', '--help'],
                       env=env, cwd=ROOT, check=True, capture_output=True)
    manifest = json.loads((base / 'packages/manifest.json').read_text(encoding='utf-8'))
    subprocess.run([dsh, 'plugin', '--profile', 'asuna-native', 'add', *[a['path'] for a in manifest]],
                   env=env, cwd=ROOT, check=True)
    for artifact in manifest:
        installed = home / 'profiles/asuna-native/node_modules' / artifact['name']
        with tarfile.open(artifact['path'], 'r:gz') as archive:
            for entry in archive.getmembers():
                if entry.isfile() and (installed / entry.name.removeprefix('package/')).read_bytes() != archive.extractfile(entry).read():
                    raise ValueError('Installed artifact does not match: ' + entry.name)
    patch = base / 'native.patch.yml'
    patch.write_text(yaml.safe_dump(profile_patch(config, args.config, args.shared_action_model),
                                   allow_unicode=True, sort_keys=False), encoding='utf-8')
    # Initial composition belongs in the editable profile layer. A command-line
    # overlay would silently override native Settings writes on every launch.
    editable = home / 'profiles/asuna-native/cordis.patch.yml'
    prior = yaml.safe_load(editable.read_text(encoding='utf-8')) if editable.exists() else []
    defaults = profile_patch(config, args.config, args.shared_action_model)
    def merge(base, override):
        if isinstance(base, dict) and isinstance(override, dict):
            return {**base, **{key: merge(base.get(key), val) for key, val in override.items()}}
        return override
    by_id = {row.get('id'): row for row in prior or [] if 'id' in row}
    merged = [merge(row, by_id.get(row['id'], {})) for row in defaults]
    ids = {row['id'] for row in defaults}
    merged.extend(row for row in prior or [] if row.get('id') not in ids)
    # Older installers put an Asuna route's output limit into this native
    # service. It is not part of AgentDefaultModel.Config: removing it during
    # a native picker save causes an ordinary lifecycle reload instead of a
    # volatile model update. Output limits remain in the two Asuna routes.
    for row in merged:
        if row.get('id') == 'agent-default-model':
            row.get('config', {}).pop('maxTokens', None)
    editable.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding='utf-8')
    credential_values = {'ASUNA_NATIVE_' + lane.upper() + '_KEY': config[source].get('api_key') or 'local-no-auth'
        for lane, source in (('character', 'executor' if args.shared_action_model else 'character'), ('action', 'executor'))}
    subprocess.run(['node', str(ROOT / 'tools/import_native_credentials.mjs')], cwd=ROOT,
                   input=json.dumps({'home': str(home), 'values': credential_values}), text=True,
                   capture_output=True, check=True)
    activation_path = base / 'activation.json'
    selected = json.loads(activation_path.read_text(encoding='utf-8')) if activation_path.exists() else {'projects': {}, 'active': {}}
    for artifact in manifest:
        project = 'core' if artifact['name'] == '@asuna/cognition-core' else 'xiaoman'
        installed = home / 'profiles/asuna-native/node_modules' / artifact['name']
        selected.setdefault('projects', {})[project] = {
            **selected.get('projects', {}).get(project, {}), 'project': project, 'state': 'APPLIED',
            'artifact': artifact['path'], 'sha256': artifact['sha256'], 'packageRoot': str(installed),
            'receipt_id': 'native-install-' + artifact['sha256'],
            **({'workerPath': str(installed / 'python')} if project == 'core' else {})}
    temporary = activation_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(activation_path)
    (base / 'launch.json').write_text(json.dumps({'config': str(args.config.resolve()),
        'shared_action_model': args.shared_action_model, 'native_credentials': True}), encoding='utf-8')
    print('Installed native profile. Start with start-asuna.cmd --port 8780')


if __name__ == '__main__':
    main()
