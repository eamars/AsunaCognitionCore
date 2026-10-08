import copy,uuid,os,shutil
from pathlib import Path
import pytest
from pymongo import MongoClient
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import write_json,sha
from asuna.testing import dispose_test_store
from asuna import channel_kinds

# Fixtures use QQ scenes and people (qq:<bot>:group:<id>, qq:<account>): register the channel package's kind.
QQ_CHANNEL={'python':ROOT/'packages'/'channels'/'napcat-qq'/'python','module':'napcat_qq'}
channel_kinds.load([QQ_CHANNEL])

# Commands run under the Host's sandbox (sandbox_backend.py). Tests wrap them the way the live Host's ctx.sandbox does:
# DSH's own provider (tests/dsh_sandbox.mjs) picks this OS's runner, writes confined to the given root (ADR-019: the
# plugin inherits DSH's platform layer). Without a usable runner, sandboxed features are off. One wrap per root.
_WRAPS={}


def _dsh_wrap(root):
    import json,subprocess
    if root not in _WRAPS:
        node=shutil.which('node')
        out=subprocess.run([node,str(Path(__file__).with_name('dsh_sandbox.mjs')),root],cwd=ROOT,capture_output=True,
                           text=True,timeout=60).stdout if node else ''
        try:_WRAPS[root]=json.loads(out or '{}')
        except ValueError:_WRAPS[root]={'error':out[-300:]}
    return _WRAPS[root]


def _probe():
    import tempfile
    return 'prefix' in _dsh_wrap(tempfile.gettempdir())


HOST_SANDBOX=_probe()


def host_confine(argv,root):
    wrap=_dsh_wrap(str(root))
    if 'prefix' not in wrap:raise RuntimeError('SANDBOX_UNAVAILABLE: '+wrap.get('error',''))
    return [*wrap['prefix'],*argv,*wrap['suffix']]


@pytest.fixture(autouse=True)
def host_sandbox():
    from asuna import sandbox_backend
    sandbox_backend.attach(host_confine if HOST_SANDBOX else None)
    yield
    sandbox_backend.attach(None)

@pytest.fixture(autouse=True)
def preserve_temporary_evidence(request):
    root=os.environ.get('ASUNA_TEST_EVIDENCE_ROOT')
    temporary=request.getfixturevalue('tmp_path') if root and 'tmp_path' in request.fixturenames else None
    yield
    if temporary is None:return
    destination=Path(root).resolve()/sha(request.node.nodeid.encode())[:16]/'temporary-evidence'
    assert destination.is_relative_to((ROOT/'reports').resolve())
    files=[]
    for source in temporary.rglob('*'):
        if not source.is_file():continue
        assert source.resolve().is_relative_to(temporary.resolve())
        target=destination/source.relative_to(temporary);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        files.append({'artifact_path':target.relative_to(ROOT).as_posix(),'sha256':sha(target.read_bytes())})
    write_json(destination/'capture.json',{'node_id':request.node.nodeid,'files':files,'purpose':'preserve actual loopback and renderer artifacts from passing or failed tests'})
    request.node.user_properties.append(('auxiliary_evidence_path',destination.relative_to(ROOT).as_posix()))

FIXTURES=Path(__file__).with_name('fixtures')
WORLD=FIXTURES/'world.json'

# Every test gets its own database with the same migrated, audited fixture world. Building it costs
# hundreds of small round trips (collections, indexes, audited seed writes), so it is built once per
# session and each test database is filled from that snapshot with a few bulk commands per collection.
_ORIGINAL_SEED=Store.seed
_WORLD_SNAPSHOT=None


def _world_snapshot(config):
    global _WORLD_SNAPSHOT
    if _WORLD_SNAPSHOT is None:
        template=Store(config,'asuna_v2_test_TPL_'+uuid.uuid4().hex[:12])
        try:
            template.migrate();_ORIGINAL_SEED(template,WORLD)
            options={row['name']:row.get('options',{}) for row in template.db.list_collections()}
            _WORLD_SNAPSHOT={name:(options[name],
                                   {k:v for k,v in template.db[name].index_information().items() if k!='_id_'},
                                   list(template.db[name].find({})))
                             for name in options}
        finally:
            dispose_test_store(template)
    return _WORLD_SNAPSHOT


