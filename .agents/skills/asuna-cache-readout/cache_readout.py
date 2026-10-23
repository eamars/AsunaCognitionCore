"""Numbers-only readout of the model traffic in a profile's DSH sessions: input (and the part read from cache) and
output tokens, by brain and by place, and one row per compaction. It parses each event in memory and prints only
counts: event types, usage fields, compaction fields and each session's header (preset, working folder, creation
time). It never prints a message, a summary, a tool call, a path or an id.

    python -I cache_readout.py hits [--by brain|place] [--since T | --hours N]
    python -I cache_readout.py compactions [--brain B] [--last N] [--since T | --hours N]
    python -I cache_readout.py --selftest

T is a local time, 2026-01-02T03:04; without a window it reads from the last restart (`<data>/restart/last.json`).
--data names the data folder (default ASUNA_DATA_ROOT or the checkout's .runtime), --profile the native DSH profile
(default asuna-native), --sessions a session folder to read instead (repeatable). See SKILL.md for the definitions."""
import argparse, collections, datetime, io, json, os, re, statistics, sys, tempfile
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[3]
SESSION_FILE = 'session.v4.jsonl.zstd'
WAITED_SECONDS = 5                      # a turn that begins this soon after a compaction ends was waiting for it
BRAIN_WORDS = {'character': 'Character', 'action': 'Action', 'attend': 'Gate', 'summary': 'Background summaries',
               'scheduler': 'Scheduler', 'appraiser': 'Appraiser', 'recovery': 'Recovery'}
REQUEST_WORDS = {'step': 'turn steps', 'summary': 'compaction summary'}
# The rows always printed, in this order (0 when the window has none, so a row never silently disappears); any other
# brain and request seen is added after them.
FIXED_ROWS = [('character', 'step'), ('character', 'summary'), ('action', 'step'), ('action', 'summary'),
              ('attend', 'step'), ('summary', 'step'), ('scheduler', 'step')]
UNITS = {'M': 1_000_000, 'k': 1_000, 'tokens': 1}
WORD = re.compile(r'[a-z]{1,16}')       # a folder-name segment printed as it is; any other segment prints as #


class NoSessions(Exception):
    pass


def core_presets(root=ROOT):
    """The presets the core plugin defines; every other preset is the persona's character brain."""
    text = (root / 'packages' / 'cognition-core' / 'cordis.patch.yml').read_text(encoding='utf-8')
    return {m.group(1): m.group(1)[len('asuna-'):] for m in re.finditer(r'-\s+id:\s+(asuna-[\w-]+?)-preset\b', text)}


def masked(segment):
    """A folder name with every part that is not a short lowercase word printed as #."""
    return '-'.join(part if WORD.fullmatch(part) else '#' for part in segment.split('-'))


def place_of(cwd, data):
    """Where a session works, from its working folder: work/<name>, channels/<route> (+ /sender), or other."""
    try:
        rel = Path(cwd).resolve().relative_to(data).parts
    except (ValueError, OSError, TypeError):
        return 'other'
    if len(rel) >= 2 and rel[0] in ('work', 'channels'):
        return '/'.join([rel[0], masked(rel[1])] + (['sender'] if len(rel) > 2 else []))
    return 'other'


def session_roots(data, profile):
    """The native profile's live and archived session folders (tools/setup_native_profile.py: profile_base)."""
    base = data / 'adr008' if profile == 'asuna-native' else data / 'adr008' / 'profiles' / profile
    return [base / 'home' / 'sessions', base / 'archive' / 'sessions']


def events(path):
    """The events of one session file and whether it was read to its end (a damaged or truncated tail stops it)."""
    out, whole = [], True
    try:
        with open(path, 'rb') as handle:
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(handle, read_across_frames=True),
                                         encoding='utf-8', errors='replace'):
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        whole = False
    except Exception:                   # noqa: BLE001 a file that cannot be read is counted, never printed
        whole = False
    return out, whole


