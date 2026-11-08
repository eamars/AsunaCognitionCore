"""Recall's past versions of her notes (crossing.before): a past text is shown only where its own visibility, every one
it had, is readable, not only where its section is now; a running record's past is read by hashes, one revision per
text it shows. On the fixture world (in memory); dm-a is the owner's DM, g1 a group."""

from asuna import crossing, visibility
from asuna.documents import DocumentStore
from asuna.records import scenes as scene_records

PERSONA = 'P1'


def test_a_past_text_is_shown_only_where_its_own_visibility_is_readable_too(world, monkeypatch):
    """The reviewer's case: a private section rewritten to public in the same write; its old private text never reaches
    a group's recall, in a ledger or in a running record, and still comes back at home."""
    monkeypatch.setattr(crossing, 'SHOWN', 10)                   # every one found, not only the newest three
    docs = DocumentStore(world, PERSONA)
    docs.apply('facts', {'op': 'append_section', 'heading': 'kept', 'reason': 'r', 'kind': 'ledger',
                         'visibility': 'owner_private'}, 'the zephyrine key stays at home', base_revision_id=None,
               author='character', mutation_id='v-1')
    docs.apply('facts', {'op': 'replace_section', 'sid': 'kept', 'reason': 'now public', 'visibility': 'public'},
               'a key exists', base_revision_id=docs.read('facts')[0], author='character', mutation_id='v-2')
    docs.apply('work_log', {'op': 'append_section', 'heading': 'entry', 'reason': 'r', 'visibility': 'owner_private'},
               'the zephyrine plan, private', base_revision_id=docs.read('work_log')[0], author='character',
               mutation_id='v-3')
    docs.apply('work_log', {'op': 'replace_section', 'sid': 'entry', 'reason': 'now public', 'visibility': 'public'},
               'a plan', base_revision_id=docs.read('work_log')[0], author='character', mutation_id='v-4')
    # A text that was private for a while, then made public before it was rewritten, counts as private.
    docs.apply('facts', {'op': 'append_section', 'heading': 'flip', 'reason': 'r', 'visibility': 'owner_private'},
               'the zephyrine flip text', base_revision_id=docs.read('facts')[0], author='character', mutation_id='v-5')
    docs.apply('facts', {'op': 'set_tags', 'sid': 'flip', 'reason': 'r', 'visibility': 'public'}, None,
               base_revision_id=docs.read('facts')[0], author='character', mutation_id='v-6')
    docs.apply('facts', {'op': 'replace_section', 'sid': 'flip', 'reason': 'r'}, 'flipped', author='character',
               base_revision_id=docs.read('facts')[0], mutation_id='v-7')
    # A public entry of her running record rewritten, still public: its old text reaches a group's recall.
    docs.apply('work_log', {'op': 'append_section', 'heading': 'open', 'reason': 'r', 'visibility': 'public'},
               'the zephyrine walk, public', base_revision_id=docs.read('work_log')[0], author='character',
               mutation_id='v-8')
    docs.apply('work_log', {'op': 'replace_section', 'sid': 'open', 'reason': 'r'}, 'a walk',
               base_revision_id=docs.read('work_log')[0], author='character', mutation_id='v-9')
    group, home = scene_records.get(world, 'g1'), scene_records.get(world, 'dm-a')
    in_group = crossing.before(world, PERSONA, group, visibility.PUBLIC, 'zephyrine', None)
    assert [entry['now'] for entry in in_group] == ['doc:work_log#open']
    at_home = crossing.before(world, PERSONA, home, visibility.OWNER_PRIVATE, 'zephyrine', None)
    assert {entry['now'] for entry in at_home} == {'doc:facts#kept', 'doc:facts#flip', 'doc:work_log#entry',
                                                   'doc:work_log#open'}


def test_her_records_past_reads_only_the_texts_it_shows_and_a_new_row_does_not_read_the_document_again(world,
                                                                                                      monkeypatch):
    docs = DocumentStore(world, PERSONA)
    base = None
    for n, heading in enumerate(('first', 'second', 'third')):
        base = docs.apply('running-log', {'op': 'append_section', 'heading': heading, 'reason': 'r', 'kind': 'working',
                                          'visibility': 'owner_private'}, '第 %d 段' % n, base_revision_id=base,
                          author='character', mutation_id='p-%d' % n)['_id']
    docs.apply('running-log', {'op': 'replace_section', 'sid': 'first', 'reason': 'fixed'}, '第 0 段，改过',
               base_revision_id=base, author='character', mutation_id='p-3')
    read, real = [], crossing.head_records.revision
    monkeypatch.setattr(crossing.head_records, 'revision', lambda store, rid, fields=None, **kw: read.append(rid) or real(
        store, rid, fields, **kw))
    past = crossing.versions(world, PERSONA, 'running-log')
    assert {sid: [body for body, *_ in v] for sid, v in past.items()} == {'first': ['第 0 段']}
    assert len(read) == 1, 'the one revision holding a replaced text, not all four'
