"""ADR-117 L2b's identity check: what her turn shows is the same with the old code and the new. It exists only for this
landing and is deleted with tools/adr117_l2b_backfill.py after the install.

Usage: python tools/adr117_l2b_identity.py [--old REV] [--break ledgers|tasks|scene_name|handback|no_backfill] [--keep]

Three runs on the in-memory adapter, each a process of its own, one synthetic world and four turns on one clock:
  A  the old code (REV, default claude/adr117-l2) builds the world through its own writes and runs the turns;
  B  A's store as it stood before its turns, under the new code, after tools/adr117_l2b_backfill.py;
  C  the new code builds the same world from scratch through its own writes and runs the turns.
The turns: a home turn with ledgers; a home turn with tasks (long reports among them); a group turn that shows other
groups by name; a home turn showing the notes she sent; and the value each finished task's hand-back gives her. For
each turn, the context dict, the system prompt and the manifest's documents must be equal, A to B and A to C. A checks
that each turn shows what it is there for, so the comparison compares something; `--break` makes one new reader wrong
on purpose (or B skip the backfill), and the comparison must then fail.
Exit code 0 when every turn is equal (with --break: when the break was caught), 1 otherwise.
"""
import argparse
import io
import json
import os
import pickle
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DATABASE = 'asuna_v2_test_l2b_identity'
PERSONA = 'P1'
HOME, HOME_PERSON = 'local-dm', 'local-user'
BASE = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)         # the world is written from here, a millisecond a reading
TURN_AT = [datetime(2026, 11, 4, 9 + n, 0, tzinfo=timezone.utc) for n in range(4)]
GROUP_NAMES = {'g1': ['Gone'], 'g2': ['Gtwo old', 'Gtwo']}      # g2 was renamed: its newest named line's name holds


# ── one run (a process of its own, on one tree's code) ──────────────────────────────────────────────────────────────

class Clock:
    at, n = BASE, 0

    @classmethod
    def tick(cls):
        cls.n += 1
        return cls.at + timedelta(milliseconds=cls.n)

    @classmethod
    def set(cls, moment):
        cls.at, cls.n = moment, 0


class Ticking(datetime):
    """The core's clock reads this: every reading a millisecond on from the moment set."""
    @classmethod
    def now(cls, tz=None):
        value = Clock.tick()
        return value if tz else value.replace(tzinfo=None)


def still():
    """The in-memory server's clock (a written `Now`): the core clock's last reading, without moving it."""
    return Clock.at + timedelta(milliseconds=Clock.n)


