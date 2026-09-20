import json,uuid
from unittest.mock import patch
from asuna.config import ROOT,load
from asuna.evidence import Evidence,write_json
from asuna.state import Store
from asuna.retrieval import Retrieval
from asuna.privacy import PrivacyService

name='cache-probe-'+uuid.uuid4().hex[:12];ev=Evidence(ROOT/'reports'/name);store=Store(load(),'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed();r=Retrieval(store,ev);status='FAIL'
try:
    r.index_pending();assert r.ensure_index()
    query='A 私聊里的私密盒号是什么？'
    first,m1=r.search('scene:dm-a',1,query,require_vector=True)
    second,m2=r.search('scene:dm-a',1,query,require_vector=True)
    assert any(m['_id']=='M09' for m in first) and m2['cache_hit'] and m1['selected']==m2['selected']
    group,mg=r.search('scene:g1',1,query,require_vector=True)
    assert not mg['cache_hit'] and 'PRIVATE_A_7e19_lantern' not in json.dumps(group)
    key=m2['cache_key_sha256'];old=r.cache[key]['vector']
    PrivacyService(store).delete_memory('M09',operator=True)
    after,m3=r.search('scene:dm-a',2,query,require_vector=True)
    assert not m3['cache_hit'] and m3['cache_key_sha256']!=key and 'M09' not in m3['selected']
    with patch('pymongo.synchronous.collection.Collection.aggregate',return_value=iter([{'_id':'M09','score':1.0}])) as stale_server:
        stale,m4=r.search('scene:dm-a',2,query+'（索引滞后注入）',require_vector=True)
        stale_server.assert_called_once()
    assert 'M09' not in m4['selected'] and any(x['id']=='M09' and x['reason']=='authoritative_recheck' for x in m4['excluded'])
    assert 'PRIVATE_A_7e19_lantern' not in json.dumps(r.cache) and 'body_markdown' not in json.dumps(r.cache)
    status='PASS';ev.record('cache.probe',{'before':m1,'hit':m2,'other_scope':mg,'after_erasure':m3,'stale_vector_fault':m4,'stale_vector_fault_mode':'injected old ID; real Mongo authority and cache','old_cached_vector_ids':[v['_id'] for v in old]})
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:r.close();store.client.close()
write_json(ev.root/'result.json',{'test_id':'PROBE-E11','status':status,'mode':'real_Mongo_vector_embedding_and_scoped_ID_cache','commands':[{'argv':['python','tools/probe_cache.py'],'exit_code':0 if status=='PASS' else 1}]});print(json.dumps({'run':name,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
