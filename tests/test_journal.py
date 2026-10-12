"""A running record (documents.JOURNALS, her work_log) is one row per entry, read and written like a document: as one
document every write copied the whole record, and work_log neared the 1 MiB revision limit within a week."""
import pytest

from asuna.documents import DocumentError, DocumentStore
from asuna.state import Conflict


def write(docs, intent, body=None, mutation='m1'):
    return docs.apply('work_log', {'reason': 'r', **intent}, body, base_revision_id=docs.read('work_log')[0],
                      author='character', mutation_id=mutation)


def test_an_entry_is_its_own_row_and_a_rewrite_keeps_the_old_text_beside_it(store):
    docs = DocumentStore(store, 'P1')
    first = write(docs, {'op': 'append_section', 'heading': '一号'}, '第一节', 'm1')
    write(docs, {'op': 'append_section', 'heading': '二号'}, '第二节', 'm2')
    revision, content = docs.read('work_log')
    assert [s['body'] for s in content['sections']] == ['第一节', '第二节'] and content['kind'] == 'journal'
    assert content['sections'][0]['inject'] == 'on_demand' and content['sections'][0]['visibility'] == 'owner_private'
    assert store.db.journal_entries.count_documents({}) == 2
    assert store.db.state_revisions.count_documents({'entity_key': {'$regex': 'work_log'}}) == 0, 'no whole copies'
    sid = content['sections'][0]['sid']
    write(docs, {'op': 'replace_section', 'sid': sid}, '第一节改过', 'm3')
    assert docs.read('work_log')[1]['sections'][0]['body'] == '第一节改过'
    kept = [row['body'] for row in store.db.journal_revisions.find({'sid': sid}).sort('created_at', 1)]
    assert kept == ['第一节', '第一节改过'], 'each version of an entry stays beside it'
    write(docs, {'op': 'set_tags', 'sid': sid, 'inject': 'never'}, None, 'm4')
    assert docs.read('work_log')[1]['sections'][0]['inject'] == 'never'
    assert 'work_log' in docs.slugs()
    # The same intent again (a crash after it committed) answers the same, and writes nothing more.
    assert write(docs, {'op': 'append_section', 'heading': '一号'}, '第一节', 'm1')['_id'] == first['_id']
    assert store.db.journal_entries.count_documents({}) == 2


def test_a_stale_write_and_a_ledger_only_op_are_refused(store):
    docs = DocumentStore(store, 'P1')
    write(docs, {'op': 'append_section', 'heading': '一号'}, '第一节', 'm1')
    old = docs.read('work_log')[0]
    write(docs, {'op': 'append_section', 'heading': '二号'}, '第二节', 'm2')
    with pytest.raises(Conflict):
        docs.apply('work_log', {'op': 'append_section', 'heading': '三号', 'reason': 'r'}, 'x', base_revision_id=old,
                   author='character', mutation_id='m3')
    with pytest.raises(DocumentError, match='DOC_OP_NOT_ALLOWED'):
        write(docs, {'op': 'correction', 'sid': docs.read('work_log')[1]['sections'][0]['sid']}, 'x', 'm4')
    with pytest.raises(DocumentError, match='DOC_HEADING_REQUIRED'):
        write(docs, {'op': 'append_section'}, 'x', 'm5')


def test_the_record_kept_as_one_document_moves_into_rows_once(store):
    docs = DocumentStore(store, 'P1')
    content = {'kind': 'working', 'title': 'work_log', 'source': {'origin': 'asuna'}, 'sections': [
        {'sid': 'a', 'heading': 'A', 'body': '甲', 'body_sha256': 'x', 'visibility': 'owner_private', 'inject': 'on_demand',
         'tags': []},
        {'sid': 'b', 'heading': 'B', 'body': '乙', 'body_sha256': 'y', 'visibility': 'owner_private', 'inject': 'on_demand',
         'tags': []}]}
    before = docs._commit('work_log', content, base_revision_id=None, reason='r', author='character', mutation_id='old')
    revision, read = docs.read('work_log')
    assert revision == before['_id'], 'what she read before is still the base she writes against'
    assert [s['body'] for s in read['sections']] == ['甲', '乙']
    assert not store.db.state_heads.find_one({'_id': docs.key('work_log')})
    assert store.db.state_revisions.find_one({'_id': before['_id']}), 'the old revisions stay'
    write(docs, {'op': 'append_section', 'heading': 'C'}, '丙', 'new')
    assert [s['body'] for s in docs.read('work_log')[1]['sections']] == ['甲', '乙', '丙']
    assert docs.slugs().count('work_log') == 1


def test_her_recall_reads_an_entry_as_a_section(store):
    from asuna.role_tools import read_sections
    docs = DocumentStore(store, 'P1')
    write(docs, {'op': 'append_section', 'heading': '名单'}, '一节正文', 'm1')
    sid = docs.read('work_log')[1]['sections'][0]['sid']
    out, missing = read_sections(store, {'persona': 'P1', 'scene_id': 'local'}, [{'doc': 'work_log', 'sid': sid}],
                                 'owner_private')
    assert not missing and out[0]['body'] == '一节正文'
