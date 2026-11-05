"""ADR-117 L2: chat lines are chunked up to each conversation's mark, which only a settled line lets pass (B8), and a
section has its tier row from the write that made it, with no turn running (B3). On the in-memory adapter."""
from types import SimpleNamespace

import pytest

from asuna import clock, crossing, memory_tiers
from asuna.evidence import canonical, sha
from asuna.memory import MemoryService
from asuna.persona_data import PersonaDataAPI
from asuna.records import memories as memory_records
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records
from asuna.role_tools import RoleTools

GROUP = 'g-l2'
WORD = 'zephyrine'           # an ASCII word: it crosses from any group (key_words.cross_words)
ME = 'demo'


@pytest.fixture
def group(store):
    store.config['character_id'] = ME
    scene_records.save(store, {'_id': GROUP, 'kind': 'group', 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1,
                               'sequence': 0, 'members': []}, stream='test')
    return store


def line(store, seq, *, mine=False, state=None, text=None, **fields):
    row = {'_id': 'line-%d' % seq, 'scene_id': GROUP, 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1,
           'scene_seq': seq, 'text': text or 'line %d about %s' % (seq, WORD),
           'direction': 'outbound' if mine else 'inbound', 'author': ME if mine else 'person-a',
           'delivery_state': state or 'RECEIVED', **fields}
    return message_records.save(store, row, stream='test')


def chunked(store, seq):
    """The line's (first) chunk, or None."""
    return memory_records.get(store, 'chunk-' + sha(canonical(['line-%d' % seq, 2, 0])))


def test_a_line_whose_revision_changes_during_the_round_is_still_chunked_and_the_mark_advances(group, monkeypatch):
    store = group
    line(store, 1, mine=True, state='DELIVERED', receipt_at='2026-11-05T01:00:00+00:00')
    line(store, 2)
    real = memory_records.save

    def receipt_meanwhile(store_, unit, **kwargs):
        # The Host writes the line again (a receipt) while the round is cutting it: the 314 conflicts.
        row = message_records.get(store_, 'line-1')
        message_records.save(store_, {**row, 'platform_message_id': 'p-%d' % row['revision']},
                             expected=row['revision'], stream='host')
        return real(store_, unit, **kwargs)
    monkeypatch.setattr(memory_records, 'save', receipt_meanwhile)

    made = MemoryService(store).chunk(GROUP)
    assert {unit['_id'] for unit in made} == {chunked(store, 1)['_id'], chunked(store, 2)['_id']}
    assert memory_records.chunk_mark(store, GROUP) == 2


def test_a_reply_delivered_after_a_later_line_was_chunked_is_chunked_and_its_words_reach_the_crossing_index(group):
    store = group
    line(store, 1, mine=True, state='SENDING', claimed_at=clock.stamp(), text='my reply says ' + WORD)
    line(store, 2)
    MemoryService(store).chunk(GROUP)
    assert chunked(store, 2) and not chunked(store, 1), 'the later line is chunked; her reply is on its way'
    assert memory_records.chunk_mark(store, GROUP) == 0, 'her reply on its way holds the mark'
    crossing.build(store)                           # the night's settlement rebuilds the word index meanwhile
    assert crossing.lines_for(store, [WORD]) == [], 'nothing past the mark reaches the index'

    row = message_records.get(store, 'line-1')
    message_records.save(store, {**row, 'delivery_state': 'DELIVERED', 'receipt_at': '2026-11-05T01:04:00+00:00'},
                         expected=row['revision'], stream='host')
    MemoryService(store).chunk(GROUP)
    mine = chunked(store, 1)
    assert mine and mine['body_markdown'] == 'my reply says ' + WORD
    assert memory_records.chunk_mark(store, GROUP) == 2
    indexed = crossing.lines_for(store, [WORD])
    assert (mine['_id'], 'scene:' + GROUP, True) in indexed, 'her words are in the index'
    assert [unit for unit, *_ in indexed].count(chunked(store, 2)['_id']) == 1, 'the later line is indexed once'


def test_a_failed_reply_does_not_hold_the_mark(group):
    store = group
    line(store, 1, mine=True, state='FAILED')
    line(store, 2)
    MemoryService(store).chunk(GROUP)
    assert memory_records.chunk_mark(store, GROUP) == 2
    assert chunked(store, 2) and not chunked(store, 1)


# ── B3 ─────────────────────────────────────────────────────────────
@pytest.fixture
def home(store, tmp_path):
    store.config['chat'] = {'person_id': 'local-user', 'persona': ME, 'display_name': 'demo'}
    store.config.pop('persona_model', None)
    seed = tmp_path / 'voice.md'
    seed.write_text('## calm\nspeaks slowly about ' + WORD + '\n', encoding='utf-8')
    store.config['persona_contribution'] = {'seeds': [{'slug': 'voice', 'kind': 'voice', 'path': str(seed)}]}
    scene_records.save(store, {'_id': 'home', 'kind': 'dm', 'scope_key': 'scene:home', 'policy_epoch': 1,
                               'sequence': 0, 'members': ['local-user']}, stream='test')
    coordinator = SimpleNamespace(store=store, scheduler=None, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: store.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=store, tools=RoleTools(coordinator), serial=[0])


def her_call(home, name, args):
    home.serial[0] += 1
    ep_id = 'ep-%d' % home.serial[0]
    home.store.put('episodes', {
        '_id': ep_id, 'scene_id': 'home', 'scope_key': 'scene:home', 'policy_epoch': 1, 'persona': ME,
        'person_id': 'local-user', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': 'owner_private'},
        'turn_tools': ['think', 'write_document'], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    return home.tools.call(ep_id, ep_id + ':0', name, args)[0]


def test_a_section_written_by_her_by_adopt_seed_and_by_an_import_has_its_tier_row_without_a_turn(home):
    store, tiers = home.store, memory_tiers.Tiers(home.store, ME)
    written = her_call(home, 'write_document', {'doc': 'notes', 'do': 'append_section', 'kind': 'ledger',
                                                'heading': 'meeting', 'content': 'on friday', 'why': 'to remember'})
    assert tiers.item('notes', written['sid'])['place'] == memory_tiers.CARRIED, 'her write'

    assert her_call(home, 'write_document', {'doc': 'voice', 'do': 'adopt_seed', 'why': 'the new seed'})['state'] \
        == 'seeded'
    assert tiers.item('voice', 'calm')['place'] == memory_tiers.CARRIED, 'adopt_seed'

    api = PersonaDataAPI(store, ME, run_id='run-1', job_id='job-1', grants={'persona_data.write'},
                         sources={'origin-1': 'cohabiting'})
    done = api.dispatch('documents.upsert', {'slug': 'world', 'kind': 'ledger', 'origin': 'origin-1',
                                             'source_identity': 'src-1', 'title': 'world',
                                             'sections': [{'heading': 'rule', 'body': 'a rule', 'visibility': 'public',
                                                           'inject': 'on_demand'}]})
    assert done['action'] == 'created'
    assert tiers.item('world', 'rule')['place'] == memory_tiers.AT_HAND, 'an import, placed from its inject'