def usage(event):
    u = (event.get('data') or {}).get('usage')
    if not isinstance(u, dict):
        return None
    fresh, read, written = (int(u.get(k) or 0) for k in ('inputTokens', 'cacheReadTokens', 'cacheWriteTokens'))
    return {'input': fresh + read + written, 'cached': read, 'written': written, 'fresh': fresh,
            'output': int(u.get('outputTokens') or 0)}


class Session:
    def __init__(self, path, data, presets, rank=0):
        self.events, self.whole = events(path)
        head = self.events[0] if self.events and self.events[0].get('type') == 'session' else {}
        preset = head.get('agentPreset') or ''
        self.brain = presets.get(preset, 'character' if preset else 'unknown')
        self.place = place_of(head.get('cwd'), data)
        self.created, self.id = head.get('createdAt'), head.get('id')
        # A session without a header sorts last; one session in two folders counts where the earlier folder has it.
        self.order = (self.created is None, str(self.created), rank, str(path))


def sessions(roots, data, since_ms, presets, every_root=False):
    """The sessions written in the window, oldest first, and how many files could not be read to their end. Raises
    NoSessions when the folders hold no session file at all (with `every_root`, when any one of them holds none)."""
    found, total, unreadable = [], 0, 0
    for rank, root in enumerate(roots):
        here = 0
        for path in Path(root).rglob(SESSION_FILE) if Path(root).is_dir() else ():
            here += 1
            try:
                if path.stat().st_mtime * 1000 < since_ms:
                    continue
            except OSError:
                unreadable += 1
                continue
            found.append(Session(path, data, presets, rank))
            unreadable += not found[-1].whole
        total += here
        if every_root and not here:
            raise NoSessions('no session files in one of the --sessions folders (number %d)' % (rank + 1))
    if not total:
        raise NoSessions('no session files under the session folders; check --data, --profile or --sessions')
    return sorted(found, key=lambda s: s.order), unreadable


def requests(found, since_ms, until_ms):
    """Each model request once: an assistant message by its message id, a summary by its compaction id (forked and
    seeded sessions copy earlier events, which count where they first appeared)."""
    seen, out = set(), []
    for number, s in enumerate(found):
        for e in s.events:
            kind = {'assistant/message': 'step', 'compaction/summary': 'summary'}.get(e.get('type'))
            u = kind and usage(e)
            if not u:
                continue
            d = e.get('data') or {}
            key = ('m', (d.get('message') or {}).get('id')) if kind == 'step' else ('c', d.get('compactionId'))
            if key[1] is None:
                key = ('e', s.id or number, e.get('seq'))
            if key in seen:
                continue
            seen.add(key)
            if since_ms <= (e.get('time') or 0) < until_ms:
                out.append({'brain': s.brain, 'place': s.place, 'kind': kind, **u})
    return out


def trigger_of(start):
    """DSH's own record on compaction/start: a command's id, an open turn's number (automatic), or neither (the
    plugin's compactNow when a turn has ended)."""
    d = start.get('data') or {}
    if d.get('sourceCommandId') is not None:
        return 'commanded'
    return 'in turn' if d.get('turn') is not None else 'turn end'


def compactions(found, since_ms, until_ms):
    """One row per compaction, where it first appeared (a copied session repeats its compactions with their ids)."""
    rows, seen = [], set()
    for s in found:
        ev, starts = s.events, {}
        for i, e in enumerate(ev):
            t, cid = e.get('type'), (e.get('data') or {}).get('compactionId')
            if t == 'compaction/start' and cid not in seen:
                starts[cid] = i
            elif t == 'compaction/end' and cid in starts:
                seen.add(cid)
                first = starts.pop(cid)
                if since_ms <= (e.get('time') or 0) < until_ms:
                    rows.append(_row(s, ev, first, i))
        for cid, first in starts.items() if s.whole else ():   # never ended: running, or a close that failed (a file
            seen.add(cid)                                        # read only in part may just have lost its end)
            if since_ms <= (ev[first].get('time') or 0) < until_ms:
                rows.append(_row(s, ev, first, None))
    return sorted(rows, key=lambda r: r['time'])


