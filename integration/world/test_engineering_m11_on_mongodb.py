"""ADR-009 E19 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a rollback refuses another
scope and keeps the sources counted."""
import pytest

from asuna.records import heads as head_records
from asuna.state import Denied
from asuna.memory import MemoryService

pytestmark = pytest.mark.world                # `store` is the fixture world


def test_E19_rollback_rejects_other_scope_and_preserves_source_accounting(store):
    old=head_records.current(store, 'relationship:A','scene:dm-a')[1]
    new=head_records.mutate(store, 'relationship:A','scene:dm-a',old['_id'],{'body':'new'},['M02'],'scene:dm-a','new-relation')
    service=MemoryService(store)
    foreign=head_records.current(store, 'relationship:B','scene:dm-b')[1]
    with pytest.raises(Denied):service.rollback('relationship:A','scene:dm-a',foreign['_id'],new['_id'],'bad',operator=True)
    back=service.rollback('relationship:A','scene:dm-a',old['_id'],new['_id'],'back',operator=True)
    assert back['content']==old['content'] and back['processed_source_ids']==new['processed_source_ids']


