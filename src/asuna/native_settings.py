"""Native DSH settings migration and model-free runtime validation."""
from copy import deepcopy
from pathlib import Path

from . import channel_kinds
from .config import ROOT, validate_database, validate_endpoint

SECRET_NAMES = {'mongo_uri', 'api_key', 'token', 'password', 'secret', 'access_token'}


def export_settings(config):
    secrets = {}
    def visit(value, path=()):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key.startswith('_'):
                    continue
                if key.lower() in SECRET_NAMES and isinstance(item, str):
                    name = '/'.join((*path, key))
                    secrets[name] = item
                    result[key] = {'$secret': name}
                else:
                    result[key] = visit(item, (*path, key))
            return result
        if isinstance(value, list):
            return [visit(item, (*path, str(i))) for i, item in enumerate(value)]
        return value
    value = deepcopy({k: v for k, v in config.items() if k not in ('character', 'executor')})
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


def runtime_settings(deployment, secrets, models, admission='explicit', *, create_dirs=False):
    value = resolve_secrets(deepcopy(deployment), secrets)
    for key in ('chat', 'embedding'):
        if not isinstance(value.get(key), dict):
            raise ValueError('INVALID_CONFIGURATION_SECTION: ' + key)
    for key in ('scene_id', 'person_id', 'persona', 'workspace'):
        if not isinstance(value['chat'].get(key), str) or not value['chat'][key]:
            raise ValueError('INVALID_LOCAL_CONFIGURATION: ' + key)
    validate_database(value, value['database'])
    validate_endpoint(value['embedding']['base_url'])
    if not isinstance(value['embedding'].get('model'), str) or not value['embedding']['model']:
        raise ValueError('EMBEDDING_MODEL_REQUIRED')
    if type(value.get('channel_port', 8766)) is not int or not 1024 <= value.get('channel_port', 8766) <= 65535:
        raise ValueError('INVALID_CHANNEL_PORT')
    for key in ('provider_idle_timeout_seconds', 'workflow_timeout_seconds'):
        value.setdefault(key, 1800)
        if type(value[key]) not in (int, float) or not 1 <= value[key] <= 86400:
            raise ValueError('INVALID_TIMEOUT: ' + key)
    for key in ('dsh_home', 'workdir'):
        directory = Path(value[key]).resolve()
        if not directory.is_relative_to(ROOT / '.runtime'):
            raise ValueError('RUNTIME_DIRECTORY_OUTSIDE_WORKSPACE: ' + key)
        if create_dirs:
            directory.mkdir(parents=True, exist_ok=True)
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
