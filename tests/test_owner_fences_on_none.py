"""A fence the replaced read wrote as an equality on a value that may be None keeps its meaning in the owner: None
matches a record whose field is null or missing, as MongoDB's `{field: None}` did (ADR-104 B5).

Guards: a publication result without a project still supersedes the project-less publications waiting before it (else
one of them asks for a Host restart forever), and a conversation without an epoch still finds its main session."""
from asuna import condense
from asuna.records import receipts as receipt_records
from asuna.records import sessions as session_records

PUBLISH = 'self_development_publish'


def receipt(store, receipt_id, **fields):
    receipt_records.save_sink(store, {'_id': receipt_id, 'kind': PUBLISH, 'state': 'APPLIED', **fields},
                              stream=receipt_id)


def test_a_publication_without_a_project_supersedes_the_earlier_ones_without_one(store):
    receipt(store, 'missing')                         # no `project` at all
    receipt(store, 'null', project=None)
    receipt(store, 'core', project='core')
    receipt(store, 'newest')                          # the result being published now: left out by id
    older = receipt_records.sink_of_kind(store, PUBLISH, project=None, states=['APPLIED', 'HOST_RESTART_REQUIRED'],
                                         besides='newest').rows()
    assert sorted(row['_id'] for row in older) == ['missing', 'null']
    assert [row['_id'] for row in receipt_records.sink_of_kind(store, PUBLISH, project='core').rows()] == ['core']


def binding(store, session_id, **fields):
    session_records.save(store, {'_id': session_id, 'binding_key': 'native-host:' + session_id, 'native_host': True,
                                 'main_conversation': True, 'lane': 'character', 'scene_id': 'g-none',
                                 'persona': 'demo', 'cwd': 'work', **fields}, stream='native-binding:' + session_id)


def test_a_conversation_without_an_epoch_finds_its_main_session_missing_one_too(store):
    binding(store, 'missing-epoch', character_context='ctx')          # no `policy_epoch` at all
    found = condense.main_session(store, {'_id': 'g-none', 'character_context': 'ctx'}, 'demo')
    assert found == ('missing-epoch', 'work')
    assert session_records.main(store, 'g-none', persona='demo', epoch=1, context='ctx') is None
    binding(store, 'null-both', scene_id='g-null', policy_epoch=None, character_context=None)
    assert session_records.main(store, 'g-null', persona='demo', epoch=None, context=None)['_id'] == 'null-both'
