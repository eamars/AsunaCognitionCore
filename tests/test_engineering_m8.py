import errno
from unittest.mock import patch
import pytest
from asuna.evidence import Evidence,LocalHttp
from asuna.state import Denied
from test_engineering_m1 import event,normal


def test_E21_disk_full_before_request_and_closed_mongo(store,tmp_path):
    evidence=Evidence(tmp_path/'full');http=LocalHttp(evidence)
    try:
        with patch('asuna.evidence.write_json',side_effect=OSError(errno.ENOSPC,'injected disk full')):
            with patch.object(http.client,'send') as send:
                with pytest.raises(OSError):http.request('POST','http://127.0.0.1:9/v1/chat/completions','summary',{'input':'test'})
                send.assert_not_called()
    finally:http.client.close()
    coordinator,lane=normal(store);store.client.close()
    with pytest.raises(Exception):coordinator.ingest(event())
    assert not lane.calls


def test_E19_transitive_private_source_laundering_denied(store):
    store.put('memory_units',{'_id':'claimed-global-summary','scope_key':'global-safe','status':'active','source_event_ids':['M09'],'body_markdown':'删除名字后的描述'})
    store.init_head('overlay:P1','global-safe',{'body':'fixture overlay'},[]);head,base=store.head('overlay:P1','global-safe')
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):
        store.mutate('overlay:P1','global-safe',base['_id'],{'body':'全局不应看到私域衍生内容'},['claimed-global-summary'],'global-safe','laundered')
