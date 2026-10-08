"""Native DSH settings migration and model-free runtime validation."""
from copy import deepcopy
import re

from . import channel_kinds
from .config import DATA, local_workspace, validate_database, validate_endpoint

# A secret's key, by substring (settings.js uses the same pattern): its value goes to DSH's credential store and the
# settings keep a reference named like an environment variable (ADR-010 D6).
SECRET_KEY = re.compile(r'mongo_uri|api_?key|token|password|secret', re.I)


def credential_ref(path):
    """The credential store's name for the secret at this settings path: ASUNA_EMBEDDING_API_KEY."""
    return 'ASUNA_' + re.sub(r'[^A-Za-z0-9]+', '_', '_'.join(path)).strip('_').upper()


def export_settings(config):
    secrets = {}
    def visit(value, path=()):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key.startswith('_'):
                    continue
                if SECRET_KEY.search(key) and isinstance(item, str):
                    if not item:
                        continue        # an empty secret is no secret: the key is left out (e.g. a keyless endpoint)
                    name = credential_ref((*path, key))
                    secrets[name] = item
                    result[key] = {'$secret': name}
                else:
                    result[key] = visit(item, (*path, key))
            return result
        if isinstance(value, list):
            return [visit(item, (*path, str(i))) for i, item in enumerate(value)]
        return value
    value = deepcopy({k: v for k, v in config.items() if k not in ('character', 'executor', 'dsh_home', 'workdir')})
    value.get('chat', {}).pop('workspace', None)
    adapter = value.get('integration', {}).get('adapter_config', {})
    channel_id = adapter.get('host', {}).get('channel_id')
    if channel_id:
        channel_kinds.of_channel(channel_id).strip_derived(adapter)
    adapter.get('host', {}).pop('token', None)
    value.setdefault('vision', {})
    value.setdefault('context_links', {})
    value.setdefault('canonical_persons', {})
    value.setdefault('channel_port', 8766)
    return {'deployment': visit(value), 'secrets': secrets}


def resolve_secrets(value, secrets):
    if isinstance(value, dict):
        if set(value) == {'$secret'}:
            if value['$secret'] not in secrets:
                raise ValueError('CREDENTIAL_NOT_CONFIGURED: ' + value['$secret'])
            return secrets[value['$secret']]
        return {key: resolve_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_secrets(item, secrets) for item in value]
    return value


def runtime_settings(deployment, secrets, models, admission='explicit', *, create_dirs=False, persona=None):
    # `search` is the Host's web search provider's (search.js): its credential may be unset, and the worker never reads it.
    value = resolve_secrets(deepcopy({key: item for key, item in deployment.items() if key != 'search'}), secrets)
    value.setdefault('chat', {})          # every local-chat key has a default below
    for key in ('chat', 'embedding'):
        if not isinstance(value.get(key), dict):
            raise ValueError('INVALID_CONFIGURATION_SECTION: ' + key)
    # A new profile's local chat: one owner in one local scene, talking with the selected persona.
    for key, default in (('scene_id', 'local'), ('person_id', 'owner'), ('persona', persona)):
        if default:
            value['chat'].setdefault(key, default)
    if isinstance(value.get('database'), str):
        value.setdefault('allowed_databases', [value['database']])
    for key in ('scene_id', 'person_id', 'persona'):
        if not isinstance(value['chat'].get(key), str) or not value['chat'][key]:
            raise ValueError('INVALID_LOCAL_CONFIGURATION: ' + key)
    # Where the profile writes is its data folder's business (ADR-010 D3), not a setting.
    value['chat']['workspace'] = str(local_workspace())
    for key in ('database', 'mongo_uri'):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError('DEPLOYMENT_SETTING_REQUIRED: ' + key)
    validate_database(value, value['database'])
    if not isinstance(value['embedding'].get('base_url'), str) or not value['embedding']['base_url']:
        raise ValueError('DEPLOYMENT_SETTING_REQUIRED: embedding.base_url')
    validate_endpoint(value['embedding']['base_url'])
    if not isinstance(value['embedding'].get('model'), str) or not value['embedding']['model']:
        raise ValueError('EMBEDDING_MODEL_REQUIRED')
    if type(value.get('channel_port', 8766)) is not int or not 1024 <= value.get('channel_port', 8766) <= 65535:
        raise ValueError('INVALID_CHANNEL_PORT')
    for key in ('provider_idle_timeout_seconds', 'workflow_timeout_seconds'):
        value.setdefault(key, 1800)
        if type(value[key]) not in (int, float) or not 1 <= value[key] <= 86400:
            raise ValueError('INVALID_TIMEOUT: ' + key)
    if create_dirs:
        local_workspace().mkdir(parents=True, exist_ok=True)
    from . import sandbox_backend
    sandbox_backend.validate(value.get('sandbox'))
    if admission not in ('explicit', 'automatic'):
        raise ValueError('INVALID_CHANNEL_ADMISSION')
    # The DSH catalog owns model capability validation. Legacy provider
    # endpoints and their separate model-settings file are not loaded here.
    for lane, key in (('character', 'character'), ('action', 'executor')):
        value[key] = {**models[lane], 'transport_read_timeout_seconds': value['provider_idle_timeout_seconds'],
                      'token_counter': 'native-host'}
    for channel_id, channel in value.get('channels', {}).items():
        kind = channel_kinds.of_channel(channel_id)
        channel['admission'] = admission
        # A route that names no workspace gets one in this profile's data folder, as an admitted one does: a
        # configuration written elsewhere cannot know where that folder is.
        for route_id, route in channel.get('routes', {}).items():
            folder = DATA / 'channels' / (channel_id + '-' + route_id)
            grants = route.get('members', {}).items() if route.get('target', {}).get('type') == 'group' else [(None, route)]
            for sender, grant in grants:
                if isinstance(grant, dict) and not grant.get('workspace'):
                    grant['workspace'] = str(folder / sender if sender else folder)
                    grant.setdefault('read_only_paths', [])
        for key in ('blocked_senders', 'blocked_groups'):
            if not isinstance(channel.get(key, []), list) or any(not isinstance(v, str) or not kind.ACCOUNT.fullmatch(v)
                    for v in channel.get(key, [])):
                raise ValueError('INVALID_CHANNEL_BLOCK_LIST: ' + key)
    integration = value.get('integration', {})
    if integration.get('enabled'):
        from .integration import validate_profile
        validate_profile(value)
    adapter = integration.get('adapter_config', {})
    channel_id = adapter.get('host', {}).get('channel_id')
    if channel_id:
        channel = value.get('channels', {}).get(channel_id)
        if not channel:
            raise ValueError('ADAPTER_CHANNEL_NOT_CONFIGURED')
        adapter['host']['token'] = channel['token']
        channel_kinds.of_channel(channel_id).adapter_config(adapter, channel)
    return value
