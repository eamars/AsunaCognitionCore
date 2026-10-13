"""ADR-062 phase 0: the append that creates a document says its kind. A ledger reaches every turn where it is readable
(ledgers_from_program); one made by append_section without a kind is a working document, which no turn carries."""
import pytest

from asuna.context import ledger_block
from asuna.documents import DocumentError, DocumentStore


def create(docs, slug, kind, mutation, body='一节正文'):
    intent = {'op': 'append_section', 'heading': '第一节', 'reason': 'r', **({'kind': kind} if kind else {})}
    return docs.apply(slug, intent, body, base_revision_id=docs.read(slug)[0], author='character', mutation_id=mutation)


def test_a_ledger_made_with_its_kind_reaches_her_turns_and_one_made_without_does_not(store):
    docs = DocumentStore(store, 'P1')
    create(docs, 'promises', 'ledger', 'k1')
    create(docs, 'scratch', None, 'k2')
    assert docs.read('promises')[1]['kind'] == 'ledger' and docs.read('scratch')[1]['kind'] == 'working'
    assert docs.read('promises')[1]['sections'][0]['inject'] == 'always'
    assert [item['doc'] for item in ledger_block(docs, 'owner_private')] == ['promises']


def test_a_journal_made_with_its_kind_is_a_running_record_of_rows(store):
    docs = DocumentStore(store, 'P1')
    create(docs, 'reading_log', 'journal', 'k1')
    create(docs, 'reading_log', None, 'k2', '第二节正文')
    content = docs.read('reading_log')[1]
    assert content['kind'] == 'journal' and [s['body'] for s in content['sections']] == ['一节正文', '第二节正文']
    assert store.db.journal_entries.count_documents({'slug': 'reading_log'}) == 2
    assert not store.db.state_heads.find_one({'_id': docs.key('reading_log')}), 'rows, never a whole copy'
    assert 'reading_log' in docs.slugs()


def test_a_kind_is_chosen_once_and_only_from_the_three(store):
    docs = DocumentStore(store, 'P1')
    with pytest.raises(DocumentError, match='DOC_KIND_INVALID'):
        create(docs, 'promises', 'persona', 'k1')
    create(docs, 'promises', 'ledger', 'k2')
    with pytest.raises(DocumentError, match='DOC_KIND_FIXED'):
        create(docs, 'promises', 'working', 'k3')
    create(docs, 'promises', 'ledger', 'k4', '同类再写一节照常')
    create(docs, 'reading_log', 'journal', 'k5')
    with pytest.raises(DocumentError, match='DOC_KIND_FIXED'):
        create(docs, 'reading_log', 'ledger', 'k6')
