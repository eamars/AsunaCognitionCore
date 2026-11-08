"""ADR-117 L4 (§20): nothing on the stored side imitates forgetting. `correction`, the gist step and the night list's
offers are gone; the weekly reading stays. A shortened item she rewrites anew no longer shows the full text it was
shortened from. Her ledgers' rewritten facts keep their old wording for recall where the ledger is readable. At start,
what the night list left in the rows goes. On the fixture world (in memory); dm-a is the owner's DM, g1 a group."""
import importlib.util
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from datetime import datetime, timedelta, timezone

from asuna import clock, crossing, documents, host_lease, memory_pilot, memory_tiers, visibility
from asuna.config import database_lock
from asuna.documents import DocumentError, DocumentStore
from asuna.evidence import Evidence
from asuna.group_admin import notes_slug
from asuna.persona_data import PersonaDataAPI
from asuna.queue import RuntimeLease
from asuna.records import heads
from asuna.records import scenes as scene_records
from asuna.retrieval import Retrieval
from asuna.role_tools import RoleTools, read_sections
from asuna.store.words import Set

PERSONA = 'P1'
AXIS = [1.0, 0.0]


def at(score):
    """A unit vector whose score against AXIS is `score` on the pilot's (1 + cosine) / 2 scale."""
    cos = 2 * score - 1
    return [cos, math.sqrt(max(0.0, 1 - cos * cos))]


class Route:
    """The item index's embedding route as the like line uses it."""
    revision = 'route-test'

    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def embed(self, texts, purpose, timeout=None):
        self.calls.append((list(texts), purpose, timeout))
        if self.fail:
            raise self.fail
        return [AXIS for _ in texts]


@pytest.fixture(autouse=True)
def locks(monkeypatch, tmp_path):
    """The Host's lock files of these tests' databases live in the test's own folder."""
    import asuna.config
    import asuna.queue
    for module in (asuna.config, asuna.queue):
        monkeypatch.setattr(module, 'LOCKS', tmp_path / 'locks')


@pytest.fixture
def home(world):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'person_id': 'A', 'persona': PERSONA}
    pilot = SimpleNamespace(retrieval=Route(), items=[], synced_at=0.0)
    coordinator = SimpleNamespace(store=world, scheduler=None, context=SimpleNamespace(pilot=pilot),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, tools=RoleTools(coordinator), serial=[0], pilot=pilot)


