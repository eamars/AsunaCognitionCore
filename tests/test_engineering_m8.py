import pytest
from asuna.records import heads as head_records
from asuna.state import Denied


def test_E19_transitive_private_source_laundering_denied(store):
    store.put('memory_units',{'_id':'claimed-global-summary','scope_key':'global-safe','status':'active','source_event_ids':['M09'],'body_markdown':'删除名字后的描述'})
    head_records.init(store, 'relationship:P1','global-safe',{'body':'fixture relationship'},[]);head,base=head_records.current(store, 'relationship:P1','global-safe')
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):
        head_records.mutate(store, 'relationship:P1','global-safe',base['_id'],{'body':'全局不应看到私域衍生内容'},['claimed-global-summary'],'global-safe','laundered')
