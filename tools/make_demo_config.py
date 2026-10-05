"""Create the ignored demo config (ADR-009 §0.3) from config/demo.example.json.

Copies only the Mongo URI and the model/embedding routes from your local config;
the demo never inherits channels, integrations, QQ routes or real databases.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(template: dict, local: dict) -> dict:
    value = json.loads(json.dumps(template))
    value.pop('_comment', None)
    value['mongo_uri'] = local['mongo_uri']
    for lane in ('character', 'executor', 'embedding'):
        value[lane] = local[lane]
    for key in ('channels', 'integration', 'context_links', 'canonical_persons'):
        value.pop(key, None)
    # Paths become absolute under this checkout (the Host and the worker run from different directories).
    value.pop('workdir', None)
    value['dsh_home'] = (ROOT / value['dsh_home']).resolve().as_posix()
    value['chat']['workspace'] = (ROOT / value['chat']['workspace']).resolve().as_posix()
    for roots in (value.get('persona_sources') or {}).values():
        for root in roots.values():
            root['path'] = (ROOT / root['path']).resolve().as_posix()
    for runtime in (value.get('persona_runtime') or {}).values():
        if runtime.get('export_dir'):
            runtime['export_dir'] = (ROOT / runtime['export_dir']).resolve().as_posix()
    if not value['database'].startswith('asuna_v2_demo_') or value['allowed_databases'] != [value['database']]:
        raise ValueError('DEMO_DATABASE_REQUIRED')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', type=Path, default=ROOT / 'config/local.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'config/demo.local.json')
    args = parser.parse_args()
    template = json.loads((ROOT / 'config/demo.example.json').read_text(encoding='utf-8'))
    value = build(template, json.loads(args.local.read_text(encoding='utf-8')))
    Path(value['chat']['workspace']).mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'written': str(args.out), 'database': value['database'], 'persona': value['chat']['persona']}))


if __name__ == '__main__':
    main()