def _row(s, ev, first, last):
    start, end = ev[first], ev[last] if last is not None else None
    cid, trigger = (start.get('data') or {}).get('compactionId'), trigger_of(start)
    span = ev[first:last] if last is not None else ev[first:]
    summary = next((x for x in span if x.get('type') == 'compaction/summary'
                    and (x.get('data') or {}).get('compactionId') == cid), None)
    later = ev[last + 1:] if last is not None else []
    after = next((x for x in later if x.get('type') == 'assistant/message' and usage(x)), None)
    turn = next((x for x in later if x.get('type') == 'turn/start'), None)
    t = (end or start).get('time') or 0
    return {'brain': s.brain, 'place': s.place, 'time': t, 'trigger': trigger,
            'end': 'not ended' if end is None else 'failed' if (end.get('data') or {}).get('error') else 'ok',
            'seconds': (t - (start.get('time') or 0)) / 1000 if end else None,
            'summary': summary and usage(summary),
            'folded': summary and (summary.get('data') or {}).get('shadowedTokenCount'),
            'after': after and usage(after),
            # an in-turn compaction holds its own turn; "waited" is about a turn queued behind one between turns
            'waited': None if trigger == 'in turn' or end is None else
            bool(turn and (turn.get('time') or 0) - t < WAITED_SECONDS * 1000)}


def share(part, whole):
    return '%.1f%%' % (100 * part / whole) if whole else '-'


def n(value, unit='tokens'):
    """Tokens in the unit: M and k with three decimals, plain tokens with thousands separators."""
    if value is None:
        return '-'
    return '{:,}'.format(value) if unit == 'tokens' else '%.3f' % (value / UNITS[unit])


def unit_line(unit):
    return 'Unit: ' + ('tokens' if unit == 'tokens' else unit + ' tokens')


