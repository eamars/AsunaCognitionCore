import uuid,os,shutil
from pathlib import Path
import pytest
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import write_json,sha

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

@pytest.fixture
def store(request):
    db=Store(load(),'asuna_v2_test_M1_'+uuid.uuid4().hex[:12])
    db.migrate();db.seed()
    yield db
    root=os.environ.get('ASUNA_TEST_EVIDENCE_ROOT')
    if root:
        path=Path(root).resolve()
        assert path.is_relative_to((ROOT/'reports').resolve())
        path=path/sha(request.node.nodeid.encode())[:16];path.mkdir(parents=True,exist_ok=False)
        # A fault case deliberately closes its application client. Inspect the
        # retained isolated DB through a separate observer connection.
        observer=Store(load(),db.name)
        try:
            trace=list(observer.db.audit_events.find({}));write_json(path/'trace.json',trace)
            write_json(path/'fixture.json',{'node_id':request.node.nodeid,'database':db.name,'lane':'fake unless the named test explicitly creates a real native lane','trace_sha256':sha((path/'trace.json').read_bytes()),'task_states':list(observer.db.tasks.find({})),'received_messages':list(observer.db.sink_receipts.find({}))})
        finally:observer.client.close()
        request.node.user_properties.append(('evidence_path',path.relative_to(ROOT).as_posix()))
    db.client.close()
    # Tests retain their isolated databases for audit; no broad cleanup.