def install_world(db):
    """Reset a test database to exactly the fixture world.

    Creating collections and indexes is server-side catalog work (about 10 ms each), so a test database
    is built once and then reused: its rows are replaced with the seed and anything a test added is
    removed. A test that patches Store.seed gets the real seeding call.
    """
    if Store.seed is not _ORIGINAL_SEED:
        db.migrate();db.seed(WORLD);return
    from concurrent.futures import ThreadPoolExecutor
    from pymongo import IndexModel
    snapshot=_world_snapshot(db.config)
    present=set(db.db.list_collection_names())
    def one(name):
        if name not in snapshot:
            db.db.drop_collection(name);return
        options,indexes,documents=snapshot[name]
        if name in present:
            db.db[name].delete_many({})
        else:
            db.db.create_collection(name,**({'validator':options['validator']} if options.get('validator') else {}))
            if indexes:
                db.db[name].create_indexes([IndexModel(spec['key'],name=index,**{k:spec[k] for k in ('unique','partialFilterExpression') if k in spec})
                                            for index,spec in indexes.items()])
        if documents:
            db.db[name].insert_many(copy.deepcopy(documents),ordered=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one,sorted(present|set(snapshot))))


_POOL=[]      # built test databases ready for reuse
_OWNED=set()  # every pooled database this session created; all are dropped at session end


def pytest_sessionfinish(session,exitstatus):
    config=load()
    for name in sorted(_OWNED):
        drop_database(config,name)
        shutil.rmtree(ROOT/'.runtime/work'/name,ignore_errors=True)


@pytest.fixture
def runtime_work():
    """Make folders under .runtime/work (the sandbox only confines roots there); all are removed at teardown."""
    made=[]
    def make(prefix):
        path=ROOT/'.runtime/work'/(prefix+'-'+uuid.uuid4().hex);made.append(path);return path
    yield make
    for path in made:shutil.rmtree(path,ignore_errors=True)


def isolated_database(prefix):
    """A fresh test database name; every test drops what it created."""
    return prefix+'_'+uuid.uuid4().hex[:12]


def drop_database(config,name):
    if not name.startswith('asuna_v2_test_'):raise ValueError('ONLY_TEST_DATABASES_ARE_DROPPED')
    client=MongoClient(config['mongo_uri'],serverSelectionTimeoutMS=5000)
    try:client.drop_database(name)
    finally:client.close()


@pytest.fixture
def store(request):
    config=load();config['character_id']='demo'  # Synthetic persona of the fixture world.
    config['_host_sandbox']={'available':HOST_SANDBOX,'reason':None if HOST_SANDBOX else 'no Host sandbox runner in tests'}
    pooled=Store.seed is _ORIGINAL_SEED
    name=_POOL.pop() if pooled and _POOL else isolated_database('asuna_v2_test_M1')
    if pooled:_OWNED.add(name)
    from fixture_grant import fixture_grant
    shutil.rmtree(ROOT/'.runtime/work'/name,ignore_errors=True)   # a reused database gets an empty workspace
    fixture_grant(config,name)
    db=Store(config,name)
    try:
        install_world(db)
        yield db
    finally:
        try:
            root=os.environ.get('ASUNA_TEST_EVIDENCE_ROOT')
            if root:
                path=Path(root).resolve()
                assert path.is_relative_to((ROOT/'reports').resolve())
                path=path/sha(request.node.nodeid.encode())[:16];path.mkdir(parents=True,exist_ok=False)
                # Export through a fresh observer even when the fault case
                # closed the application's client; the database is then dropped.
                observer=Store(load(),db.name)
                try:
                    trace=list(observer.db.audit_events.find({}));write_json(path/'trace.json',trace)
                    write_json(path/'fixture.json',{'node_id':request.node.nodeid,'database':db.name,'lane':'fake unless the named test explicitly creates a real native lane','trace_sha256':sha((path/'trace.json').read_bytes()),'task_states':list(observer.db.tasks.find({})),'received_messages':list(observer.db.sink_receipts.find({}))})
                finally:observer.client.close()
                request.node.user_properties.append(('evidence_path',path.relative_to(ROOT).as_posix()))
        finally:
            if pooled:
                db.client.close();_POOL.append(name)                # reset by the next test; dropped at session end
            else:
                dispose_test_store(db)
                shutil.rmtree(ROOT/'.runtime/work'/name,ignore_errors=True)
            for derived in getattr(db,'derived_databases',[]):   # replay targets etc.
                drop_database(config,derived)
