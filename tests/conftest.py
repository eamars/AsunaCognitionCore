import copy,uuid,os,re,shutil,subprocess,sys
from pathlib import Path
import importlib.util

# A unit run reaches no database server (ADR-104). Two locks, each enough alone: every MongoDB client is the in-process
# stand-in of unit_run_site/sitecustomize.py (here, and in every Python process the run starts with its environment),
# and every configuration the run loads names an address that cannot resolve (RFC 6761 .invalid), so a process that
# does not inherit the environment, such as a confined command, has no server to reach either.
UNIT_RUN_SITE=Path(__file__).with_name('unit_run_site')
os.environ['ASUNA_UNIT_RUN']='1'
os.environ['PYTHONPATH']=os.pathsep.join(filter(None,[str(UNIT_RUN_SITE),os.environ.get('PYTHONPATH')]))
_spec=importlib.util.spec_from_file_location('unit_run_stand_in',UNIT_RUN_SITE/'sitecustomize.py')
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))
NO_SERVER='mongodb://unit-run.invalid:27017/'
from asuna import config as _config
_load_settings=_config.load


def _unit_run_settings(*args,**kwargs):
    value=_load_settings(*args,**kwargs);value['mongo_uri']=NO_SERVER
    return value
_config.load=_unit_run_settings

import sandbox_temp
sandbox_temp.inherit()   # tmp_path folders a run inside DSH's Windows sandbox can use
import pytest

from asuna import repo_files
from pymongo import MongoClient
from asuna.config import ROOT,DATA
from asuna.state import Store
from asuna.evidence import write_json,sha
from asuna.testing import dispose_test_store,remove_lock_files,remove_workspace,suite_config as load
from asuna.queue import effects_lock_path
from asuna import channel_kinds

# Fixtures use QQ scenes and people (qq:<bot>:group:<id>, qq:<account>): register the channel package's kind.
QQ_CHANNEL={'python':ROOT/'packages'/'channels'/'napcat-qq'/'python','module':'napcat_qq'}
channel_kinds.load([QQ_CHANNEL])

# Every folder a test writes is under the data folder this run writes (ASUNA_DATA_ROOT, else the checkout's .runtime)
# or under pytest's --basetemp, so a run confined to one writable folder works.
WORK=DATA/'work'

# Commands run under the Host's sandbox (sandbox_backend.py). Tests wrap them the way the live Host's ctx.sandbox does:
# DSH's own provider (tests/dsh_sandbox.mjs) picks this OS's runner, writes confined to the given root (ADR-019: the
# plugin inherits DSH's platform layer). One wrap per root.
_WRAPS={}


def _dsh_wrap(root):
    import json
    if root not in _WRAPS:
        node=shutil.which('node')
        out=subprocess.run([node,str(Path(__file__).with_name('dsh_sandbox.mjs')),root],cwd=ROOT,capture_output=True,
                           text=True,timeout=60).stdout if node else ''
        try:_WRAPS[root]=json.loads(out or '{}')
        except ValueError:_WRAPS[root]={'error':out[-300:]}
    return _WRAPS[root]


def _cannot_confine():
    """Why the runner cannot confine a command in this run, or None; measured by running one where the tests confine
    theirs. A runner can wrap a command and still fail to start it: in a worktree whose folders the user may not
    re-permission, or inside a process that is itself confined, granting a folder its write right is denied."""
    from asuna import sandbox_backend
    root=WORK/('sandbox-probe-'+uuid.uuid4().hex)
    try:root.mkdir(parents=True)
    except OSError as error:return 'the data folder %s is not writable (%s)'%(DATA,error.strerror or error)
    try:
        wrap=_dsh_wrap(str(root))
        if 'prefix' not in wrap:
            return 'no Host sandbox runner here: %s'%(wrap.get('error') or 'node or the DSH sandbox package not found')
        argv=[*wrap['prefix'],sys.executable,'-c',"open('probe.txt','w').write('ok')",*wrap['suffix']]
        try:ran=subprocess.run(argv,cwd=root,env=sandbox_backend.environment(),capture_output=True,text=True,timeout=60)
        except (OSError,subprocess.SubprocessError) as error:return 'the runner did not start (%s)'%error
        if ran.returncode!=0 or not (root/'probe.txt').is_file():
            return 'exit %s: %s'%(ran.returncode,' '.join((ran.stderr or ran.stdout).split())[:300])
        return None
    finally:
        remove_workspace(root);_WRAPS.pop(str(root),None)


# The tests run as a Host that has a sandbox, so what the program grants with one is checked on every machine.
# Whether a confined command really runs here is measured once (one confined write); where none can (no runner, as on
# a host without DSH's sandbox package, or a run that is itself confined), a test skips at the command it would run:
# what it checks there is unchecked, not passed.
HOST_SANDBOX=True
CANNOT_CONFINE=_cannot_confine()
UNCHECKED='UNCHECKED, not passed: no confined command runs in this run (%s)'%CANNOT_CONFINE


# Repository guards read the tree's files through asuna.repo_files: git in a checkout, the tree and its .gitignore in
# a plain copy (a publication's candidate), so they run in both.


# Tests the in-process stand-in cannot carry: one reviewed line each, `test id | what the stand-in lacks` (a test id
# without its [parameters] covers them all). Read at collection, never caught at run time; the file goes with the
# stand-in, when the unit run moves to the store's in-memory adapter (ADR-104).
HARNESS_SKIPS=Path(__file__).with_name('harness_skips.txt')


def _harness_skips():
    listed={}
    for line in HARNESS_SKIPS.read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.startswith('#'):
            test,_,lacks=line.partition(' | ');listed[test.strip()]=lacks.strip()
    return listed


