"""None in an owner's read, one rule (ADR-104, design section 4): a fence (conversation, scope, epoch, persona, the
person or requester whose records are read) given None finds nothing, without a read; a value condition (a state,
kind, lane, project, character context) given None finds the records whose field is null or missing, as MongoDB's
`{field: None}` did.

Guards: a publication result without a project still supersedes the project-less publications waiting before it (else
one of them asks for a Host restart forever), and a conversation without an epoch still finds its main session."""
from asuna import condense
from asuna.records import episodes as episode_records
from asuna.records import receipts as receipt_records
from asuna.records import sessions as session_records

PUBLISH = 'self_development_publish'


def counted(store):
    """The store's reads counted: the names of the collections asked for."""
    asked, collection = [], store.collection
    store.collection = lambda name: asked.append(name) or collection(name)
    return asked


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


def test_receipts_a_state_of_none_is_a_receipt_without_one_and_an_id_of_none_reads_nothing(store):
    receipt_records.save_sink(store, {'_id': 'stateless', 'kind': PUBLISH}, stream='stateless')
    receipt(store, 'applied')
    assert [row['_id'] for row in receipt_records.sink_of_kind(store, PUBLISH, state=None).rows()] == ['stateless']
    asked = counted(store)
    assert receipt_records.lane_get(store, None) is None and receipt_records.sink_get(store, None) is None
    assert asked == []


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


def test_sessions_a_lane_of_none_is_a_session_without_one_and_a_persona_of_none_reads_nothing(store):
    session_records.save(store, {'_id': 'laneless', 'binding_key': 'native-host:laneless', 'native_host': True,
                                 'scene_id': 'g-x'}, stream='native-binding:laneless')
    binding(store, 'with-lane', scene_id='g-x')
    assert [row['_id'] for row in session_records.native(store, lane=None).rows()] == ['laneless']
    asked = counted(store)
    assert session_records.main(store, 'g-x', persona=None) is None and asked == []


def test_episodes_a_fence_of_none_reads_nothing_and_so_does_a_kind_of_none(store):
    """A turn's kind is required (never null or missing), so a kind of None has no turn to find."""
    episode_records.save(store, {'_id': 'ep-x', 'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external',
                                 'persona': 'demo'}, stream='ep-x')
    assert episode_records.get(store, 'ep-x', persona='demo')['_id'] == 'ep-x'
    asked = counted(store)
    assert episode_records.get(store, 'ep-x', persona=None) is None
    assert episode_records.of_source(store, 'ev', scene=None) is None
    assert episode_records.of_kind(store, None).rows() == []
    assert episode_records.open(store, ['X'], kind=None).rows() == []
    assert asked == []


def test_tasks_a_fence_of_none_reads_nothing_and_a_state_or_a_side_of_none_is_a_record_without_one(store):
    from asuna.records import tasks as task_records
    task_records.save(store, {'_id': 't-x', 'request_key': 't-x', 'scene_id': 'g', 'scope_key': 's',
                              'policy_epoch': 1, 'requester_id': 'p'}, stream='t-x')          # no `state`
    task_records.save_message(store, {'_id': 'm-x', 'task_id': 't-x', 'text': 'hi'}, stream='t-x')   # no `from`
    assert task_records.get(store, 't-x', state=None)['_id'] == 't-x'
    assert [row['_id'] for row in task_records.thread(store, 't-x', sender=None).rows()] == ['m-x']
    assert task_records.thread_message(store, 'm-x', sender=None)['_id'] == 'm-x'
    asked = counted(store)
    assert task_records.get(store, 't-x', scene=None) is None and task_records.get(store, 't-x', requester=None) is None
    assert task_records.by_prefix(store, 't-', scene='g', requester=None, epoch=1).rows() == []
    assert task_records.recent_with_inputs(store, 'g', None, 1) == [] and task_records.thread(store, None).rows() == []
    assert asked == []


def test_plans_a_fence_of_none_reads_nothing_and_an_outcome_or_a_status_of_none_is_a_plan_without_one(store):
    from asuna.records import plans as plan_records
    plan_records.save(store, {'_id': 'p-x', 'scene_id': 'g', 'person_id': 'p', 'policy_epoch': 1,
                              'kind': 'settlement'}, stream='p-x')             # no `status`, no `last_outcome`
    assert [row['_id'] for row in plan_records.with_outcome(store, 'g', ['settlement'], None).rows()] == ['p-x']
    assert plan_records.count_status(store, None) == 1
    assert [row['_id'] for row in plan_records.in_status(store, status=None).rows()] == ['p-x']
    asked = counted(store)
    assert plan_records.get(store, 'p-x', person=None) is None and plan_records.get(store, 'p-x', scene=None) is None
    assert plan_records.of_conversation(store, 'g', epoch=None).rows() == []
    assert plan_records.with_outcome(store, None, ['settlement'], None).rows() == []
    assert asked == []
