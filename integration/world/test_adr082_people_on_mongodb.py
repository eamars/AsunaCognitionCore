"""ADR-082 on MongoDB, kept by ADR-104 decision 9 (a break would leak private data): the people list is given at home
and refused outside, and a watch block names someone here, never anyone from home."""
import json

import pytest

from asuna.records import heads as head_records
from asuna import role_tools, switches
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.people import People
from asuna.understanding import LIST_HOME_ONLY, NO_HERE, NO_PERSON

from turn_parts import owner

pytestmark = pytest.mark.world                # `store` is the fixture world

THINK = ('think', {'thought': '先看看是谁。'})
DM = {'event_id': 'dm-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '我说话一向直接。'}


def event(key, person='A', wake='mentioned_account', text='@演示 在吗'):
    return {'event_id': key, 'scene_id': 'g1', 'person_id': person, 'text': text,
            'group_context': {'wake_reason': wake, 'topic_id': 't', 'mentioned_account_ids': []}}


def room(store):
    """g1 with four members: A and C share a name (林), E has none the program knows."""
    store.raw.scenes.update_one({'_id': 'g1'}, {'$set': {'members': ['A', 'B', 'C', 'E']}})


def label(store, person, scene='g1'):
    return People(store, 'P1').speaker(store.raw.scenes.find_one({'_id': scene}), person)


def turn(store, ev, *calls, gate=None, speech='在。'):
    lane = FakeLane(store, [FakeTurn([THINK, *calls], speech)])
    coordinator = Coordinator(store, lane)
    if gate:
        coordinator.attend = FakeLane(store, [LaneResult('接话：' + gate)])
    ep = coordinator.ingest(ev)
    assert ep['state'] == 'COMMITTED', ep.get('failure')
    return ep, lane


def results(lane, tool):
    """[(result or refusal text, ok)] of one tool's calls, in order."""
    return [(row[4], row[5]) for row in lane.tool_results if row[2] == tool]


def write_dm(store, layer='person', body='A 说话直接，先给结论。', short='直接，先给结论', key='dm-1'):
    ep, lane = turn(store, {**DM, 'event_id': key},
                    ('understand_person', {'layer': layer, 'content': body, 'short': short}), speech='好。')
    assert results(lane, 'understand_person') == [({'state': 'COMMITTED'}, True)]
    return ep


def test_people_list_at_home_and_refused_outside(store, monkeypatch):
    write_dm(store)
    _, lane = turn(store, event('t-list'), ('recall', {'person': '名单'}))
    assert results(lane, 'recall') == [(LIST_HOME_ONLY, False)]
    owner(store)
    _, lane = turn(store, {**DM, 'event_id': 'home-list'}, ('recall', {'person': '名单'}),
                   ('recall', {'person': '明'}))
    (listed, ok), (by_name, named_ok) = results(lane, 'recall')
    assert ok and named_ok
    rows = {row['name']: row['layers'] for row in listed['people']}
    assert set(rows) == {'林', '明'} and 'person' not in json.dumps(list(listed['people'][0]), ensure_ascii=False)
    person_layer = next(layer for layer in rows['林'] if layer['layer'] == '人那层')
    assert person_layer['chars'] == len('A 说话直接，先给结论。') and person_layer['written_in'] and person_layer['written_at']
    assert person_layer['short'] == (head_records.current(store, 'relationship:A', 'person')[1]['content'].get('short') or '没有')
    [b_here] = rows['明']
    assert b_here['layer'].startswith('这里那层') and b_here['chars'] > 0 and b_here['short'] == '没有'
    # At home a read names anyone on the list; his here layer is the one of the conversation it is read in.
    assert by_name['who'] and by_name['person']['text'] == NO_PERSON and by_name['here'] == {'text': NO_HERE}
    assert '另外 1 个对话' in by_name['person']['first']
    # B15: it grows with everyone she writes; past its bound, the newest, then how many earlier ones are left out.
    from asuna import understanding
    whole = understanding.listing(store, 'P1')
    cut = understanding.listing(store, 'P1', limit=len(json.dumps(
        {k: v for k, v in whole[0].items() if k != 'person'}, ensure_ascii=False, default=str)) + 2)
    assert cut == [whole[0], {'earlier': understanding.EARLIER_PEOPLE % (1, 2), 'left_out': 1}]
    # Through recall: she sees the closing line without its count; the audit counts the people listed and left out.
    monkeypatch.setattr(understanding, 'LISTED_CHARS', len(json.dumps(
        {k: v for k, v in whole[0].items() if k != 'person'}, ensure_ascii=False, default=str)) + 2)
    ep, lane = turn(store, {**DM, 'event_id': 'home-list-cut'}, ('recall', {'person': '名单'}))
    [(shown, ok)] = results(lane, 'recall')
    assert ok and shown['people'][-1] == {'earlier': understanding.EARLIER_PEOPLE % (1, 2)}
    audit = store.raw.audit_events.find_one({'type': 'recall.people', 'stream_id': ep['_id']})
    assert audit['payload'] == {'listed': 1, 'left_out': 1}


def test_watch_block_names_someone_here_never_anyone_from_home(store):
    """block takes person as on does (a label, #number or name here); without it, the one speaking. The owner is
    never blocked, in any conversation: a block silences that person's lines everywhere, his own chat included."""
    owner(store, person='O')
    room(store)
    lane = FakeLane(store, [FakeTurn([THINK], '在。') for _ in range(3)])
    coordinator = Coordinator(store, lane)
    ep = store.raw.episodes.find_one({'_id': coordinator.ingest(event('t-name'))['_id']})
    named = coordinator.tools.tool_watch(ep, 'c1', {'op': 'block', 'person': label(store, 'B'), 'hours': 2})[0]
    assert label(store, 'B') in named['done'] and switches.blocked(store, 'B') and switches.blocked(store, 'A') is None
    speaking = coordinator.tools.tool_watch(ep, 'c2', {'op': 'block', 'hours': 2})[0]
    assert label(store, 'A') in speaking['done'] and switches.blocked(store, 'A')
    with pytest.raises(role_tools.Refused) as unknown:
        coordinator.tools.tool_watch(ep, 'c3', {'op': 'block', 'person': '[没这人 #99]'})
    assert '这个对话里没有「[没这人 #99]」' in str(unknown.value) and '能用的：' in str(unknown.value)
    assert str(unknown.value).endswith('能用的：%s、%s。' % (label(store, 'A'), label(store, 'B'))), 'the people seen here'
    visit = {**ep, 'episode_kind': 'visit', 'turn_kind': 'visit'}
    assert label(store, 'C') in coordinator.tools.tool_watch(visit, 'c4', {'op': 'block', 'person': label(store, 'C')})[0]['done'], \
        'named, it needs no one speaking'
    owner(store, person='A')
    with pytest.raises(role_tools.Refused, match='家里的人屏蔽不了'):
        coordinator.tools.tool_watch(ep, 'c5', {'op': 'block', 'person': label(store, 'A').split()[-1]})   # [林 #1]
    with pytest.raises(role_tools.Refused, match='家里的人屏蔽不了'):
        coordinator.tools.tool_watch(ep, 'c6', {'op': 'block'})


