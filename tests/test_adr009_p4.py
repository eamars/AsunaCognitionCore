"""ADR-009 P4: memory extensions, persona data API, probes, persona jobs, export."""
import json

import shutil
import uuid

import pytest

from asuna.blobs import BlobStore
from asuna.config import ROOT
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, LaneResult
from asuna.persona_data import DataError, PersonaDataAPI, check_export_path, export_documents
from asuna.persona_jobs import DirectLauncher, JobRunner, SandboxLauncher
from asuna.retrieval import Retrieval
from asuna.state import Denied
from conftest import FIXTURES
from test_adr009_p2 import owner, decide
from test_engineering_m1 import event

HOME = FIXTURES / 'personas/demo-home'
JOB = FIXTURES / 'personas/demo/jobs/migrate/main.py'
MANIFEST = [{'path': 'diary/2026-01.md', 'layer': 'diary'}, {'path': 'profile.md', 'layer': 'document', 'slug': 'old-profile'}]
QUESTIONS = [{'id': 'q1', 'query': '热可可', 'anchors': ['diary/2026-01.md']},
             {'id': 'q2', 'query': '书架', 'anchors': ['notes/unregistered.txt']},
             {'id': 'q3', 'query': '外部日记里的事', 'anchors': [], 'scope': 'out'}]


@pytest.fixture
def retrieval(store, tmp_path):
    value = Retrieval(store, Evidence(tmp_path / 'evidence'))
    yield value
    value.close()


def api(store, retrieval=None, state='cohabiting', grants=('persona_data.write', 'probe')):
    owner(store)
    return PersonaDataAPI(store, 'P1', run_id='run-test', job_id='migrate', grants=grants,
                          sources={'demo-home': state}, retrieval=retrieval)


def unit(identity, body, vis='owner_private', **extra):
    return {'source_identity': identity, 'entry_type': 'diary', 'body_markdown': body, 'visibility': vis,
            'source_window': {'origin': 'demo-home', 'path': 'diary/2026-01.md', 'file_sha256': 'f' * 64,
                              'line_from': 1, 'line_to': 2, 'heading': identity}, **extra}


def test_T4_2_owner_private_units_never_reach_public_retrieval(store, retrieval):
    data = api(store, retrieval)
    data.dispatch('memory.upsert', {'origin': 'demo-home', 'units': [unit('secret', 'PRIVATE_TOKEN_CANARY 深夜的心事')]})
    private, _ = retrieval.search('scene:dm-a', 1, 'PRIVATE_TOKEN_CANARY 深夜的心事', private_scope='owner-private:P1')
    public, manifest = retrieval.search('scene:g1', 1, 'PRIVATE_TOKEN_CANARY 深夜的心事')
    assert any(m['source_identity'] == 'secret' for m in private if m.get('source_identity'))
    assert not any(m.get('source_identity') == 'secret' for m in public)
    assert 'imp-' not in json.dumps(manifest.get('lexical_ids'))                 # not even a lexical candidate
    with pytest.raises(ValueError):
        retrieval.search('scene:g1', 1, 'x', linked_scopes=['owner-private:P1'], private_scope='scene:g1')
    if manifest['path'] != 'server_vector_rrf':
        pytest.skip('vector filter not exercised: embedding service unavailable (lexical candidates verified above)')


def test_T4_3_idempotent_writes_and_dry_run_writes_nothing(store):
    data = api(store)
    request = {'origin': 'demo-home', 'units': [unit('e1', '一'), unit('e2', '二')]}
    collections = ('memory_units', 'state_heads', 'state_revisions', 'affect_events', 'artifacts')
    before = {c: store.db[c].count_documents({}) for c in collections}
    plan = data.dispatch('memory.upsert', {**request, 'dry_run': True})
    assert {c: store.db[c].count_documents({}) for c in collections} == before
    real = data.dispatch('memory.upsert', request)
    assert (plan['created'], real['created']) == (2, 2)
    assert data.dispatch('memory.upsert', request) == {'created': 0, 'updated': 0, 'unchanged': 2, 'pending_embedding': 0,
                                                       'visibility_defaulted': []}


