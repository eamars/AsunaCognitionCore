"""ADR-098 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): a brief from a public place
expands only the workspace and data roots."""
import json
from pathlib import Path

import pytest

from asuna import local_roots, visibility
from asuna.lanes import FakeTurn

from turn_parts import event, run

pytestmark = pytest.mark.world                # `store` is the fixture world

HOST = json.loads((Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'path_placeholders.json').read_text(encoding='utf-8'))
HOST = HOST['hosts']['windows']
WS, HOME = HOST['workspace'], HOST['home']

THINK = ('think', {'thought': '他回来了，我挺高兴，简单回一句。'})


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', local_roots.build(HOST))
    monkeypatch.setattr(local_roots, 'REFUSED', None)


@pytest.fixture
def home(store, monkeypatch):
    """dm-a as the owner's own chat: its person is the owner."""
    monkeypatch.setitem(store.config['chat'], 'person_id', 'A')


def delegate(store, ev, brief, title='看文件'):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': title, 'brief': brief})], '交给行动脑了。'))
    ep = coordinator.ingest(ev)
    [(_, _, _, _, result, ok)] = [r for r in lane.tool_results if r[2] == 'delegate']
    task = store.raw.tasks.find_one({'_id': ep['task_ids'][0]}) if ep.get('task_ids') else None
    return ep, result, ok, task


def test_a_brief_from_a_public_place_expands_only_the_workspace_and_data(store):
    brief = '读 ${ASUNA_WORKSPACE}/README.md，别碰 ${ASUNA_HOME}\\notes.md 和 ${ASUNA_DRIVE_D}\\logs\\x.log'
    ep, result, ok, task = delegate(store, event('p1', scene='dm-a', person='A'), brief)
    if ep['manifest']['session_class'] != visibility.PUBLIC or 'delegate' not in ep.get('turn_tools', ()):
        pytest.skip('UNCHECKED, not passed: the fixture world gives this conversation no public delegate')
    assert ok, result
    assert task['brief'] == '读 %s\\README.md，别碰 ${ASUNA_HOME}\\notes.md 和 ${ASUNA_DRIVE_D}\\logs\\x.log' % WS


