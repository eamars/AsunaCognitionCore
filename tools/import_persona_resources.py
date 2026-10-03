"""One-time, explicit ADR-008 selection of existing distributable Xiaoman code.

No logs, connection files, service data, media library, or snapshots are copied.
Reruns refuse to overwrite the persona's subsequently edited project files.
"""
import hashlib
import json
from pathlib import Path
from asuna.config import ROOT, load


def main():
    config = load()
    identifiers, secrets = set(), set()
    def collect(value, key=''):
        if isinstance(value, dict):
            for name, item in value.items():
                collect(item, name)
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif isinstance(value, str):
            if value.isdigit() and 6 <= len(value) <= 12:
                identifiers.add(value)
            if any(word in key.lower() for word in ('password', 'secret', 'token', 'api_key', 'mongo_uri')) and len(value) >= 8:
                secrets.add(value)
    collect(config)
    replacements = {value: str(900000000000 + index) for index, value in enumerate(sorted(identifiers))}
    package = ROOT/'packages/xiaoman'
    chosen = []
    skills = ROOT/'.runtime/skills/local-user'
    for name, names in {'qq-napcat-adapter': ('SKILL.md', 'USAGE.md', 'decode_log.py'),
                        'asuna-offline-selfchecks': ('SKILL.md',)}.items():
        chosen += [(skills/name/file, Path('skills')/name/file) for file in names]
    source = ROOT/'.runtime/integration/owner/development'
    integration = Path('integrations/qq-napcat-adapter')
    chosen += [(source/'adapter.py', integration/'adapter.py')]
    chosen += [(file, integration/'qqadapter'/file.name) for file in sorted((source/'qqadapter').glob('*.py'))]
    chosen += [(file, integration/'vendor/websocket'/file.name) for file in sorted((source/'vendor/websocket').glob('*.py'))]
    chosen += [(source/'vendor/websocket_client-1.9.2.dist-info/licenses/LICENSE', integration/'vendor/LICENSE.websocket-client')]
    manifest = []
    for source, relative in chosen:
        raw = source.read_bytes()
        text = raw.decode('utf-8')
        if any(secret in text for secret in secrets):
            raise ValueError('Private credential found in selected resource: ' + str(relative))
        for original, anonymous in replacements.items():
            text = text.replace(original, anonymous)
        destination = package/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('x', encoding='utf-8', newline='') as output:
            output.write(text)
        manifest.append({'path': relative.as_posix(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                         'export_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    (package/'resources-provenance.json').write_text(json.dumps({
        'source': 'Existing Xiaoman skills and enabled QQ adapter implementation; explicit file selection.',
        'privacy': 'Private account/route identifiers in documentation and examples were replaced; no live configuration was copied.',
        'files': manifest}, indent=2), encoding='utf-8')
    print({'selected_files': len(manifest), 'private_identifiers_replaced': len(replacements)})


if __name__ == '__main__':
    main()
