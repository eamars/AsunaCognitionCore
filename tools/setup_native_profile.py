"""Install the core, one persona package and its channel packages into a local-only native Web profile.

Does not start a model turn or consume platform routes. Preserves saved profile values.
Run after tools/pack_plugins.py --persona <dir> --channel <dir>. Models are DSH providers (its Models page); the
brains are chosen on the Asuna settings card. Persona and channel packages are arguments; the core names neither.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import yaml

from asuna import channel_kinds
from asuna.config import ROOT, load
from asuna.native_settings import credential_ref, export_settings


def profile_base(profile):
    """The owner's original profile keeps its existing location; others are isolated."""
    base = ROOT / '.runtime/adr008'
    return base if profile == 'asuna-native' else base / 'profiles' / profile


def data_folder(profile):
    """(dataRoot, stateDir) of a profile set up from this checkout (ADR-010 D3). The owner's profile keeps its
    folders where they are: data in the checkout's .runtime, floor state in its adr008. Another profile's data
    folder is its own base, with the floor state at the top."""
    return (ROOT / '.runtime', 'adr008') if profile == 'asuna-native' else (profile_base(profile), None)


def with_pnpm(env):
    """DSH installs plugins with `pnpm` from PATH; without one, use the pnpm Node ships through corepack.

    tools/asuna-launch.mjs gives the Web host the same shim, so a restart can activate a published candidate.
    """
    if shutil.which('pnpm', path=env.get('PATH')):
        return env
    node = shutil.which('node', path=env.get('PATH'))
    corepack = node and Path(node).with_name('corepack.cmd' if os.name == 'nt' else 'corepack')
    if not corepack or not corepack.exists():
        return env
    shim = ROOT / '.runtime/bin'
    shim.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        (shim / 'pnpm.cmd').write_text(f'@"{corepack}" pnpm %*\r\n', encoding='utf-8', newline='')
    else:
        (shim / 'pnpm').write_text(f'#!/bin/sh\nexec "{corepack}" pnpm "$@"\n', encoding='utf-8')
        (shim / 'pnpm').chmod(0o755)
    return {**env, 'PATH': str(shim) + os.pathsep + env.get('PATH', ''), 'COREPACK_ENABLE_DOWNLOAD_PROMPT': '0'}


def persona_package(directory):
    """Read the persona package's npm name, project id and agent preset from its own files."""
    directory = directory.resolve()
    package = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
    patch = yaml.safe_load((directory / 'cordis.patch.yml').read_text(encoding='utf-8')) or []
    presets = [row['config']['id'] for item in patch for row in item.get('insert', [])
               if row.get('name') == '@asuna/cognition-core/preset']
    if len(presets) != 1:
        raise ValueError('PERSONA_PACKAGE_PRESET_REQUIRED')
    project = package['name'].rsplit('/', 1)[-1]
    if not project.replace('-', '').isalnum():
        raise ValueError('PERSONA_PACKAGE_NAME_INVALID')
    return {'name': package['name'], 'project': project, 'preset': presets[0], 'root': directory}


def channel_package(directory):
    """A channel package's npm name, project id and kind module (its one python/<module> package)."""
    directory = directory.resolve()
    package = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
    modules = [p.name for p in (directory / 'python').iterdir() if (p / '__init__.py').is_file()]
    if len(modules) != 1:
        raise ValueError('CHANNEL_PACKAGE_MODULE_REQUIRED')
    project = package['name'].rsplit('/', 1)[-1]
    if not project.replace('-', '').isalnum():
        raise ValueError('CHANNEL_PACKAGE_NAME_INVALID')
    return {'name': package['name'], 'project': project, 'root': directory,
            'python': directory / 'python', 'module': modules[0]}