def open_store(root, data, image=None):
    """The fixture world's settings (tests/conftest.py's turn settings) and a store on the in-memory adapter (holding
    a saved store's records, when `image` is given)."""
    sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
    os.environ['ASUNA_UNIT_RUN'] = '1'
    os.environ['ASUNA_DATA_ROOT'] = str(data)
    import asuna
    assert Path(asuna.__file__).resolve().is_relative_to(root / 'src'), 'not this tree\'s code: %s' % asuna.__file__
    from asuna import clock
    from asuna.store import memory as memory_adapter
    clock.datetime = Ticking
    from asuna import channel_kinds, capabilities
    from asuna import config as _config
    from asuna.config import DATA
    from asuna.state import Store
    from fixture_grant import fixture_grant
    channel_kinds.load([{'python': root / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
    config = _config.load(root / 'config' / 'local.example.json', dsh_home=DATA / 'asuna-dsh')
    config.update(mongo_uri='mongodb://unit-run.invalid:27017/', character_id='demo', database_adapter='memory',
                  database=DATABASE, allowed_databases=[], seed=7)
    for lane, modalities in (('character', ['text']), ('executor', ['text', 'image'])):
        config[lane] = {'model': 'fixture-' + lane, 'provider': 'fixture', 'max_tokens': 4096, 'context_window': 65536,
                        'input_modalities': modalities, 'token_counter': 'native-host'}
    config['_host_sandbox'] = {'available': True, 'reason': None}
    fixture_grant(config, DATABASE)
    capabilities.forget()
    if image:
        memory_adapter._DATABASES[DATABASE] = pickle.loads(Path(image).read_bytes())
    store = Store(config, DATABASE)
    store.checked.adapter.clock = still
    return store


def ingest(store, scene_id, person_id, event_id, text, group_name=None):
    from asuna.ingress import persist_input
    event = {'event_id': event_id, 'scene_id': scene_id, 'person_id': person_id, 'text': text}
    if group_name is not None:
        event['raw'] = {'group_name': group_name}
    return persist_input(store, event)[0]


def write_doc(store, slug, kind, heading, body, n):
    from asuna import memory_tiers
    from asuna.documents import DocumentStore
    docs = DocumentStore(store, PERSONA)
    before = docs.read(slug)
    intent = {'op': 'append_section', 'heading': heading, 'reason': 'world', 'visibility': 'owner_private',
              'kind': kind}
    docs.apply(slug, intent, body, base_revision_id=before[0], author='character', mutation_id='world:%s:%d' % (slug, n))
    if memory_tiers.ENABLED:
        memory_tiers.Tiers(store, PERSONA).written(slug, intent, before[1], docs.read(slug)[1])


def report(sections, each):
    return '\n'.join('## 第%d部分\n' % (n + 1) + ('第%d部分的内容，一行一行写下去。\n' % (n + 1)) * each
                     for n in range(sections))


def build(store):
    """The world, through each code's own writes: documents, named group lines, tasks finished four ways, notes."""
    from asuna import notes, tasks as task_module
    from asuna.lanes import FakeLane, LaneResult
    from asuna.records import artifacts as artifact_records
    from asuna.records import scenes as scene_records
    from asuna.records import tasks as task_records
    from asuna.records import people as people_records
    store.seed(root_of(store) / 'tests' / 'fixtures' / 'world.json')
    # Her home (chat.prepare_local_scene, without its package seeds: the fixture world's persona is P1).
    people_records.save_identity(store, {'_id': HOME_PERSON, 'person_id': HOME_PERSON, 'platform': 'local',
                                         'account_id': HOME_PERSON, 'display_name': 'owner'}, stream='local-setup')
    scene_records.save(store, {'_id': HOME, 'scene_id': HOME, 'kind': 'dm', 'members': [HOME_PERSON],
                               'scope_key': 'scene:' + HOME, 'policy_epoch': 1, 'sequence': 0}, stream='local-setup')
    # Documents: two ledgers, a working document, her own running record, the work log.
    write_doc(store, 'ledger-money', 'ledger', '借出', '借给 A 一本书，说好月底还。', 1)
    write_doc(store, 'ledger-money', None, '还回', 'A 还了书。', 2)
    write_doc(store, 'ledger-plans', 'ledger', '计划', '周末去看展。', 1)
    write_doc(store, 'reading', 'working', '读书', '读到第三章。', 1)
    write_doc(store, 'garden', 'journal', '浇水', '今天浇了水。', 1)
    write_doc(store, 'work_log', None, '修好了', '修好了一个小问题。', 1)
    # Group lines that carry the group's name; g2 renamed after its first line.
    for scene_id, names in GROUP_NAMES.items():
        person = scene_records.get(store, scene_id)['members'][0]
        for n, name in enumerate(names):
            ingress_line = ingest(store, scene_id, person, 'evt-%s-%d' % (scene_id, n), '大家好', group_name=name)
            assert ingress_line
        ingest(store, scene_id, person, 'evt-%s-plain' % scene_id, '没有群名的一行')
    # Tasks at home: a long report with many tool records, a middling one, a short one with many records, one a
    # restart cut, one orphaned, one still queued.
    asked = ingest(store, HOME, HOME_PERSON, 'evt-ask', '帮我查几件事')
    service = task_module.TaskService(store)

    def task(task_id, state='READY', **extra):
        scene = scene_records.get(store, HOME)
        task_records.save(store, {'_id': task_id, 'request_key': task_id, 'state': state, 'scene_id': HOME,
                                  'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                                  'requester_id': HOME_PERSON, 'episode_id': asked['episode_id'],
                                  'raw_input_refs': [asked['_id']], 'intent_revision': 1, 'fencing_token': 0,
                                  'goal': '查 ' + task_id, 'title': task_id, 'tool_steps': 0,
                                  'created_at': store_now(), **extra}, stream=task_id)
        return task_records.get(store, task_id)

    def records(task_id, count, size):
        for n in range(count):
            artifact_records.save(store, {'_id': '%s-call-%d' % (task_id, n), 'scope_key': 'scene:' + HOME,
                                          'task_id': task_id, 'intent_revision': 1, 'tool': 'write_file',
                                          'args': {'n': n}, 'input_hash': 'h%d' % n, 'state': 'DONE',
                                          'result': {'wrote': 'x' * size, 'n': n}}, stream=task_id)

    class Broker:
        def bind(self, session, task, workspace):
            pass

    for task_id, text, count in (('t-long', report(6, 60), 25), ('t-middling', report(2, 75), 12),
                                 ('t-short', report(1, 10), 30)):
        task(task_id)
        running = service.claim(task_id)
        records(task_id, count, 700)
        lane = FakeLane(store, [LaneResult(content=text)])
        task_module.Executor(service, lane, Broker())._run_claimed(running, str(store.config['chat']['workspace']),
                                                                  lambda: None)
        assert task_records.get(store, task_id)['state'] == 'RETURNED', task_id
    task('t-restart')
    service.claim('t-restart')
    records('t-restart', 3, 50)
    service.interrupted_by_restart('t-restart')
    task('t-orphan')
    orphan = service.claim('t-orphan')
    service.close_orphan(orphan)
    task('t-queued')
    # Notes: home to g1, g1 to g2, g2 to g1.
    for n, (source, target, trust, kind) in enumerate(((HOME, 'g1', notes.TRUSTED, 'group'),
                                                       ('g1', 'g2', notes.UNTRUSTED, 'group'),
                                                       ('g2', 'g1', notes.UNTRUSTED, 'group'))):
        notes.record(store, {'_id': 'note-%d' % n, 'persona': PERSONA, 'from_scene': source,
                             'from_class': 'owner_private' if source == HOME else 'public', 'from_episode': 'ep-n%d' % n,
                             'to_scene': target, 'kind': kind, 'place': 'group', 'text': '便条 %d 的话' % n,
                             'trust': trust, 'mode': notes.WAKE, 'hop': 1, 'reply_to': None, 'tables_version': 1,
                             'created_at': store_now(), 'seen_in': []})


def root_of(store):
    import asuna
    return Path(asuna.__file__).resolve().parents[2]


def store_now():
    from asuna.state import now
    return now()


TURNS = (('home_ledgers', HOME, HOME_PERSON, '今天记了什么账'),
         ('home_tasks', HOME, HOME_PERSON, '那几件事查得怎样'),
         ('group_titles', 'g1', 'A', '有人在吗'),
         ('home_notes_sent', HOME, HOME_PERSON, '便条送到了吗'))


def turns(store):
    from asuna.context import ContextBuilder
    out = {}
    for (name, scene_id, person, text), moment in zip(TURNS, TURN_AT):
        Clock.set(moment)
        ingest(store, scene_id, person, 'evt-turn-' + name, text, group_name='Gone' if scene_id == 'g1' else None)
        event = {'event_id': 'evt-turn-' + name, 'scene_id': scene_id, 'person_id': person, 'text': text}
        system, context, manifest = ContextBuilder(store, retrieval=None).prepare(event, PERSONA)
        out[name] = json.loads(json.dumps({'system': system, 'context': context, 'documents': manifest['documents']},
                                          ensure_ascii=False, sort_keys=True, default=str))
    # What each finished task's hand-back gives her (TaskService.feedback's value, at home): its stored result read.
    from asuna.records import tasks as task_records
    from asuna.tasks import bounded_result, observations_of, records_pages
    out['handback_values'] = json.loads(json.dumps({
        task_id: bounded_result(row.get('result'), records_pages(observations_of(store, row)))
        for task_id in ('t-long', 't-middling', 't-short', 't-restart', 't-orphan')
        for row in [task_records.get(store, task_id)]}, ensure_ascii=False, sort_keys=True, default=str))
    return out


def shows_what_it_is_for(out):
    """Each turn carries what it is in the comparison for (checked on A): else the comparison compared nothing."""
    ledgers = out['home_ledgers']['context'].get('ledgers_from_program') or []
    tasks = out['home_tasks']['context'].get('task_state_from_program') or []
    group = json.dumps(out['group_titles']['context'], ensure_ascii=False)
    sent = (out['home_notes_sent']['context'].get('notes_sent_from_program') or {}).get('items') or []
    return {'ledgers shown': sorted(item['doc'] for item in ledgers) == ['ledger-money', 'ledger-plans'],
            'ledger revisions in the manifest': {'ledger-money', 'ledger-plans'} <= set(out['home_ledgers']['documents']),
            'long reports said': sorted(t['_id'] for t in tasks if '报告' in (t.get('report') or '')) ==
                                 ['t-long', 't-middling'],
            'every task listed': len(tasks) == 6,
            'a renamed group by its newest name': '群聊「Gtwo」' in group and 'Gtwo old' not in group,
            'notes sent named': [item['to'] for item in sent] == ['群聊「Gone」'],
            'a long hand-back paged': (out['handback_values']['t-long'] or {}).get('report_pages', 0) > 1}


BREAKS = ('ledgers', 'tasks', 'scene_name', 'handback', 'no_backfill')


def breaks(name):
    """One new reader made wrong on purpose (`no_backfill`: B runs without the backfill)."""
    if name == 'ledgers':
        from asuna.documents import DocumentStore
        DocumentStore.of_kind = lambda self, kind: []
    elif name == 'tasks':
        from asuna.records import tasks as task_records
        real = task_records.recent_with_inputs
        task_records.recent_with_inputs = lambda *args: [{**row, '_report_pages': 0} for row in real(*args)]
    elif name == 'scene_name':
        from asuna.people import People
        real = People.scene_title
        People.scene_title = lambda self, scene: real(self, {**scene, 'name': None} if scene else scene)
    elif name == 'handback':
        from asuna import tasks
        real = tasks.bounded_result
        tasks.bounded_result = lambda result, records=(): {**real(result, records), **{
            key: result[key] for key in ('chars', 'pages') if key in result}} if isinstance(result, dict) else result
    elif name not in (None, 'no_backfill'):
        raise SystemExit('no such break: %s; the breaks are %s' % (name, ', '.join(BREAKS)))


def drive(args):
    root, out = Path(args.root).resolve(), Path(args.out)
    store = open_store(root, Path(args.data), args.image)
    from asuna.store import memory as memory_adapter
    breaks(args.broken)
    store.ensure()
    if not args.image:
        build(store)
    if args.save_image:
        Path(args.save_image).write_bytes(pickle.dumps(memory_adapter._DATABASES[DATABASE]))
    if args.backfill:
        sys.path.insert(0, str(root / 'tools'))
        import adr117_l2b_backfill
        filled = adr117_l2b_backfill.run(store)
        (out.parent / (out.stem + '-backfill.json')).write_text(json.dumps(filled), encoding='utf-8')
    out.write_text(json.dumps(turns(store), ensure_ascii=False, sort_keys=True), encoding='utf-8')


# ── the comparison ──────────────────────────────────────────────────────────────────────────────────────────────────

def first_difference(a, b, path=''):
    if type(a) is not type(b):
        return path or '/', 'a %s against a %s' % (type(a).__name__, type(b).__name__)
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return '%s/%s' % (path, key), 'only in ' + ('the first' if key in a else 'the second')
            found = first_difference(a[key], b[key], '%s/%s' % (path, key))
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return path, '%d items against %d' % (len(a), len(b))
        for n, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, '%s[%d]' % (path, n))
            if found:
                return found
        return None
    return None if a == b else (path, '%r against %r' % (str(a)[:120], str(b)[:120]))


def old_tree(rev, into):
    archive = subprocess.run(['git', 'archive', '--format=tar', rev], cwd=HERE, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(into, filter='data')
    return into


def compare(args):
    sys.stdout.reconfigure(encoding='utf-8')
    work = Path(tempfile.mkdtemp(prefix='adr117-l2b-identity-'))
    try:
        old = old_tree(args.old, work / 'old')
        data, image = work / 'data', work / 'A.image'

        def run(root, name, *extra):
            command = [sys.executable, str(Path(__file__).resolve()), 'drive', '--root', str(root), '--data', str(data),
                       '--out', str(work / (name + '.json')), *extra]
            done = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
            if done.returncode:
                raise SystemExit('run %s failed (exit %d):\n%s' % (name, done.returncode, done.stderr[-3000:]))
            return json.loads((work / (name + '.json')).read_text(encoding='utf-8'))

        if args.broken and args.broken not in BREAKS:
            raise SystemExit('no such break: %s; the breaks are %s' % (args.broken, ', '.join(BREAKS)))
        broken = ('--break', args.broken) if args.broken and args.broken != 'no_backfill' else ()
        backfill = () if args.broken == 'no_backfill' else ('--backfill',)
        a = run(old, 'A', '--save-image', str(image))
        b = run(HERE, 'B', '--image', str(image), *backfill, *broken)
        c = run(HERE, 'C', *broken)
        filled = work / 'B-backfill.json'
        verdict = {'old': args.old, 'break': args.broken, 'A shows': shows_what_it_is_for(a),
                   'backfill in B': json.loads(filled.read_text(encoding='utf-8')) if filled.exists() else None,
                   'compared': {name: {'context keys': len(turn['context']), 'system chars': len(turn['system']),
                                       'documents': len(turn['documents']),
                                       'bytes': len(json.dumps(turn, ensure_ascii=False))}
                                for name, turn in a.items() if name != 'handback_values'},
                   'hand-back values': {name: len(json.dumps(value, ensure_ascii=False))
                                        for name, value in a['handback_values'].items()},
                   'A=B': {name: first_difference(a[name], b[name]) for name in a},
                   'A=C': {name: first_difference(a[name], c[name]) for name in a}}
        print(json.dumps(verdict, ensure_ascii=False, indent=1))
        meaningful = all(verdict['A shows'].values())
        equal = all(found is None for side in ('A=B', 'A=C') for found in verdict[side].values())
        if not meaningful:
            print('NO VERDICT: a turn does not show what it is in the comparison for')
            return 1
        if args.broken:
            caught = not equal
            print('BREAK %s: %s' % (args.broken, 'caught' if caught else 'NOT caught'))
            return 0 if caught else 1
        print('IDENTICAL' if equal else 'DIFFERENT')
        return 0 if equal else 1
    finally:
        if args.keep:
            print('kept: %s' % work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command')
    check = sub.add_parser('compare')
    for each in (parser, check):
        each.add_argument('--old', default='claude/adr117-l2', help='the old code (a git revision)')
        each.add_argument('--break', dest='broken', default=None, help='one of: ' + ', '.join(BREAKS))
        each.add_argument('--keep', action='store_true', help='keep the work folder')
    one = sub.add_parser('drive')
    one.add_argument('--root', required=True)
    one.add_argument('--data', required=True)
    one.add_argument('--out', required=True)
    one.add_argument('--image')
    one.add_argument('--save-image')
    one.add_argument('--backfill', action='store_true')
    one.add_argument('--break', dest='broken', default=None)
    args = parser.parse_args()
    if args.command == 'drive':
        drive(args)
        return 0
    return compare(args)


if __name__ == '__main__':
    sys.exit(main())
