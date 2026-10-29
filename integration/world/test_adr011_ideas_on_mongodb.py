"""ADR-011 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): an idea from a public chat is
noted but cannot be read there."""

import pytest

from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn

pytestmark = pytest.mark.world                # `store` is the fixture world

THINK = ('think', {'thought': '有个地方可以做得更好。'})


def event(key, scene='dm-a', person='A', text='你可以把回复改得更短吗？', **extra):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, **extra}


def test_an_idea_from_a_public_chat_is_noted_but_cannot_be_read_there(store):
    lane = FakeLane(store, [FakeTurn([THINK, ('ideas', {'do': 'note', 'idea': '群里说话可以更短', 'why': '有人嫌我的回复太长'})], '好，我记下了。'),
                            FakeTurn([THINK], '嗯。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest(event('pub-1'))
    assert 'ideas' in lane.calls[0]['tools'] and lane.tool_results[1][5]
    row = store.raw.ideas.find_one({})
    assert row['state'] == 'open' and row['source'] == {'by': 'character', 'scene_id': 'dm-a', 'episode_id': ep['_id'],
                                                         'turn': 'external'}
    assert row['scope_key'].startswith('owner-private:')
    later = coordinator.ingest(event('pub-2', text='在吗'))
    assert 'ideas_from_program' not in later['context'], 'a public chat writes the notebook but never reads it'
    assert {'ideas.read', 'ideas.review'}.isdisjoint(later['turn_tools'])


