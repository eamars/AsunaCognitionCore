"""A coding agent's line to her (ADR-033): post a message, poll her answers.

  python tools/agent_line.py send <route> "<text>"      (or - to read the text from stdin)
  python tools/agent_line.py poll <route> [--wait SECONDS] [--json]
  python tools/agent_line.py status <route>

The route's key is read from <data>/private/route-keys/agent-<route>.json (ASUNA_DATA_ROOT, else .runtime), written
by the Host at start. The key opens only this line: posting as this route, and claiming and confirming her words on it.
A poll confirms each answer it prints; an answer nobody polls stays queued, shown in her history as not yet delivered.
A poll also prints, once each, what the owner wrote on this line from the Web, marked as the owner's.
"""
import argparse
import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM_WAIT = 25            # the host holds one outbox request at most this long


def key_file(route, channel='agent'):
    data = Path(os.environ.get('ASUNA_DATA_ROOT') or ROOT / '.runtime')
    return data / 'private' / 'route-keys' / ('%s-%s.json' % (channel, route))


def load_key(route):
    path = key_file(route)
    if not path.is_file():
        sys.exit('No key for line %r at %s: the Host writes it at start when channels.agent has this route.' % (route, path))
    return json.loads(path.read_text(encoding='utf-8'))


def call(line, method, path, body=None, timeout=CLAIM_WAIT + 10):
    request = urllib.request.Request(line['url'] + path, method=method,
                                     data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                                     headers={'Authorization': 'Bearer ' + line['key'],
                                              'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        sys.exit('%s %s -> HTTP %d %s' % (method, path, exc.code, detail))
    except (urllib.error.URLError, socket.timeout, http.client.HTTPException, ConnectionError) as exc:
        sys.exit('The Host does not answer at %s (%s): is it running?' % (line['url'], getattr(exc, 'reason', exc)))


def send(line, text):
    body = {'route_id': line['route_id'], 'account_id': line['account_id'], 'sender_id': line['sender_id'],
            'event_id': 'agent-' + uuid.uuid4().hex, 'text': text,
            'occurred_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}
    return call(line, 'POST', '/events', body)


def poll(line, wait):
    """Claim her words on this line until none is left, waiting up to `wait` seconds for the first. Returns her
    answers, the line's state, and the owner's lines shown on the way."""
    got, owner, deadline = [], [], time.monotonic() + max(0, wait)
    while True:
        left = deadline - time.monotonic()
        try:
            answer = call(line, 'GET', '/outbox?wait_seconds=%d' % (max(0, min(CLAIM_WAIT, int(left))) if not got else 0))
        except SystemExit:
            if got:                        # what is already confirmed is hers to read: never lose it to a later error
                return got, 'open', owner
            raise
        owner += [('#%s ' % item['seq'] if item.get('seq') is not None else '') + (item.get('text') or '')
                  for item in answer.get('owner_lines') or []]
        if answer.get('line') == 'closed':
            return got, 'closed', owner
        items = answer.get('items') or []
        for item in items:
            call(line, 'POST', '/outbox/%s/receipt' % item['publication_id'],
                 {'attempt_id': item['attempt_id'], 'status': 'platform_accepted',
                  'platform_message_id': 'agent-' + uuid.uuid4().hex, 'response': {'by': 'agent_line'}})
            got.append(item.get('text') or '')
        if not items and (got or time.monotonic() >= deadline):
            return got, 'open', owner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('send'); s.add_argument('route'); s.add_argument('text')
    p = sub.add_parser('poll'); p.add_argument('route'); p.add_argument('--wait', type=int, default=0)
    p.add_argument('--json', action='store_true')
    t = sub.add_parser('status'); t.add_argument('route')
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    line = load_key(args.route)
    if args.command == 'send':
        text = sys.stdin.read() if args.text == '-' else args.text
        result = send(line, text.strip())
        print({'line_closed': 'line closed: she is not taking messages on this line now'}.get(
            result.get('status'), result.get('status', 'sent')))
    elif args.command == 'poll':
        got, state, owner = poll(line, args.wait)
        if args.json:
            print(json.dumps({'line': state, 'messages': got, 'owner_lines': owner}, ensure_ascii=False))
        else:
            for text in owner:
                print('[the owner, on this line from the Web] ' + text)
                print('---')
            for text in got:
                print(text)
                print('---')
            if state == 'closed':
                print('(line closed: her words wait until she opens it)')
    else:
        host, port = line['url'].split('//')[1].split('/')[0].split(':')
        try:
            socket.create_connection((host, int(port)), timeout=3).close()
            print('Host answers at %s; key for line %r present.' % (line['url'], line['route_id']))
        except OSError as exc:
            sys.exit('The Host does not answer at %s (%s).' % (line['url'], exc))


if __name__ == '__main__':
    main()
