"""ADR-009 E19 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a message source cannot be
laundered."""
import pytest

from asuna.records import memories as memory_records
from asuna.records import messages as message_records
from asuna.records import heads as head_records
from asuna.state import Denied

pytestmark = pytest.mark.world                # `store` is the fixture world


def test_E19_message_source_cannot_be_laundered(store):
    message_records.save(store, {'_id':'private-source','scope_key':'scene:dm-a','text':'synthetic private source'})
    memory_records.save(store, {'_id':'claimed-public','scope_key':'global-safe','status':'active','source_event_ids':['private-source'],'body_markdown':'anonymous reinterpretation'})
    head=head_records.init(store, 'relationship:P1','global-safe',{'body':'fixture relationship'},[])
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):head_records.mutate(store, 'relationship:P1','global-safe',head['revision_id'],{'body':'new'},['claimed-public'],'global-safe','invalid-source')


