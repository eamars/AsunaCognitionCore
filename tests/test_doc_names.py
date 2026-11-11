"""ADR-126: a word shown for a kind of document is never a document's name, and a name that is not a document makes
one only when she says which kind. On the fixture world (in memory); dm-a is the owner's DM."""
from types import SimpleNamespace

import pytest

from asuna import memory_tiers, visibility
from asuna.documents import DocumentStore
from asuna.role_tools import RoleTools

PERSONA = 'P1'
WORD = '是屏幕上标一类文档的词，不是文档名'       # DOC_NAME_IS_A_STORE_WORD, as she reads it


@pytest.fixture(autouse=True)
def locks(monkeypatch, tmp_path):
    import asuna.config
    import asuna.queue
    for module in (asuna.config, asuna.queue):
        monkeypatch.setattr(module, 'LOCKS', tmp_path / 'locks')


@pytest.fixture
def home(world):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'person_id': 'A', 'persona': PERSONA}
    pilot = SimpleNamespace(items=[], synced_at=0.0)
    coordinator = SimpleNamespace(store=world, scheduler=None, context=SimpleNamespace(pilot=pilot),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator), serial=[0])


def call(home, tool, args):
    home.serial[0] += 1
    ep_id = 'ep-126-%d' % home.serial[0]
    home.store.put('episodes', {
        '_id': ep_id, 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': 'A', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': visibility.OWNER_PRIVATE},
        'turn_tools': ['think', tool], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    return home.tools.call(ep_id, ep_id + ':0', tool, args)[0]


def append(home, doc, heading='一节', **args):
    return call(home, 'write_document', {'doc': doc, 'do': 'append_section', 'heading': heading,
                                         'content': '一段话', 'why': 'mine', **args})


def refused(home, *a, **k):
    with pytest.raises(Exception) as caught:
        append(home, *a, **k)
    return str(caught.value)


def names(home):
    return DocumentStore(home.store, PERSONA).slugs()


def test_a_shown_word_is_not_a_name_and_the_refusal_lists_what_she_means(home):
    empty = refused(home, '自我')
    assert WORD in empty and '这一类还没有文档' in empty, empty
    append(home, 'self')                                   # her self is named by the program: no kind needed
    said = refused(home, '自我')
    assert '这一类的文档：self。' in said, said
    assert '自我' not in names(home), 'no document named by the word'
    for word in ('流水', '口吻', '人设', '活账', '群笔记'):
        assert WORD in refused(home, word, kind='journal' if word == '流水' else None), word


def test_a_journal_word_lists_the_journals_and_a_kind_does_not_get_past_it(home):
    append(home, 'work_log', kind='journal')
    said = refused(home, '流水', kind='journal')               # how 流水 was made: with kind given
    assert '这一类的文档：work_log。' in said, said
    assert '流水' not in names(home)


def test_a_new_name_needs_its_kind_and_is_made_with_it(home):
    said = refused(home, '光伏账')
    assert said.startswith('「光伏账」不存在') and said.endswith('要新建一本就写 kind（ledger、journal 或 working）；要写已有的，照抄它的名字。'), said
    assert '光伏账' not in names(home), 'nothing made'
    append(home, '光伏账', kind='working')
    assert '光伏账' in names(home)
    append(home, '光伏账', heading='第二节')                   # an existing one takes a write without kind


def test_recall_reads_no_document_by_a_shown_word(home):
    append(home, 'self')
    with pytest.raises(Exception) as caught:
        call(home, 'recall', {'sections': [{'doc': '自我', 'section': 'x'}]})
    assert WORD in str(caught.value) and '这一类的文档：self。' in str(caught.value), str(caught.value)


def test_a_store_shows_the_names_she_writes():
    assert memory_tiers.store_label('self', ['self']) == '自我（self）'
    assert memory_tiers.store_label('journal', ['work_log', 'reading']) == '流水（reading、work_log）'
    assert memory_tiers.store_label('group_notes', ['group:qq:1', 'group:qq:2']) == '群笔记（group_notes）'
    assert memory_tiers.store_label('core', ['core']) == 'core'