def call(home, args):
    """One write_document of hers, in a home turn of its own."""
    home.serial[0] += 1
    ep_id = 'ep-l4-%d' % home.serial[0]
    home.store.put('episodes', {
        '_id': ep_id, 'scene_id': 'dm-a', 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': 'A', 'episode_kind': 'external', 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': {}, 'manifest': {'session_class': visibility.OWNER_PRIVATE},
        'turn_tools': ['think', 'write_document'], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    return home.tools.call(ep_id, ep_id + ':0', 'write_document', args)[0]


def write(home, heading, doc='self', body=None, visibility_='public', **args):
    return call(home, {'doc': doc, 'do': 'append_section', 'heading': heading,
                       'content': body or ('关于 %s 的一段话' % heading), 'why': 'mine', 'visibility': visibility_,
                       **args})


def indexed(home, doc, sid, score, scope_key='global-safe', heading=None):
    """An item the index holds, at `score` from what the next write embeds to."""
    home.pilot.items.append({'key': 'shadow:' + doc + sid, 'store': 'self', 'doc': doc, 'sid': sid,
                             'scope_key': scope_key, 'heading': heading or sid, 'unit': at(score)})


def sections(home, doc='self'):
    return [s['sid'] for s in (DocumentStore(home.store, PERSONA).read(doc)[1] or {}).get('sections') or []]




def test_a_ledger_fact_she_rewrote_keeps_its_old_wording_for_recall_where_the_ledger_is_readable(world):
    docs = DocumentStore(world, PERSONA)
    base = docs.apply('facts', {'op': 'append_section', 'heading': 'open', 'reason': 'r', 'kind': 'ledger',
                                'visibility': 'public'}, 'the zephyrine opens at nine', base_revision_id=None,
                      author='character', mutation_id='f-1')['_id']
    base = docs.apply('facts', {'op': 'append_section', 'heading': 'kept', 'reason': 'r', 'visibility': 'owner_private'},
                      'the zephyrine key stays at home', base_revision_id=base, author='character',
                      mutation_id='f-2')['_id']
    base = docs.apply('facts', {'op': 'replace_section', 'sid': 'open', 'reason': 'moved'}, 'it opens at ten',
                      base_revision_id=base, author='character', mutation_id='f-3')['_id']
    docs.apply('facts', {'op': 'replace_section', 'sid': 'kept', 'reason': 'moved'}, 'the key went elsewhere',
               base_revision_id=base, author='character', mutation_id='f-4')
    in_group = crossing.before(world, PERSONA, scene_records.get(world, 'g1'), visibility.PUBLIC, 'zephyrine', None)
    at_home = crossing.before(world, PERSONA, scene_records.get(world, 'dm-a'), visibility.OWNER_PRIVATE, 'zephyrine',
                              None)
    assert [entry['now'] for entry in in_group] == ['doc:facts#open'] and 'opens at nine' in in_group[0]['line']
    assert {entry['now'] for entry in at_home} == {'doc:facts#open', 'doc:facts#kept'}




def test_a_shortened_section_she_rewrites_anew_no_longer_shows_the_text_it_was_shortened_from(home):
    """The reviewer's finding: a changed rewrite of a gisted item kept `detail_of`, so read_sections showed the old
    verbatim as what the new text stands for. The old text stays in the revision ledger."""
    first = write(home, 'short', body='短的那句')
    row_id = memory_tiers.item_id(PERSONA, 'self', first['sid'])
    revision = DocumentStore(home.store, PERSONA).read('self')[0]
    home.store.collection('memory_tiers').update({'_id': row_id}, Set({'detail_of': {'revision_id': revision},
                                                                       'gist': {'done': '2026-11-01'}}))
    ep = {'persona': PERSONA, 'scene_id': 'dm-a'}
    [read], _ = read_sections(home.store, ep, [{'doc': 'self', 'sid': first['sid']}], visibility.OWNER_PRIVATE)
    assert read['detail'] == {'what': memory_tiers.DETAIL_WHAT, 'text': '短的那句'}
    call(home, {'doc': 'self', 'do': 'replace_section', 'section': first['sid'], 'content': '她重新写的完整一段',
                'why': 'mine'})
    row = home.store.collection('memory_tiers').get(row_id)
    assert 'detail_of' not in row and 'gist' not in row
    [read], _ = read_sections(home.store, ep, [{'doc': 'self', 'sid': first['sid']}], visibility.OWNER_PRIVATE)
    assert read['body'] == '她重新写的完整一段' and 'detail' not in read


def test_at_start_the_night_lists_rows_go_and_the_weekly_readings_stay(world):
    rows = world.collection('memory_tiers')
    for what in ('gist', 'merge', 'repeated', 'week'):
        rows.insert({'_id': 'offer:' + what, 'row': 'offer', 'persona': PERSONA, 'what': what, 'at': '2026-11-01'})
    rows.insert({'_id': 'tier:put-away', 'row': 'item', 'persona': PERSONA, 'doc': 'self', 'sid': 's',
                 'place': memory_tiers.PUT_AWAY, 'superseded_at': '2026-11-01'})
    rows.insert({'_id': 'move:1', 'row': 'move', 'persona': PERSONA, 'item': 'tier:put-away', 'reason': 'superseded'})
    # A gisted item she rewrote after its gist (the gist step never set rewritten_at), and one she did not.
    rows.insert({'_id': 'tier:rewritten', 'row': 'item', 'persona': PERSONA, 'doc': 'self', 'sid': 'r',
                 'detail_of': {'revision_id': 'x'}, 'gist': {'done': '2026-11-01'}, 'rewritten_at': '2026-11-03'})
    rows.insert({'_id': 'tier:gisted', 'row': 'item', 'persona': PERSONA, 'doc': 'self', 'sid': 'g',
                 'detail_of': {'revision_id': 'y'}, 'gist': {'done': '2026-11-01'}, 'rewritten_at': '2026-10-20'})
    assert memory_tiers.retire_night_list(world) == {'offers_deleted': 3, 'superseded_unset': 1, 'detail_unset': 1}
    assert [row['_id'] for row in rows.find({'row': 'offer'})] == ['offer:week']
    assert 'superseded_at' not in rows.get('tier:put-away') and rows.get('move:1')
    assert 'detail_of' not in rows.get('tier:rewritten') and rows.get('tier:gisted')['detail_of'] == {'revision_id': 'y'}
    assert memory_tiers.retire_night_list(world) == {'offers_deleted': 0, 'superseded_unset': 0, 'detail_unset': 0}
