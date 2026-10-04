"""Synthetic persona job (demo): inventory, import and recall check over the stdio protocol.

The manifest and the question bank are the persona's own data; this fixture
receives them as run arguments. Standard library only (runs in the sandbox).
"""
import base64
import hashlib
import json
import os
import re
import sys

_ids = iter(range(1, 1_000_000))  # personal-scan: ok


def call(method, args):
    request_id = next(_ids)
    sys.stdout.write(json.dumps({'id': request_id, 'method': method, 'args': args}, ensure_ascii=False) + '\n')
    sys.stdout.flush()
    reply = json.loads(sys.stdin.readline())
    if 'error' in reply:
        raise RuntimeError(reply['error']['code'])
    return reply['value']


def main():
    start = json.loads(sys.stdin.readline())
    args, root = start['args'], start['sources']['demo-home']
    entries = args.get('manifest')
    if entries is None:
        # The persona's own manifest document, when the run carries none (e.g. from the settings card).
        try:
            doc = call('documents.get', {'slug': 'migration-manifest'})['content']
            entries = json.loads(doc['sections'][0]['body'])
        except Exception:
            entries = []
    manifest = {entry['path']: entry for entry in entries}
    files = sorted(os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/')
                   for d, _, names in os.walk(root) for f in names)
    items, red = [], False
    for path in files:
        if path not in manifest:
            items.append({'path': path, 'status': 'red', 'why': 'not registered in the manifest'})
            red = True
    counts = {'memory': 0, 'documents': 0, 'snapshots': 0}
    for path, entry in manifest.items():
        raw = open(os.path.join(root, path), 'rb').read()
        digest = hashlib.sha256(raw).hexdigest()
        call('artifacts.snapshot', {'origin': 'demo-home', 'path': path, 'sha256': digest,
                                    'content': base64.b64encode(raw).decode()})
        counts['snapshots'] += 1
        text = raw.decode('utf-8')
        if entry['layer'] == 'diary':
            lines = text.splitlines()
            for match in re.finditer(r'(?m)^## (\d{4}-\d{2}-\d{2})\n(.+)$', text):
                line = text[:match.start()].count('\n') + 1
                result = call('memory.upsert', {'origin': 'demo-home', 'units': [{
                    'source_identity': path + '#' + match.group(1), 'entry_type': 'diary', 'body_markdown': match.group(2),
                    'epistemic_type': 'character_interpretation', 'occurred_at': match.group(1) + 'T12:00:00+00:00',
                    'visibility': entry.get('visibility', 'owner_private'),
                    'source_window': {'origin': 'demo-home', 'path': path, 'file_sha256': digest,
                                      'line_from': line, 'line_to': line + 1, 'heading': match.group(1)}}]})
                counts['memory'] += result['created'] + result['updated']
        elif entry['layer'] == 'document':
            sections = [{'heading': h.strip(), 'body': b.strip(), 'visibility': entry.get('visibility', 'owner_private')}
                        for h, b in re.findall(r'(?m)^## (.+)\n((?:(?!^## ).*\n?)*)', text)]
            result = call('documents.upsert', {'origin': 'demo-home', 'source_identity': path, 'slug': entry['slug'],
                                               'kind': 'working', 'title': entry['slug'], 'sections': sections,
                                               'source': {'path': path, 'sha256': digest}})
            counts['documents'] += result['action'] in ('created', 'updated')
    for question in args.get('questions', []):
        if question.get('scope') == 'out':
            items.append({'question': question['id'], 'status': 'NOT_RUN(scope)'})
            continue
        if any(anchor not in manifest for anchor in question['anchors']):
            items.append({'question': question['id'], 'status': 'red', 'why': 'anchor file not registered'})
            red = True
            continue
        found = call('probe.retrieve', {'as': 'owner_private', 'query': question['query'], 'k': 6})
        hit = any((item.get('source_window') or {}).get('path') in question['anchors'] for item in found['items'])
        items.append({'question': question['id'], 'status': 'pass' if hit else 'red'})
        red = red or not hit
    with open(os.path.join(start['out'], 'counts.json'), 'w', encoding='utf-8') as handle:
        json.dump(counts, handle)
    status = 'red' if red else 'ok'
    sys.stdout.write(json.dumps({'kind': 'report', 'status': status, 'summary': json.dumps(counts),
                                 'items': items}, ensure_ascii=False) + '\n')
    sys.stdout.flush()
    return 1 if red else 0


if __name__ == '__main__':
    sys.exit(main())
