"""Recall's past versions of her notes (crossing.before): a past text is shown only where its own visibility, every one
it had, is readable, not only where its section is now; a running record's past is read by hashes, one revision per
text it shows. On the fixture world (in memory); dm-a is the owner's DM, g1 a group."""
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


def test_a_past_text_is_shown_only_where_its_own_visibility_is_readable_too(world, monkeypatch):
    """The reviewer's case: a private section rewritten to public in the same write; its old private text never reaches
    a group's recall from a running record, and still comes back at home (ledgers are not read by this recall)."""
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
    assert {entry['now'] for entry in at_home} == {'doc:work_log#entry', 'doc:work_log#open'}   # ledgers: not read


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
    mark = (world.name, PERSONA, 'running-log')
    past = crossing.versions(world, PERSONA, 'running-log')
    assert {sid: [body for body, *_ in v] for sid, v in past.items()} == {'first': ['第 0 段']}
    assert len(read) == 1, 'the one revision holding a replaced text, not all four'
    document = crossing._pasts[mark][1]