def job_config(store, entry=JOB, sources=('demo-home',), timeout=60):
    owner(store)
    store.config['persona_contribution'] = {'jobs': [{'id': 'migrate', 'entry': str(entry), 'runtime': 'python',
                                                      'grants': ['persona_data.write', 'probe'], 'sources': list(sources),
                                                      'timeout_s': timeout}]}
    store.config['persona_sources'] = {'P1': {'demo-home': {'path': str(HOME), 'state': 'cohabiting'}}}
    if not store.db.scenes.find_one({'_id': 'dm-a'}):
        raise AssertionError('fixture scene missing')


def write_job(name, body):
    directory = ROOT / '.runtime/work' / ('adr009-job-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    (directory / name).write_text(body, encoding='utf-8')
    return directory / name


PROTOCOL = '''import json,sys
start=json.loads(sys.stdin.readline())
def call(m,a):
    sys.stdout.write(json.dumps({"id":1,"method":m,"args":a})+"\\n");sys.stdout.flush();return json.loads(sys.stdin.readline())
'''


def test_T4_5_sandbox_isolation_and_protocol(store, retrieval):
    """Protocol parts run everywhere; isolation parts need the real sandbox and skip without it."""
    other = write_job('main.py', PROTOCOL + 'r=call("documents.get",{"slug":"x","persona":"someone-else"})\n'
                      'sys.stdout.write(json.dumps({"kind":"report","status":"red","summary":r["error"]["code"],"items":[]})+"\\n");sys.exit(1)\n')
    try:
        job_config(store, entry=other)
        result = JobRunner(store, 'P1', retrieval=retrieval, launcher=DirectLauncher()).run('migrate', dry_run=True)
        report = json.loads(BlobStore(store).get(result['report_artifact_ids'][0], 'owner-private:P1', operator=True))
        assert result['status'] == 'red' and report['summary'] == 'PERSONA_SCOPE_DENIED'
        slow = write_job('main.py', 'import time\ntime.sleep(30)\n')
        job_config(store, entry=slow, timeout=2)
        timed = JobRunner(store, 'P1', launcher=DirectLauncher()).run('migrate')
        assert timed['status'] == 'error', timed   # killed on timeout
        if not SandboxLauncher.available():
            pytest.skip('WSL + bubblewrap unavailable: isolation (paths, network, /out cap) not verified here')
        probe = write_job('main.py', '''import json,os,socket,sys
start=json.loads(sys.stdin.readline())
seen={"home_visible":os.path.exists("/mnt/c"),"source_listed":sorted(os.listdir(start["sources"]["demo-home"]))}
try:
    socket.create_connection(("192.0.2.1",80),timeout=2);seen["network"]=True
except OSError:
    seen["network"]=False
open(os.path.join(start["out"],"seen.json"),"w").write(json.dumps(seen))
sys.stdout.write(json.dumps({"kind":"report","status":"ok","summary":json.dumps(seen),"items":[]})+"\\n")
''')
        job_config(store, entry=probe)
        result = JobRunner(store, 'P1', launcher=SandboxLauncher()).run('migrate')
        seen = json.loads(json.loads(BlobStore(store).get(result['report_artifact_ids'][0], 'owner-private:P1', operator=True))['summary'])
        assert seen == {'home_visible': False, 'source_listed': ['diary', 'notes', 'profile.md'], 'network': False}, seen
        flood = write_job('main.py', 'import json,os,sys\nstart=json.loads(sys.stdin.readline())\n'
                          'open(os.path.join(start["out"],"big"),"wb").write(b"0"*(70*1024*1024))\n')
        job_config(store, entry=flood)
        assert JobRunner(store, 'P1', launcher=SandboxLauncher()).run('migrate')['status'] == 'error'
    finally:
        for path in (ROOT / '.runtime/work').glob('adr009-job-*'):
            shutil.rmtree(path, ignore_errors=True)


def test_T4_7_export_paths_and_content(store, tmp_path):
    owner(store)
    with pytest.raises(DataError, match='EXPORT_PATH_TRACKED'):
        check_export_path(ROOT / 'docs' / 'export-here', ROOT)
    assert check_export_path(ROOT / 'reports' / 'export-ok', ROOT)                  # ignored path
    result = export_documents(store, 'P1', tmp_path / 'export', ROOT)                  # outside the worktree
    text = (tmp_path / 'export' / 'persona.md').read_text(encoding='utf-8')
    assert result['exported'] == ['persona.md'] and '"visibility": "public"' in text and '"revision_id"' in text
    assert not any((tmp_path / 'export').glob('*messages*')) and 'episodes' not in text


def test_T4_9_persona_job_run_only_for_development_tasks(store):
    from asuna.development import PERSONA_JOB_TOOLS
    job_config(store)
    plan = json.dumps({'next': 'delegate', 'goal': '整理', 'constraints': [], 'recall_query': '', 'speak_before_action': False})
    try:                                     # dm-b has no workspace grant: delegation is refused outright
        group = Coordinator(store, FakeLane(store, [LaneResult('交给行动脑。'), LaneResult(plan)])).ingest(event('job-g', scene='dm-b', person='B'))
    except Denied as refused:
        assert str(refused) == 'WORKSPACE_NOT_AUTHORIZED'
        group = {}
    task = store.db.tasks.find_one({'_id': group['task_id']}) if group.get('task_id') else None
    assert task is None or 'persona_job_run' not in task['allowed_capabilities']
    assert PERSONA_JOB_TOOLS[0]['name'] == 'persona_job_run'
    from asuna.persona_jobs import tool_result
    run = JobRunner(store, 'P1', launcher=DirectLauncher()).run('migrate', dry_run=False,
                                                                args={'manifest': MANIFEST + [{'path': 'notes/unregistered.txt', 'layer': 'note'}],
                                                                      'questions': []})
    payload = json.dumps(tool_result(run), ensure_ascii=False)
    for excerpt in ('热可可', '书架', '早上先看一眼待办', 'diary/2026-01.md'):
        assert excerpt not in payload, excerpt
    assert set(tool_result(run)) == {'run_id', 'job', 'status', 'exit_code', 'dry_run', 'counts', 'report_artifact_ids', 'reason'}


def test_T4_11_owner_private_derived_data_stays_out_of_linked_public_scenes(store):
    owner(store)
    from asuna.visibility import without_link_downgrades
    store.config['context_links'] = {'g1': ['dm-a']}
    cleaned, rejected = without_link_downgrades(store.config)
    assert rejected and cleaned['context_links']['g1'] == []
    Coordinator(store, FakeLane(store, [LaneResult('OWNER_MONOLOGUE_CANARY'), decide(), LaneResult('好。')])).ingest(event('own-1'))
    store.config.update(cleaned)
    _, context, _ = ContextBuilder(store).prepare(event('pub-1', scene='g1'), 'P1')
    assert 'OWNER_MONOLOGUE_CANARY' not in json.dumps(context, ensure_ascii=False)


def test_T4_12_consult_from_a_public_task_sees_no_owner_private_material(store):
    owner(store)
    from asuna.documents import DocumentStore
    docs = DocumentStore(store, 'P1')
    docs.apply('persona', {'op': 'append_section', 'heading': '私密', 'visibility': 'owner_private', 'reason': 't'},
               'OWNER_PRIVATE_PERSONA_CANARY', base_revision_id=docs.read('persona')[0], author='operator', mutation_id='t412')
    calls = []

    class Role:
        def generate(self, binding, operation, phase, text, system):
            calls.append(text + system)
            return LaneResult('建议先确认清单。')

    plan = json.dumps({'next': 'delegate', 'goal': '整理公开清单', 'constraints': [], 'recall_query': '', 'speak_before_action': False})
    work = ROOT / '.runtime/work' / ('t412-' + uuid.uuid4().hex[:8]); work.mkdir(parents=True)
    store.config['channels'] = {'f': {'routes': {'g': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'x'},
                                'members': {'s': {'person_id': 'A', 'workspace': str(work), 'read_only_paths': []}}}}}}
    ep = Coordinator(store, FakeLane(store, [LaneResult('委托。'), LaneResult(plan)])).ingest(event('consult-g', scene='g1'))
    from asuna.tasks import TaskService
    task = TaskService(store).claim(ep['task_id'])
    Coordinator(store, Role()).consult(task, 'c1', {'question': '怎么排？'})
    assert calls and 'OWNER_PRIVATE_PERSONA_CANARY' not in calls[0]
    shutil.rmtree(work, ignore_errors=True)