def local(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().strftime('%m-%d %H:%M')


def label(brain, kind):
    return '%s, %s' % (BRAIN_WORDS.get(brain, brain), REQUEST_WORDS[kind])


def hits_table(reqs, by, unit='M'):
    """Requests, input (with the part read from cache) and output by brain and request; by place, one row each."""
    groups = collections.defaultdict(collections.Counter)
    for r in reqs:
        g = groups[(r['brain'], r['kind']) if by == 'brain' else (r['brain'], r['kind'], r['place'])]
        g['requests'] += 1
        for k in ('input', 'cached', 'fresh', 'written', 'output'):
            g[k] += r[k]
    if by == 'brain':
        keys = FIXED_ROWS + sorted(k for k in groups if k not in FIXED_ROWS)
    else:
        keys = sorted(groups, key=lambda k: -groups[k]['input'])
    head = ['Brain, request'] + (['place'] if by == 'place' else []) + ['Requests', 'Input', 'of which cached', 'Output']
    lines = [unit_line(unit), ' | '.join(head)]
    total = collections.Counter()

    def row(name, g):
        cached = '%s (%s)' % (n(g['cached'], unit), share(g['cached'], g['input'])) if g['input'] else n(0, unit)
        return ' | '.join(name + ['{:,}'.format(g['requests']), n(g['input'], unit), cached, n(g['output'], unit)])

    for key in keys:
        g = groups.get(key, collections.Counter())
        total.update(g)
        lines.append(row([label(*key[:2])] + ([key[2]] if by == 'place' else []), g))
    lines.append(row(['All'] + ([''] if by == 'place' else []), total))
    if total['written']:
        lines.append('Written to cache (counted in input): %s' % n(total['written'], unit))
    return lines


def compaction_table(rows, unit='M', every=None):
    """The rows shown, then the medians and ends of every compaction in the window (`every`, default the rows)."""
    lines = [unit_line(unit),
             'time | brain | place | trigger | end | summary input | summary cached | folded | summary output'
             ' | seconds | next input | next cached | next turn waited']
    for r in rows:
        s, a = r['summary'] or {}, r['after'] or {}
        lines.append(' | '.join([local(r['time']), BRAIN_WORDS.get(r['brain'], r['brain']), r['place'], r['trigger'],
                                 r['end'], n(s.get('input'), unit), share(s.get('cached', 0), s.get('input')),
                                 n(r['folded'], unit), n(s.get('output'), unit),
                                 '-' if r['seconds'] is None else '%.0f' % r['seconds'], n(a.get('input'), unit),
                                 share(a.get('cached', 0), a.get('input')),
                                 '-' if r['waited'] is None else 'yes' if r['waited'] else 'no']))
    every = rows if every is None else every
    by = collections.defaultdict(list)
    for r in every:
        if r['summary'] and r['summary']['input'] and r['end'] == 'ok':
            by[r['trigger']].append(r['summary']['cached'] / r['summary']['input'])
    for trigger, values in sorted(by.items()):
        lines.append('%s: %d compactions, summary cached share median %.1f%%' % (trigger, len(values),
                                                                             100 * statistics.median(values)))
    ends = collections.Counter(r['end'] for r in every)
    lines.append('ended ok %d, failed %d, not ended %d' % (ends['ok'], ends['failed'], ends['not ended']))
    return lines


def window(args, data):
    now = datetime.datetime.now().astimezone()
    if args.since:
        since = datetime.datetime.fromisoformat(args.since)
        since = since if since.tzinfo else since.astimezone()
        said = 'from ' + since.strftime('%Y-%m-%d %H:%M')
    elif args.hours is not None:
        since, said = now - datetime.timedelta(hours=args.hours), 'the last %g hours' % args.hours
    else:
        back = json.loads((data / 'restart' / 'last.json').read_text(encoding='utf-8'))['back_at']
        since = datetime.datetime.fromisoformat(back.replace('Z', '+00:00')).astimezone()
        said = 'from the last restart, back at ' + since.strftime('%Y-%m-%d %H:%M')
    return since.timestamp() * 1000, now.timestamp() * 1000 + 1, said + ' (local time), read at ' + now.strftime('%H:%M')


def run(argv):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('what', choices=['hits', 'compactions'])
    p.add_argument('--by', choices=['brain', 'place'], default='brain')
    p.add_argument('--brain', default='character', help="compactions of this brain ('all' for every brain)")
    p.add_argument('--last', type=int, default=20, help='compaction rows to show, the latest')
    p.add_argument('--unit', choices=list(UNITS), default='M', help='token unit (default M)')
    p.add_argument('--since')
    p.add_argument('--hours', type=float)
    p.add_argument('--data')
    p.add_argument('--profile', default='asuna-native')
    p.add_argument('--sessions', action='append')
    args = p.parse_args(argv)
    data = Path(args.data or os.environ.get('ASUNA_DATA_ROOT') or ROOT / '.runtime').resolve()
    since, until, said = window(args, data)
    try:
        found, unreadable = sessions(args.sessions or session_roots(data, args.profile), data, since, core_presets(),
                                     every_root=bool(args.sessions))
    except NoSessions as exc:
        print(exc, file=sys.stderr)
        return 2
    print(said)
    if args.what == 'hits':
        lines = hits_table(requests(found, since, until), args.by, args.unit)
    else:
        rows = [r for r in compactions(found, since, until) if args.brain in ('all', r['brain'])]
        shown = rows[-args.last:] if args.last > 0 else []
        print('%d compactions in the window, showing the last %d' % (len(rows), len(shown)))
        lines = compaction_table(shown, args.unit, rows)
    print('\n'.join(lines))
    if unreadable:
        print('%d session files could not be read to their end; what was readable is counted' % unreadable)
    return 0


def selftest():
    """Synthetic sessions with DSH's own fields: a copied message and a copied compaction count once, input adds the
    cached and written parts, the three triggers (a /compact that compacted nothing does not mark a later one), failed
    and unended compactions, a turn that waited, the window and the file-age skip, folder ids masked, no ids printed."""
    checks = []

    def check(name, ok, detail=''):
        checks.append(ok)
        print(('ok  ' if ok else 'FAIL') + ' ' + name + ('' if ok else ' ' + str(detail)))

    with tempfile.TemporaryDirectory() as tmp:
        data, root = Path(tmp) / 'data', Path(tmp) / 'sessions'
        group = 'channels/qq-group-123-456'
        for folder in ('work/local-user', group, 'channels/auto-Ab3dEf9h'):
            (data / folder).mkdir(parents=True)
        presets = core_presets()
        try:
            sessions([root], data.resolve(), 0, presets)[0]
            check('an empty session folder is an error, not a table of zeros', False)
        except NoSessions:
            check('an empty session folder is an error, not a table of zeros', True)

        def write(name, head, evs, age_days=0):
            d = root / name / 'asuna-x'
            d.mkdir(parents=True)
            body = '\n'.join(json.dumps(e) for e in [{'type': 'session', **head}] + evs) + '\n'
            (d / SESSION_FILE).write_bytes(zstandard.ZstdCompressor().compress(body.encode('utf-8')))
            if age_days:
                old = (datetime.datetime.now() - datetime.timedelta(days=age_days)).timestamp()
                os.utime(d / SESSION_FILE, (old, old))

        def msg(t, mid, fresh, read, written=0, out=10):
            return {'type': 'assistant/message', 'time': t, 'data': {'message': {'id': mid}, 'usage': {
                'inputTokens': fresh, 'cacheReadTokens': read, 'cacheWriteTokens': written, 'outputTokens': out}}}

        def comp(t, cid, read, fresh, turn=None, command=None, error=None, seconds=60, ends=True):
            start = {'compactionId': cid, 'turn': turn, **({'sourceCommandId': command} if command else {})}
            evs = [{'type': 'compaction/start', 'time': t, 'data': start}]
            if error is None and ends:
                evs.append({'type': 'compaction/summary', 'time': t + seconds * 500, 'data': {
                    'compactionId': cid, 'shadowedTokenCount': 5000,
                    'usage': {'inputTokens': fresh, 'cacheReadTokens': read, 'outputTokens': 900}}})
            if ends:
                evs.append({'type': 'compaction/end', 'time': t + seconds * 1000,
                            'data': {'compactionId': cid, 'turn': turn, **({'error': error} if error else {})}})
            return evs

        t0 = int(datetime.datetime.now().timestamp() * 1000) - 3_600_000
        home = [{'type': 'command/run', 'time': t0 - 10, 'data': {'name': 'compact', 'commandId': 'k0'}},
                {'type': 'command/done', 'time': t0 - 5, 'data': {'commandId': 'k0', 'kind': 'success'}},  # nothing to compact
                {'type': 'turn/start', 'time': t0, 'data': {'turn': 1}}, msg(t0 + 1, 'm1', 100, 900),
                *comp(t0 + 2, 'c-in', 500, 500, turn=1),
                msg(t0 + 70_000, 'm2', 50, 0, written=950),
                {'type': 'turn/end', 'time': t0 + 71_000, 'data': {'turn': 1}},
                *comp(t0 + 72_000, 'c-end', 990, 10),
                {'type': 'turn/start', 'time': t0 + 72_000 + 61_000, 'data': {'turn': 2}},        # one waited on it
                msg(t0 + 140_000, 'm3', 400, 600),
                {'type': 'turn/end', 'time': t0 + 141_000, 'data': {'turn': 2}},
                {'type': 'command/run', 'time': t0 + 200_000, 'data': {'name': 'compact', 'commandId': 'k1'}},
                *comp(t0 + 200_001, 'c-cmd', 0, 1000, command='k1', error='aborted'),
                *comp(t0 + 300_000, 'c-open', 0, 0, turn=3, ends=False)]
        write('home', {'agentPreset': 'asuna-somebody', 'cwd': str(data / 'work/local-user'), 'createdAt': 1}, home)
        write('fork', {'agentPreset': 'asuna-action', 'createdAt': 2, 'cwd': str(data / group / '789')},
              [msg(t0 + 1, 'm1', 100, 900), *comp(t0 + 2, 'c-in', 500, 500, turn=1),       # copies of m1 and c-in
               msg(t0 + 5, 'a1', 10, 90)])
        write('auto', {'agentPreset': 'asuna-attend', 'createdAt': 3, 'cwd': str(data / 'channels/auto-Ab3dEf9h')},
              [msg(t0 - 7_200_000, 'g0', 40, 0), msg(t0 + 9, 'g1', 40, 0)])
        write('old', {'agentPreset': 'asuna-action', 'createdAt': 0, 'cwd': str(data / 'work/local-user')},
              [msg(t0 - 3 * 86_400_000, 'o1', 1, 1)], age_days=3)
        found, unreadable = sessions([root], data.resolve(), t0 - 3_600_000, presets)
        check('a file last written before the window is skipped', len(found) == 3 and unreadable == 0, len(found))
        reqs = requests(found, t0 - 3_600_000, float('inf'))
        check('a copied message and summary count once, where they first appeared; the window holds',
              len(reqs) == 7 and sum(r['brain'] == 'action' for r in reqs) == 1
              and sum(r['brain'] == 'attend' for r in reqs) == 1, [(r['brain'], r['kind']) for r in reqs])
        steps = [r for r in reqs if r['kind'] == 'step' and r['brain'] == 'character']
        check('input = not cached + cached + written', [r['input'] for r in steps] == [1000, 1000, 1000], steps)
        lines = hits_table(reqs, 'brain', 'tokens')
        rows_by = {line.split(' | ')[0]: line.split(' | ')[1:] for line in lines[2:] if ' | ' in line}
        check('the all row adds up', rows_by['All'][:2] == ['7', '5,140'], rows_by.get('All'))
        check('fixed rows print in order, at 0 when empty', rows_by.get('Scheduler, turn steps') == ['0', '0', '0', '0']
              and rows_by.get('Gate, turn steps', [''])[0] == '1' and list(rows_by)[:7] == [label(*k) for k in FIXED_ROWS],
              list(rows_by))
        m = hits_table(reqs, 'brain')
        check('M is the default unit, three decimals', m[0] == 'Unit: M tokens' and
              [x for x in m if x.startswith('All')][0].split(' | ')[2] == '0.005', m)
        rows = compactions(found, t0 - 3_600_000, float('inf'))
        check('a copied compaction is one row', [r['trigger'] for r in rows].count('in turn') == 2 and len(rows) == 4,
              [(r['trigger'], r['end']) for r in rows])
        check('triggers from DSH fields; a /compact that compacted nothing marks nothing',
              [r['trigger'] for r in rows] == ['in turn', 'turn end', 'commanded', 'in turn'],
              [r['trigger'] for r in rows])
        check('ends: ok, ok, failed, not ended', [r['end'] for r in rows] == ['ok', 'ok', 'failed', 'not ended'])
        check('the summary request\'s own cache', [(r['summary'] or {}).get('cached') for r in rows] == [500, 990, None, None])
        check('the next request after the compaction', rows[0]['after']['written'] == 950 and rows[1]['after']['input'] == 1000)
        check('waited: a turn right after a turn-end compaction; not asked of an in-turn one',
              [r['waited'] for r in rows] == [None, True, False, None] and rows[1]['seconds'] == 60)
        places = {s.place for s in found}
        check('places come from the folder, ids masked', places ==
              {'work/local-user', 'channels/qq-group-#-#/sender', 'channels/auto-#'}, places)
        check('a core preset is named, any other is the character', {s.brain for s in found} == {'character', 'action',
                                                                                                'attend'})
        text = '\n'.join(lines + hits_table(reqs, 'place', 'tokens') + compaction_table(rows))
        check('nothing printed carries an id', not re.search(r'\d{3,}-|-\d{3,}|Ab3d|m1|c-end|k1', text), text)
    print('%d/%d' % (sum(checks), len(checks)))
    return all(checks)


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        sys.exit(0 if selftest() else 1)
    sys.exit(run(sys.argv[1:]))
