"""Tags given with a section rewrite apply (owner 2026-10-06), and the receipt says what the section now is."""
from asuna.documents import DocumentStore


def test_replace_section_with_tags_applies_them(store):
    docs = DocumentStore(store, 'P1')
    first = docs.apply('work', {'op': 'append_section', 'heading': '源码', 'visibility': 'public', 'inject': 'always', 'reason': 'r'},
                       'a', base_revision_id=None, author='character', mutation_id='m1')
    _, content = docs.read('work')
    sid = content['sections'][0]['sid']
    docs.apply('work', {'op': 'replace_section', 'sid': sid, 'visibility': 'owner_private', 'reason': 'r'}, 'b',
               base_revision_id=first['_id'], author='character', mutation_id='m2')
    section = docs.read('work')[1]['sections'][0]
    assert (section['body'], section['visibility'], section['inject']) == ('b', 'owner_private', 'always')


def test_her_write_receipt_names_the_new_sections_sid_and_its_tags(store):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_engineering_m1 import THINK
    lane = FakeLane(store, [FakeTurn([THINK, ('write_document', {'doc': 'work', 'do': 'append_section', 'heading': '新的一节',
                                                                 'content': 'x', 'why': 'r'})], '好')])
    from test_adr009_p5_rhythm import scheduler
    scheduler(store)                                  # the owner's private chat dm-a
    ep = Coordinator(store, lane).ingest({'event_id': 'w1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '记一下'})
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    [row] = [row for row in lane.tool_results if row[2] == 'write_document']
    assert "'sid': '" in str(row) and 'owner_private' in str(row), row


def test_a_section_is_found_by_its_heading_or_a_remembered_spelling_unless_two_share_it(store):
    import pytest
    from asuna.documents import DocumentError
    docs = DocumentStore(store, 'P1')
    rev = docs.apply('work', {'op': 'append_section', 'heading': '（判 bot 的对照名单）', 'reason': 'r'}, 'a',
                     base_revision_id=None, author='character', mutation_id='m1')
    rev = docs.apply('work', {'op': 'append_section', 'heading': '另一节', 'reason': 'r'}, 'b',
                     base_revision_id=rev['_id'], author='character', mutation_id='m2')
    # The heading as written, then as she remembered it with other punctuation: both name that section.
    rev = docs.apply('work', {'op': 'replace_section', 'sid': '（判 bot 的对照名单）', 'reason': 'r'}, 'a2',
                     base_revision_id=rev['_id'], author='character', mutation_id='m3')
    rev = docs.apply('work', {'op': 'replace_section', 'sid': '：判 bot 的对照名单', 'reason': 'r'}, 'a3',
                     base_revision_id=rev['_id'], author='character', mutation_id='m4')
    assert [s['body'] for s in docs.read('work')[1]['sections']] == ['a3', 'b']
    # A second heading with the same slug: the remembered spelling names neither, and the refusal lists the sids.
    rev = docs.apply('work', {'op': 'append_section', 'heading': '判 bot 的对照名单', 'reason': 'r'}, 'c',
                     base_revision_id=rev['_id'], author='character', mutation_id='m5')
    with pytest.raises(DocumentError) as refused:
        docs.apply('work', {'op': 'replace_section', 'sid': '：判 bot 的对照名单', 'reason': 'r'}, 'x',
                   base_revision_id=rev['_id'], author='character', mutation_id='m6')
    assert refused.value.code == 'DOC_SECTION_NOT_FOUND' and '判-bot-的对照名单-2' in str(refused.value)