def move_secrets(core):
    """Settings written before ADR-010 D6 carried plaintext under `secrets` and path-named references
    ({"$secret": "embedding/api_key"}). Rename each reference to its credential-store name and hand back the values
    to store, so the settings keep only references. Returns {ref: value}."""
    old = core.pop('secrets', None) or {}
    moved = {}
    def visit(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if not (isinstance(item, dict) and set(item) == {'$secret'}):
                    visit(item)
                    continue
                name = item['$secret']
                if name in old and not old[name]:
                    del value[key]          # an empty secret is no secret (the store refuses empty values)
                    continue
                ref = name if name.startswith('ASUNA_') else credential_ref(name.split('/'))
                item['$secret'] = ref
                if name in old:
                    moved[ref] = old[name]
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(core.get('deployment', {}))
    return moved


def profile_patch(config, config_path, persona, profile='asuna-native', channels=(), channel_admission=None):
    data_root, state_dir = data_folder(profile)
    return [
        {'id': 'session-title-llm', 'disabled': True},
        # Her web_search and web_fetch go through the cognition core's providers (search.js, fetch.js).
        {'id': 'web', 'config': {'searchProvider': 'asuna-search', 'fetchProvider': 'asuna-fetch'}},
        {'id': 'agent-preset-registry', 'config': {'default': persona['preset']}},
        {'id': 'asuna-publication-floor', 'config': {
            'dataRoot': str(data_root), 'python': sys.executable,
            'defaultProject': persona['project'],
            **({'stateDir': state_dir} if state_dir else {}),
            'projects': [{'id': persona['project'], 'root': str(persona['root']), 'format': 'package'},
                         *({'id': c['project'], 'root': str(c['root']), 'format': 'package'} for c in channels),
                         {'id': 'core', 'root': str(ROOT), 'format': 'repository'}]}},
        {'id': 'asuna-cognition-core', 'config': {
            'python': sys.executable, 'persona': config['chat']['persona'],
            'deployment': export_settings(config)['deployment'],
            # A first choice only: a value saved on the settings card wins over these defaults.
            **({'channelAdmission': channel_admission} if channel_admission else {})}},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/local.json')
    parser.add_argument('--persona-package', type=Path, required=True,
                        help='persona package directory (its packed artifact must be in the pack manifest)')
    parser.add_argument('--channel-package', type=Path, action='append', default=[],
                        help='channel package directory, e.g. packages/channels/napcat-qq (repeatable; packed like the persona)')
    parser.add_argument('--profile', default='asuna-native', help='DSH profile name (asuna-demo for the demo environment)')
    parser.add_argument('--port', type=int, help='Web port this profile starts on (recorded; default: as before, else 8780)')
    parser.add_argument('--channel-admission', choices=('explicit', 'automatic'),
                        help='channel admission for a profile that has not saved one (default explicit)')
    args = parser.parse_args()
    if not args.profile.replace('-', '').isalnum():
        raise ValueError('INVALID_PROFILE_NAME')
    if args.port is not None and not 1024 <= args.port <= 65535:
        raise ValueError('INVALID_WEB_PORT')
    config = load(args.config)
    persona = persona_package(args.persona_package)
    channels = [channel_package(directory) for directory in args.channel_package]
    # Exported settings drop what a channel's kind derives, so its module must be importable here.
    channel_kinds.load([{'python': c['python'], 'module': c['module']} for c in channels])
    base = profile_base(args.profile)
    home = base / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = with_pnpm({**os.environ, 'DSH_HOME': str(home), 'DSH_TELEMETRY_DISABLED': '1'})
    dsh = ['node', str(ROOT / 'node_modules/@deepseek-ai/dsh/lib/bin.js')]        # any OS, as the launcher runs it
    if not (home / 'profiles' / args.profile / 'package.json').exists():
        subprocess.run([*dsh, '--profile', args.profile, '--from-default-profile', 'web', '--help'],
                       env=env, cwd=ROOT, check=True, capture_output=True)
    packed = json.loads((ROOT / '.runtime/adr008/packages/manifest.json').read_text(encoding='utf-8'))
    # The reviewed native rendering extension (tools/dsh-inline) is installed with the plugins it serves.
    names = {'@asuna/cognition-core', persona['name'], *(c['name'] for c in channels),
             *(a['name'] for a in packed if a.get('kind') == 'native-rendering-extension')}
    manifest = [a for a in packed if a['name'] in names]
    if {a['name'] for a in manifest} != names:
        raise ValueError('PACKED_ARTIFACT_MISSING: run tools/pack_plugins.py --persona ' + str(args.persona_package)
                         + ''.join(' --channel ' + str(d) for d in args.channel_package))
    subprocess.run([*dsh, 'plugin', '--profile', args.profile, 'add', *[a['path'] for a in manifest]],
                   env=env, cwd=ROOT, check=True)
    for artifact in manifest:
        installed = home / 'profiles' / args.profile / 'node_modules' / artifact['name']
        with tarfile.open(artifact['path'], 'r:gz') as archive:
            for entry in archive.getmembers():
                if entry.isfile() and (installed / entry.name.removeprefix('package/')).read_bytes() != archive.extractfile(entry).read():
                    raise ValueError('Installed artifact does not match: ' + entry.name)
    # Initial composition belongs in the editable profile layer. A command-line
    # overlay would silently override native Settings writes on every launch.
    editable = home / 'profiles' / args.profile / 'cordis.patch.yml'
    prior = yaml.safe_load(editable.read_text(encoding='utf-8')) if editable.exists() else []
    defaults = profile_patch(config, args.config, persona, args.profile, channels, args.channel_admission)
    stored = {}
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
        # ADR-010 D3: the data folder replaced the checkout as the place a profile writes to.
        if row.get('id') in ('asuna-publication-floor', 'asuna-cognition-core'):
            row.get('config', {}).pop('workspace', None)
            row.get('config', {}).pop('configPath', None)
        if row.get('id') == 'asuna-cognition-core':
            stored.update(move_secrets(row.get('config', {})))
            deployment = row.get('config', {}).get('deployment', {})
            for key in ('dsh_home', 'workdir'):
                deployment.pop(key, None)
            deployment.get('chat', {}).pop('workspace', None)
    # Which packages are development projects is composition, not a saved setting:
    # an installed channel package must become a project even on an existing profile.
    floor = next(row for row in defaults if row['id'] == 'asuna-publication-floor')['config']
    for row in merged:
        if row.get('id') == 'asuna-publication-floor':
            row['config'].update(defaultProject=floor['defaultProject'], projects=floor['projects'])
        # So is which providers back web_search and web_fetch: an existing profile takes the current pins.
        if row.get('id') == 'web':
            row['config'] = dict(next(r for r in defaults if r['id'] == 'web')['config'])
    editable.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding='utf-8')
    # Business secrets go to DSH's credential store; existing values there are kept (import_native_credentials.mjs).
    credential_values = dict(export_settings(config)['secrets'])
    credential_values.update(stored)
    subprocess.run(['node', str(ROOT / 'tools/import_native_credentials.mjs')], cwd=ROOT,
                   input=json.dumps({'home': str(home), 'values': credential_values}), text=True,
                   capture_output=True, check=True)
    activation_path = base / 'activation.json'
    selected = json.loads(activation_path.read_text(encoding='utf-8')) if activation_path.exists() else {'projects': {}, 'active': {}}
    projects = {persona['name']: persona['project'], **{c['name']: c['project'] for c in channels}}
    for artifact in manifest:
        if artifact.get('kind') == 'native-rendering-extension':
            continue                        # a profile dependency, not a development project
        project = 'core' if artifact['name'] == '@asuna/cognition-core' else projects[artifact['name']]
        installed = home / 'profiles' / args.profile / 'node_modules' / artifact['name']
        current = selected.setdefault('projects', {}).get(project, {})
        if current.get('sha256') == artifact['sha256'] and current.get('state') in ('APPLIED', 'ACTIVE'):
            continue                        # this package is already the one selected: keep its state and history
        value = {'project': project, 'state': 'APPLIED',
                 'artifact': artifact['path'], 'sha256': artifact['sha256'], 'packageRoot': str(installed),
                 'receipt_id': 'native-install-' + artifact['sha256'],
                 **({'workerPath': str(installed / 'python')} if project == 'core' else {})}
        # As her own publications do (floor.js): the last selection that ran, so a start that never comes up
        # returns to it (asuna-launch.mjs, ADR-011 §6.4).
        previous = (selected.get('active') or {}).get(project)
        if previous and previous.get('sha256') != artifact['sha256']:
            value['previous'] = {k: v for k, v in previous.items() if k not in ('previous', 'boots')}
        selected['projects'][project] = value
    temporary = activation_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(activation_path)
    # What the launcher needs to install this checkout again when it changes (asuna-launch.mjs): the packages this
    # profile is composed of, and the packed digests now installed.
    relative = lambda directory: Path(os.path.relpath(directory.resolve(), ROOT)).as_posix()
    # The Web port is the profile's own (ADR-020): given here, else the one recorded before, else the launcher's 8780.
    try:
        port = args.port or json.loads((base / 'launch.json').read_text(encoding='utf-8')).get('port')
    except (OSError, ValueError):
        port = args.port
    (base / 'launch.json').write_text(json.dumps({'config': str(args.config.resolve()), **({'port': port} if port else {}),
        'profile': args.profile,
        'setup': {'persona_package': relative(args.persona_package),
                  'channel_packages': [relative(directory) for directory in args.channel_package]},
        'installed': {artifact['name']: artifact['sha256'] for artifact in manifest}}, indent=2), encoding='utf-8')
    suffix = '' if args.profile == 'asuna-native' else ' --profile %s --config %s' % (args.profile, args.config)
    print('Installed native profile. Start with start-asuna.cmd (Windows) or ./start-asuna.sh' + suffix
          + ' (Web port %s)' % (port or 8780))


if __name__ == '__main__':
    main()
