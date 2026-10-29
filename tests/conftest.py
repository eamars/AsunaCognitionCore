import uuid,os,shutil,subprocess,sys
from pathlib import Path

# A unit run reaches no database server: its tests never need one (a test that needs one is in integration/). Two
# locks, each enough alone: ASUNA_UNIT_RUN=1 makes the store's registry and dbread refuse to open a database
# (DATABASE_IN_UNIT_RUN, here and in every process the run starts with its environment), and every configuration the
# run loads names an address that cannot resolve (RFC 6761 .invalid), so a process that does not inherit the
# environment, such as a confined command, has no server to reach either.
os.environ['ASUNA_UNIT_RUN']='1'
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
from asuna.config import ROOT,DATA
from asuna.evidence import write_json,sha
from asuna.testing import remove_workspace
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


@pytest.fixture
def runtime_work():
    """Make folders under the data folder's work/ (the sandbox only confines roots there); all are removed at teardown."""
    made=[]
    def make(prefix):
        path=WORK/(prefix+'-'+uuid.uuid4().hex);made.append(path);return path
    yield make
    for path in made:remove_workspace(path)
