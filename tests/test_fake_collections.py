"""The offline checks' fake stores give the record owners the same rows the fake holds (tests/fake_collections.py):
a write through an owner is read back from the fake, and a fake that keeps a list refuses a write instead of losing
it."""
import pytest

import fake_collections
from asuna.records import scenes as scene_records


class Rows:
    def __init__(self, rows):
        self.rows = rows


class Store:
    def __init__(self, scenes):
        self.db = type('DB', (), {})()
        self.db.scenes = Rows(scenes)
        self.collection = fake_collections.collections(self.db)


def test_a_write_through_an_owner_is_read_back_from_the_fake():
    store = Store({'g': {'_id': 'g', 'kind': 'group', 'sequence': 4}})
    assert scene_records.next_seq(store, 'g') == 5
    scene_records.note_tokens(store, 'g', 12)
    assert store.db.scenes.rows['g']['sequence'] == 5 and store.db.scenes.rows['g']['conversation_tokens'] == 12
    assert scene_records.get(store, 'g')['sequence'] == 5


def test_a_fake_that_keeps_a_list_is_read_but_refuses_a_write():
    store = Store([{'_id': 'g', 'kind': 'group', 'sequence': 4}])
    assert scene_records.get(store, 'g')['kind'] == 'group'
    with pytest.raises(TypeError):
        scene_records.next_seq(store, 'g')
    assert store.db.scenes.rows == [{'_id': 'g', 'kind': 'group', 'sequence': 4}]
