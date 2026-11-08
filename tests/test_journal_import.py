"""The running log's one-time move from one document to one row per section (tools/journal_import.py,
DocumentStore._journal_import), run with her Host stopped: every section with its times, its tier rows dated by them,
the head dropped last and its revisions kept; a write during the import keeps the head and a second run brings the rows
to it; a persona job never writes a running record back as a document. On the fixture world (in memory)."""
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from datetime import datetime, timedelta, timezone

from asuna import clock, crossing, documents, host_lease, memory_tiers, visibility
from asuna.config import database_lock
from asuna.documents import DocumentError, DocumentStore
from asuna.persona_data import PersonaDataAPI
from asuna.queue import RuntimeLease
from asuna.records import heads
from asuna.role_tools import RoleTools
from asuna.store.words import Set

PERSONA = 'P1'
@pytest.fixture(autouse=True)
def locks(monkeypatch, tmp_path):
    """The Host's lock files of these tests' databases live in the test's own folder."""
    import asuna.config
    import asuna.queue
    for module in (asuna.config, asuna.queue):
        monkeypatch.setattr(module, 'LOCKS', tmp_path / 'locks')


@pytest.fixture
def home(world):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'person_id': 'A', 'persona': PERSONA}
    pilot = SimpleNamespace(items=[], synced_at=0.0)
    coordinator = SimpleNamespace(store=world, scheduler=None, context=SimpleNamespace(pilot=pilot),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator), serial=[0], pilot=pilot)


