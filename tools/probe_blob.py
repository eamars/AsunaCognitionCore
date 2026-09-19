import json,uuid
from asuna.config import load,ROOT
from asuna.state import Store,Denied
from asuna.blobs import BlobStore
from asuna.privacy import PrivacyService
from asuna.evidence import Evidence,write_json,sha

name='blob-probe-'+uuid.uuid4().hex[:12];ev=Evidence(ROOT/'reports'/name);store=Store(load(),'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed()
status='FAIL'
try:
    blob=BlobStore(store);data=('large synthetic PRIVATE_SCOPE_BODY '+uuid.uuid4().hex+'\n').encode()*32768
    ref=blob.put(data,'scene:dm-a','oversize_probe',source_ids=['M09'])
    assert len(data)>1024*1024 and blob.get(ref['artifact_id'],'scene:dm-a',operator=True)==data
    for scope,op in [('scene:g1',True),('scene:dm-a',False)]:
        try:blob.get(ref['artifact_id'],scope,operator=op)
        except Denied:pass
        else:raise AssertionError('IDOR_ACCEPTED')
    deletion=PrivacyService(store).delete_memory('M09',operator=True)
    assert deletion['gridfs_blobs_removed']==1 and store.db.artifact_blobs.files.count_documents({})==0 and store.db.artifact_blobs.chunks.count_documents({})==0
    status='PASS';ev.record('blob.probe',{'input_size':len(data),'input_sha256':sha(data),'reference':ref,'deletion_id':deletion['deletion_id']})
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:store.client.close()
write_json(ev.root/'result.json',{'test_id':'PROBE-E06-blob','status':status,'mode':'real_Mongo_GridFS','commands':[{'argv':['python','tools/probe_blob.py'],'exit_code':0 if status=='PASS' else 1}]})
print(json.dumps({'run':name,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
