"""One-time safe configuration bootstrap: parse allowlisted values, never execute them."""
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEGACY = Path('C:/workspace/kazusa_cognition_core_prod/.env')
ALLOWED = {'MONGODB_URI', 'MONGODB_DB_NAME', 'EMBEDDING_BASE_URL', 'EMBEDDING_API_KEY', 'EMBEDDING_MODEL'}
values = {}
if LEGACY.exists():
    for line in LEGACY.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*', line)
        if match and match[1] in ALLOWED:
            value = match[2]
            if len(value) > 1 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            if '$(' in value or '`' in value or '${' in value:
                raise ValueError('Unexpanded configuration must be supplied explicitly')
            values[match[1]] = value
config = {
    'mongo_uri': os.environ.get('ASUNA_MONGODB_URI') or values.get('MONGODB_URI'),
    'database': 'asuna_cognition_core_v2',
    'allowed_databases': ['asuna_cognition_core_v2'],
    'test_database_prefix': 'asuna_v2_test_',
    'legacy_database': values.get('MONGODB_DB_NAME'),
    'embedding': {'base_url': 'http://192.168.2.8:1234/v1', 'api_key': values.get('EMBEDDING_API_KEY', ''), 'model': values.get('EMBEDDING_MODEL'), 'query_prefix': 'search_query: ', 'document_prefix': 'search_document: '},
    'character': {'base_url': 'http://192.168.2.13:8083/v1', 'model': 'gemma4-26b-a4b-it-qat-vision-262144-qat-mtp', 'sampling': {'temperature': 0.7, 'top_p': 0.95, 'seed': 20260919}, 'max_tokens': 4096},
    'executor': {'base_url': 'http://192.168.2.13:1919/v1', 'model': 'qwen38-next-uncensored-freetoken-vision', 'sampling': {'temperature': 0.2, 'top_p': 0.95, 'seed': 20260919}, 'max_tokens': 32768},
    'dsh_home': str(ROOT / '.runtime' / 'asuna-dsh'),
    'workdir': str(ROOT / '.runtime' / 'work'),
    'local_only': True,
    'publish_adapter': 'local-idempotent-sink',
    'source': {'connections': 'explicit user input', 'embedding_model_and_key': str(LEGACY), 'legacy_config_sha256': hashlib.sha256(LEGACY.read_bytes()).hexdigest() if LEGACY.exists() else None},
}
(ROOT / 'config').mkdir(exist_ok=True)
target = ROOT / 'config/local.json'
if target.exists():
    raise SystemExit('Refusing to overwrite existing local config')
target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
for name in ('dsh_home', 'workdir'):
    Path(config[name]).mkdir(parents=True, exist_ok=True)
print('Created ignored local config and isolated directories; no credentials printed.')
