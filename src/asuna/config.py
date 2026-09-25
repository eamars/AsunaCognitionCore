from __future__ import annotations
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'docs/development_plans/ADR-001-asuna_v2_v1_handoff'


def prompt_path(config: dict, name: str) -> Path:
    return Path(config.get('prompts_dir', BUNDLE / 'prompts')) / name


def redact_text(text: str, config: dict) -> str:
    values = [config.get('mongo_uri', '')]
    values += [config.get(lane, {}).get('api_key', '') for lane in ('character', 'executor', 'embedding')]
    values += [channel.get('token', '') for channel in config.get('channels', {}).values()]
    def credentials(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and any(word in key.lower() for word in ('token', 'password', 'secret', 'key')):
                    values.append(item)
                else:
                    credentials(item)
        elif isinstance(value, list):
            for item in value: credentials(item)
    credentials(config.get('integration', {}).get('adapter_config', {}))
    for value in sorted(filter(None, values), key=len, reverse=True):
        text = text.replace(value, '[凭据已隐藏]')
    return text


def load(path: str | Path = 'config/local.json') -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    from .model_settings import settings_path, validate
    override = settings_path(path)
    if override.exists():
        models = json.loads(override.read_text(encoding='utf-8'))
        if set(models) != {'character', 'executor'}:
            raise ValueError('INVALID_MODEL_SETTINGS')
        value.update({lane: validate(models[lane]) for lane in models})
    for lane in ('character', 'executor'):
        value[lane] = validate(value[lane])
    value['_model_settings_path'] = str(override)
    integration_path = Path(path).parent / 'integration.local.json'
    if integration_path.exists():
        value['integration'] = json.loads(integration_path.read_text(encoding='utf-8'))
    channel_path = Path(path).parent / 'asuna-channel.local.json'
    if channel_path.exists():
        channels = json.loads(channel_path.read_text(encoding='utf-8'))
        if channels.get('enabled') is True:
            value['channels'] = channels['channels']
            value['channel_port'] = channels.get('port', 8766)
        # 跨场景只读联动（A2）：这两个键写在通道文件顶层也要能到 store.config 里。
        # 原样带过，不校验 route 内部键；形状不对的条目由 scene_links 在读的时候照实丢掉。
        for key in ('context_links', 'canonical_persons'):
            if key in channels:
                value[key] = channels[key]
    validate_database(value, value['database'])
    for lane in ('character', 'executor', 'embedding'):
        validate_endpoint(value[lane]['base_url'])
    value.setdefault('provider_idle_timeout_seconds',1800)
    value.setdefault('workflow_timeout_seconds',1800)
    for lane in ('character','executor'):
        value[lane].setdefault('transport_read_timeout_seconds',1800)
    for key in ('dsh_home', 'workdir'):
        p = Path(value[key]).resolve()
        if not p.is_relative_to((ROOT / '.runtime').resolve()):
            raise ValueError(f'{key} must be isolated inside this repository .runtime')
        p.mkdir(parents=True, exist_ok=True)
    return value


def validate_database(config: dict, name: str) -> str:
    if name == config.get('legacy_database') or not (
        name in config['allowed_databases'] or name.startswith('asuna_v2_test_')
    ) or any(c in name for c in '/\\. $\x00'):
        raise ValueError('DATABASE_NOT_AUTHORIZED')
    return name


def validate_endpoint(url: str) -> None:
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or p.username or p.password or p.query or p.fragment:
        raise ValueError('INVALID_LOCAL_ENDPOINT')
    # Literal addresses only: no DNS rebinding or inferred localhost services.
    ip = ipaddress.ip_address(p.hostname or '')
    if not (ip.is_private or ip.is_loopback) or ip.is_unspecified:
        raise ValueError('CLOUD_ROUTE_FORBIDDEN')


def redacted(config: dict) -> dict:
    out = json.loads(json.dumps(config))
    out.pop('mongo_uri', None)
    out.pop('legacy_database', None)
    if 'integration' in out:
        out['integration'].pop('adapter_config', None)
    for channel in out.get('channels', {}).values():
        channel.pop('token', None)
    for name in ('character', 'executor', 'embedding'):
        out[name].pop('api_key', None)
    return out