def call(home, args):
    """One write_document of hers, in a home turn of its own."""
    home.serial[0] += 1
    ep_id = 'ep-l4-%d' % home.serial[0]
    home.store.put('episodes', {
        '_id': ep_id, 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': 'A', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': visibility.OWNER_PRIVATE},
        'turn_tools': ['think', 'write_document'], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    return home.tools.call(ep_id, ep_id + ':0', 'write_document', args)[0]


def write(home, heading, doc='self', body=None, visibility_='public', **args):
    return call(home, {'doc': doc, 'do': 'append_section', 'heading': heading,
                       'content': body or ('关于 %s 的一段话' % heading), 'why': 'mine', 'visibility': visibility_,
                       **args})


def sections(home, doc='self'):
    return [s['sid'] for s in (DocumentStore(home.store, PERSONA).read(doc)[1] or {}).get('sections') or []]


class Held:
    """The tool's store: the world's, left open when the tool closes it."""

    def __init__(self, world):
        self.world = world

    def __getattr__(self, name):
        return getattr(self.world, name)

    def close(self):
        pass


def _tool(world, monkeypatch, *argv):
    monkeypatch.setattr('sys.argv', ['journal_import.py', *argv])
    spec = importlib.util.spec_from_file_location(
        'journal_import', Path(__file__).resolve().parents[1] / 'tools' / 'journal_import.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'load', lambda path: {**world.config, 'chat': {'persona': PERSONA}})
    monkeypatch.setattr(module, 'Store', lambda config: Held(world))
    return module


def test_the_one_time_import_brings_every_section_with_its_times_and_drops_the_head(world, monkeypatch, capsys):
    docs = DocumentStore(world, PERSONA)
    base = None
    for n, heading in enumerate(('first', 'second', 'third')):
        base = docs.apply('running-log', {'op': 'append_section', 'heading': heading, 'reason': 'r', 'kind': 'working',
                                          'visibility': 'public' if n != 1 else 'owner_private'},
                          '第 %d 段' % n, base_revision_id=base, author='character', mutation_id='m-%d' % n)['_id']
    base = docs.apply('running-log', {'op': 'replace_section', 'sid': 'first', 'reason': 'r'}, '第 0 段，改过',
                      base_revision_id=base, author='character', mutation_id='m-3')['_id']
    # Written 60, 50, 45 days ago, the first rewritten 40 days ago.
    for row, days in zip(heads.history(world, docs.key('running-log')).rows(), (60, 50, 45, 40)):
        world.collection('state_revisions').update({'_id': row['_id']}, Set({
            'created_at': (clock.now() - timedelta(days=days)).isoformat(timespec='microseconds')}))
    created = sorted(row['created_at'] for row in heads.history(world, docs.key('running-log')).rows())
    tool = _tool(world, monkeypatch, 'running-log', '--dry-run')
    tool.main()
    dry = json.loads(capsys.readouterr().out)
    assert dry['before'] == {'head': True, 'kind': 'working', 'sections': 3, 'rows': 0, 'rows_to_make': 3,
                             'by_visibility': {'public': 2, 'owner_private': 1}, 'revisions': 4}
    assert heads.head(world, docs.key('running-log')) and not list(documents.entries(world, PERSONA, 'running-log').rows())

    # Stopped halfway (its rows made, the head still there), it resumes when run again.
    monkeypatch.setattr('sys.argv', ['journal_import.py', 'running-log'])
    with monkeypatch.context() as stop:
        stop.setattr(documents.head_records, 'drop_head', lambda *a, **k: (_ for _ in ()).throw(OSError('stopped')))
        with pytest.raises(OSError):
            tool.main()
    assert heads.head(world, docs.key('running-log')) and len(list(documents.entries(world, PERSONA, 'running-log').rows())) == 3
    # Until its head goes it is still the document, whole, for every reader.
    halfway = DocumentStore(world, PERSONA)
    assert not halfway.is_journal('running-log') and 'running-log' not in documents.slugs(world, PERSONA)
    assert halfway.read('running-log')[1]['kind'] == 'working' and len(halfway.read('running-log')[1]['sections']) == 3
    capsys.readouterr()
    tool.main()
    done = json.loads(capsys.readouterr().out)
    assert done['rows_equal_sections'] and done['revisions_kept'] and not done['after']['head']
    rows = {row['sid']: row for row in documents.entries(world, PERSONA, 'running-log').rows()}
    assert list(rows) == ['first', 'second', 'third'] and [rows[s]['seq'] for s in rows] == [1, 2, 3]
    assert (rows['first']['created_at'], rows['first']['updated_at']) == (created[0], created[3])
    assert (rows['third']['created_at'], rows['third']['updated_at']) == (created[2], created[2])
    assert rows['second']['visibility'] == 'owner_private' and rows['first']['body'] == '第 0 段，改过'
    assert DocumentStore(world, PERSONA).is_journal('running-log')
    tiers = {r['sid']: r for r in memory_tiers.items(world, PERSONA, doc='running-log').each()}
    assert set(tiers) == set(rows)
    # Its tier rows keep each entry's own times: none of these old entries reads as just written or comes up by itself.
    for sid, row in rows.items():
        assert (tiers[sid]['added'], tiers[sid]['memorable_at']) == (row['created_at'], row['updated_at'])
        assert not memory_tiers.within_age(tiers[sid], clock.now())
    # Again: nothing is made twice.
    tool.main()
    again = json.loads(capsys.readouterr().out)
    assert again['before']['rows'] == 3 and 'after' not in again and not again.get('refused')
    assert len(list(documents.entries(world, PERSONA, 'running-log').rows())) == 3


def test_a_write_of_hers_during_the_import_keeps_the_head_and_the_run_again_brings_the_rows_to_it(world, monkeypatch,
                                                                                                    capsys):
    docs = DocumentStore(world, PERSONA)
    base = None
    for n, heading in enumerate(('first', 'second')):
        base = docs.apply('running-log', {'op': 'append_section', 'heading': heading, 'reason': 'r', 'kind': 'working',
                                          'visibility': 'owner_private'},
                          '第 %d 段' % n, base_revision_id=base, author='character', mutation_id='m-%d' % n)['_id']
    tool = _tool(world, monkeypatch, 'running-log')
    real, hers = documents.save_entry, DocumentStore(world, PERSONA)

    def her_write_lands(store, row, **kwargs):
        made = real(store, row, **kwargs)
        if row['sid'] == 'first' and not kwargs.get('expected'):
            # Her turn rewrites the section just imported and adds one, through the document, mid-import.
            head = hers.read('running-log')[0]
            head = hers.apply('running-log', {'op': 'replace_section', 'sid': 'first', 'reason': 'r'}, '第 0 段，她改的',
                              base_revision_id=head, author='character', mutation_id='m-hers')['_id']
            hers.apply('running-log', {'op': 'append_section', 'heading': 'third', 'reason': 'r',
                                       'visibility': 'owner_private'}, '第 2 段', base_revision_id=head,
                       author='character', mutation_id='m-hers-2')
        return made
    with monkeypatch.context() as during:
        during.setattr(documents, 'save_entry', her_write_lands)
        with pytest.raises(SystemExit) as stopped:
            tool.main()
    out = json.loads(capsys.readouterr().out)
    assert stopped.value.code == 1 and out['refused'].startswith('JOURNAL_IMPORT_HEAD_CHANGED') and out['after']['head']
    tool.main()
    done = json.loads(capsys.readouterr().out)
    assert done['before']['sections'] == 3 and done['rows_equal_sections'] and not done['after']['head']
    rows = {row['sid']: row for row in documents.entries(world, PERSONA, 'running-log').rows()}
    assert list(rows) == ['first', 'second', 'third'] and rows['first']['body'] == '第 0 段，她改的'


def lease(world, seconds):
    now = datetime.now(timezone.utc)
    world.collection('host_leases').replace({'_id': 'host', 'instance': 'this-deployment', 'host': 'box', 'pid': 1,
                                             'persona': PERSONA, 'since': now,
                                             'expires_at': now + timedelta(seconds=seconds)}, create=True)


def test_the_import_refuses_while_a_host_for_the_database_runs(world, monkeypatch, capsys):
    docs = DocumentStore(world, PERSONA)
    docs.apply('running-log', {'op': 'append_section', 'heading': 'h', 'reason': 'r', 'kind': 'working',
                               'visibility': 'owner_private'}, '正文', base_revision_id=None, author='character',
               mutation_id='m-h')
    tool = _tool(world, monkeypatch, 'running-log')
    monkeypatch.setattr(tool, 'POLL_SECONDS', 0.1)
    with RuntimeLease(database_lock(world.config), timeout=1):          # her Host on this machine holds it
        with pytest.raises(SystemExit) as stopped:
            tool.main()
    out = json.loads(capsys.readouterr().out)
    assert stopped.value.code == 1 and out['refused'].startswith('JOURNAL_IMPORT_HOST_UP') and 'this machine' in out['refused']
    # A lease that does not expire within the wait, this deployment's own or not (the lock may be another file).
    lease(world, 60)
    monkeypatch.setattr(tool, 'WAIT_SECONDS', 0.3)
    with pytest.raises(SystemExit):
        tool.main()
    assert 'had not expired after' in json.loads(capsys.readouterr().out)['refused']
    # One renewed while it waits is a Host that runs.
    later = iter(range(1, 100))
    real = host_lease.holder
    monkeypatch.setattr(tool.host_lease, 'holder', lambda config: {**real(config), 'expires_at': real(config)['expires_at']
                                                                  + timedelta(seconds=30 * next(later))})
    monkeypatch.setattr(tool, 'WAIT_SECONDS', 5)
    with pytest.raises(SystemExit):
        tool.main()
    assert 'was renewed while this waited' in json.loads(capsys.readouterr().out)['refused']
    monkeypatch.setattr(tool.host_lease, 'holder', real)
    assert heads.head(world, docs.key('running-log')) and not list(documents.entries(world, PERSONA, 'running-log').rows())
    # A Host stopped a moment ago: its lease expires in a second, never renewed; the import waits for it, then runs.
    lease(world, 1)
    started = time.monotonic()
    tool.main()
    captured = capsys.readouterr()
    done = json.loads(captured.out)
    assert done['rows_equal_sections'] and not done['after']['head'] and 'waiting for the database lease' in captured.err
    assert 0.5 < time.monotonic() - started < 4


def test_a_persona_job_never_writes_her_running_record_back_into_a_document(world, monkeypatch, capsys):
    docs = DocumentStore(world, PERSONA)
    docs.apply('running-log', {'op': 'append_section', 'heading': 'h', 'reason': 'r', 'kind': 'working',
                               'visibility': 'owner_private'}, '正文', base_revision_id=None, author='character',
               mutation_id='m-h')
    assert docs._journal_import('running-log')
    api = PersonaDataAPI(world, PERSONA, run_id='run-1', job_id='job-1', grants={'persona_data.write'},
                         sources={'origin-1': 'cohabiting'})
    for method, args in (('documents.append', {'slug': 'running-log', 'origin': 'origin-1', 'source_identity': 'a',
                                               'section': {'heading': 'x', 'body': '外来的', 'visibility': 'public'}}),
                         ('documents.upsert', {'slug': 'running-log', 'kind': 'working', 'origin': 'origin-1',
                                               'source_identity': 'b', 'title': 't',
                                               'sections': [{'heading': 'x', 'body': '外来的', 'visibility': 'public'}]})):
        with pytest.raises(DocumentError) as refused:
            api.dispatch(method, args)
        assert refused.value.code == 'DOC_IS_RUNNING_RECORD', method
    assert not heads.head(world, docs.key('running-log'))
    assert [row['body'] for row in documents.entries(world, PERSONA, 'running-log').rows()] == ['正文']
    assert DocumentStore(world, PERSONA).is_journal('running-log')


def test_the_command_imports_only_a_working_document(world, monkeypatch, capsys):
    docs = DocumentStore(world, PERSONA)
    docs.apply('a-ledger', {'op': 'append_section', 'heading': 'h', 'reason': 'r', 'kind': 'ledger'}, '正文',
               base_revision_id=None, author='character', mutation_id='m-l')
    tool = _tool(world, monkeypatch, 'a-ledger')
    with pytest.raises(SystemExit):
        tool.main()
    assert 'JOURNAL_IMPORT_NOT_WORKING' in capsys.readouterr().out and heads.head(world, docs.key('a-ledger'))


def test_a_record_made_rows_reads_only_the_texts_it_shows_and_a_new_row_does_not_read_the_document_again(world,
                                                                                                      monkeypatch):
    docs = DocumentStore(world, PERSONA)
    base = None
    for n, heading in enumerate(('first', 'second', 'third')):
        base = docs.apply('running-log', {'op': 'append_section', 'heading': heading, 'reason': 'r', 'kind': 'working',
                                          'visibility': 'owner_private'}, '第 %d 段' % n, base_revision_id=base,
                          author='character', mutation_id='p-%d' % n)['_id']
    docs.apply('running-log', {'op': 'replace_section', 'sid': 'first', 'reason': 'fixed'}, '第 0 段，改过',
               base_revision_id=base, author='character', mutation_id='p-3')
    read, real = [], crossing.head_records.revision
    monkeypatch.setattr(crossing.head_records, 'revision', lambda store, rid, fields=None, **kw: read.append(rid) or real(
        store, rid, fields, **kw))
    mark = (world.name, PERSONA, 'running-log')
    past = crossing.versions(world, PERSONA, 'running-log')
    assert {sid: [body for body, *_ in v] for sid, v in past.items()} == {'first': ['第 0 段']}
    assert len(read) == 1, 'the one revision holding a replaced text, not all four'
    document = crossing._pasts[mark][1]
    # As rows, a rewrite of an entry: its old text is the document's last; the document's revisions are not listed again.
    assert DocumentStore(world, PERSONA)._journal_import('running-log')
    rows = DocumentStore(world, PERSONA)
    rows.apply('running-log', {'op': 'replace_section', 'sid': 'second', 'reason': 'later'}, '第 1 段，后来改的',
               base_revision_id=rows.read('running-log')[0], author='character', mutation_id='p-4')
    read.clear()
    past = crossing.versions(world, PERSONA, 'running-log')
    assert {sid: [body for body, *_ in v] for sid, v in past.items()} == {'first': ['第 0 段'], 'second': ['第 1 段']}
    assert crossing._pasts[mark][1] is document and len(read) == 1, 'only the revision holding the text it replaced'