def pytest_collection_modifyitems(session,config,items):
    listed,used=_harness_skips(),set()
    for item in items:
        test=item.nodeid if item.nodeid in listed else item.nodeid.split('[')[0]
        if test in listed:
            used.add(test)
            item.add_marker(pytest.mark.skip(reason='UNCHECKED, not passed: the in-process stand-in lacks '+listed[test]))
    whole=config.args_source==pytest.Config.ArgsSource.TESTPATHS and not config.option.keyword and not config.option.markexpr
    if whole and set(listed)-used:
        raise pytest.UsageError('HARNESS_SKIP_NOT_A_TEST: tests/harness_skips.txt lists ids no test has: '+
                                ', '.join(sorted(set(listed)-used)[:10]))


def pytest_report_header(config):
    return ['asuna data folder: %s'%DATA,
            'Host sandbox: '+(UNCHECKED if CANNOT_CONFINE else 'confines commands'),
            'source tree: '+('a git checkout' if repo_files.checkout(ROOT) else 'a plain copy, read with its .gitignore')]


def host_confine(argv,root):
    if CANNOT_CONFINE:pytest.skip(UNCHECKED)
    wrap=_dsh_wrap(str(root))
    if 'prefix' not in wrap:raise RuntimeError('SANDBOX_UNAVAILABLE: '+wrap.get('error',''))
    return [*wrap['prefix'],*argv,*wrap['suffix']]


@pytest.fixture(autouse=True)
def host_sandbox():
    from asuna import sandbox_backend
    sandbox_backend.attach(host_confine)
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
        template=Store(config,isolated_database('asuna_v2_test_TPL'))
        try:
            template.migrate();_ORIGINAL_SEED(template,WORLD)
            options={name:{} for name in template.db.list_collection_names()}   # the stand-in keeps no validator
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
            for index,spec in indexes.items():     # one at a time: the stand-in's create_indexes drops a partial filter
                db.db[name].create_index(spec['key'],name=index,**{k:spec[k] for k in ('unique','partialFilterExpression','expireAfterSeconds') if k in spec})
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
        remove_workspace(WORK/name)


# A run that is killed never reaches pytest_sessionfinish, so its databases stay. Each name carries the process that
# made it (isolated_database); a session starts by dropping those whose process is gone, and the unmarked ones the
# pool made before names carried it. A run going on in another checkout keeps its own.
OWNER=re.compile(r'^asuna_v2_test_.+_p(\d+)_[0-9a-f]{12}$')
UNMARKED=re.compile(r'^asuna_v2_test_(M1|TPL)_[0-9a-f]{12}$')


def _alive(pid):
    if os.name=='nt':                              # os.kill would end the process on Windows, not probe it
        import ctypes
        kernel=ctypes.windll.kernel32
        handle=kernel.OpenProcess(0x1000,False,pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:return False
        try:
            code=ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259   # STILL_ACTIVE
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


def pytest_sessionstart(session):
    config=load()
    try:
        client=MongoClient(config['mongo_uri'],serverSelectionTimeoutMS=2000)
        try:names=client.list_database_names()
        finally:client.close()
    except Exception:
        return                                     # no Mongo: the tests that need it skip
    for name in names:
        owner=OWNER.match(name)
        if (owner and not _alive(int(owner.group(1)))) or UNMARKED.match(name):
            drop_database(config,name)
            remove_workspace(WORK/name)


@pytest.fixture
def runtime_work():
    """Make folders under the data folder's work/ (the sandbox only confines roots there); all are removed at teardown."""
    made=[]
    def make(prefix):
        path=WORK/(prefix+'-'+uuid.uuid4().hex);made.append(path);return path
    yield make
    for path in made:remove_workspace(path)


def isolated_database(prefix):
    """A fresh test database name carrying this process (a killed run's are dropped by the next session); every test
    drops what it created."""
    return '%s_p%d_%s'%(prefix,os.getpid(),uuid.uuid4().hex[:12])


def drop_database(config,name):
    if not name.startswith('asuna_v2_test_'):raise ValueError('ONLY_TEST_DATABASES_ARE_DROPPED')
    client=MongoClient(config['mongo_uri'],serverSelectionTimeoutMS=5000)
    try:client.drop_database(name)
    finally:client.close()
    remove_lock_files(effects_lock_path(name))

@pytest.fixture
def store(request):
    config=load();config['character_id']='demo'  # Synthetic persona of the fixture world.
    # The brains' models as the worker receives them from DSH's catalog (native_settings.runtime_settings).
    # The action brain sees pictures; a test whose character brain should, says so.
    for lane,modalities in (('character',['text']),('executor',['text','image'])):
        config[lane]={'model':'fixture-'+lane,'provider':'fixture','max_tokens':4096,'context_window':65536,
                      'input_modalities':modalities,'token_counter':'native-host'}
    config['_host_sandbox']={'available':True,'reason':None}
    pooled=Store.seed is _ORIGINAL_SEED
    name=_POOL.pop() if pooled and _POOL else isolated_database('asuna_v2_test_M1')
    if pooled:_OWNED.add(name)
    from fixture_grant import fixture_grant
    shutil.rmtree(WORK/name,ignore_errors=True)   # a reused database gets an empty workspace
    fixture_grant(config,name)
    db=Store(config,name)
    from asuna import capabilities
    capabilities.forget()                         # what an adapter declared is kept per run; each test declares its own
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
                remove_workspace(WORK/name)
            for derived in getattr(db,'derived_databases',[]):   # replay targets etc.
                drop_database(config,derived)
