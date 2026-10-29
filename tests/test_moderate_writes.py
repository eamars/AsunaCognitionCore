"""A write is checked as MongoDB's moderate validation checks (ADR-104 decision 9; the rule is `Handle.replace` in
src/asuna/store/__init__.py): a whole record the catalog refuses is written only over a stored record it refuses too,
an old record of another kind, so an erasure or an audit rebase never stops halfway on one and an old record can still
be saved; a record that passes cannot be made to fail, and a new record is always checked. On the unit run's store."""
import pytest

from asuna import audit
from asuna.records import messages as message_records
from asuna.records.view import redact
from asuna.store.errors import RecordInvalid

SCOPE = 'scene:old'


def old_line(store, line_id='old-1', **fields):
    """A line as an older version of the code wrote it: `scene_seq` as text, where the catalog declares a number.
    Written past the shared layer, as it stands on her database."""
    line = {'_id': line_id, 'schema_version': 1, 'revision': 1, 'scene_id': 'old', 'scope_key': SCOPE,
            'scene_seq': '7', 'direction': 'inbound', 'text': '旧的一行', **fields}
    store.adapter.insert('messages', [line], True)
    return line


def test_an_old_record_of_another_kind_can_be_replaced_redacted_and_rebased(store):
    line = old_line(store)
    saved = message_records.save(store, {**line, 'text': '改过的一行'}, expected=line['revision'], stream='old')
    assert store.collection('messages').get('old-1')['text'] == '改过的一行' and saved['scene_seq'] == '7'
    redact(store, 'messages', SCOPE, 'del-1', 2)
    redacted = store.collection('messages').get('old-1')
    assert redacted['deletion_id'] == 'del-1' and redacted['text'] == '[deleted]' and redacted['scene_seq'] == '7'
    store.audit('old', 'state.note', {'said': 'x'}, SCOPE)
    first = audit.events(store, stream='old', by='seq').rows()[0]
    store.adapter.replace('audit_events', {**first, 'occurred_at': 5}, None, (), False)     # an old record's time
    audit.redact_streams(store, SCOPE, 'del-1', [], [])
    rebased = audit.events(store, stream='old', by='seq').rows()
    assert all(event['payload'].get('redacted_by') == 'del-1' for event in rebased)
    audit.verify(rebased)


def test_a_record_that_passes_cannot_be_made_to_fail(store):
    line = message_records.save(store, {'_id': 'new-1', 'scene_id': 'now', 'scope_key': 'scene:now', 'scene_seq': 1,
                                        'direction': 'inbound', 'text': '一行'}, stream='now')
    with pytest.raises(RecordInvalid, match='RECORD_KIND'):
        message_records.save(store, {**line, 'scene_seq': '八'}, expected=line['revision'], stream='now')
    assert store.collection('messages').get('new-1')['scene_seq'] == 1


def test_a_new_record_is_always_checked(store):
    rows = store.collection('messages')
    wrong = {'_id': 'fresh', 'schema_version': 1, 'revision': 1, 'scene_seq': '7'}
    with pytest.raises(RecordInvalid, match='RECORD_KIND'):
        rows.insert(wrong)
    with pytest.raises(RecordInvalid, match='RECORD_KIND'):
        rows.replace(wrong, create=True)
    assert rows.get('fresh') is None
