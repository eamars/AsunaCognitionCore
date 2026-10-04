import pytest
from asuna.state import Denied


def test_E19_transitive_private_source_laundering_denied(store):
    store.put('memory_units',{'_id':'claimed-global-summary','scope_key':'global-safe','status':'active','source_event_ids':['M09'],'body_markdown':'删除名字后的描述'})
    store.init_head('overlay:P1','global-safe',{'body':'fixture overlay'},[]);head,base=store.head('overlay:P1','global-safe')
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):
        store.mutate('overlay:P1','global-safe',base['_id'],{'body':'全局不应看到私域衍生内容'},['claimed-global-summary'],'global-safe','laundered')
