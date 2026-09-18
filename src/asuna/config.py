from __future__ import annotations
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'asuna_v2_v1_handoff'


def load(path: str | Path = 'config/local.json') -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    validate_database(value, value['database'])
    for lane in ('character', 'executor', 'embedding'):
        validate_endpoint(value[lane]['base_url'])
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
    for name in ('character', 'executor', 'embedding'):
        out[name].pop('api_key', None)
    return out
