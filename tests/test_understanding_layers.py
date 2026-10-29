"""Her understanding of a person in two layers (owner 2026-10-08, with her wording): the person layer is read
wherever she meets them and always opens with the line that it is only part of them; the here layer stays in its
conversation."""
import pytest

from asuna.records import heads as head_records
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.privacy import PrivacyService
from asuna.role_tools import Refused
from asuna.understanding import NO_HERE, NO_PERSON, PART

THINK = ('think', {'thought': '这条换个地方也成立。'})
DM = {'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '我说话一向直接。'}
GROUP = {'event_id': 'e2', 'scene_id': 'g1', 'person_id': 'A', 'text': '在吗'}
CALLED = {**GROUP, 'group_context': {'wake_reason': 'mentioned_account', 'topic_id': 't', 'mentioned_account_ids': []}}


def write(store, *calls, event=DM):
    lane = FakeLane(store, [FakeTurn([THINK, *calls], '好。')])
    return Coordinator(store, lane).ingest(event), lane


def test_the_person_layer_is_read_elsewhere_with_where_it_was_written(store):
    # In a group (ADR-082) the layers are read with recall's person; a one-to-one chat shows them every turn (D5).
    _, before, manifest = ContextBuilder(store).prepare(GROUP)
    assert 'relationship' not in before and 'understanding_update_from_program' not in before
    assert manifest['person_revision'] is None and manifest['person_entity_key'] == 'relationship:A|person'
    lane = FakeLane(store, [FakeTurn([THINK, ('recall', {'person': 'A'})], '在。')])
    Coordinator(store, lane).ingest(CALLED)
    [(*_, first, ok)] = [r for r in lane.tool_results if r[2] == 'recall']
    assert ok and first['person'] == {'first': PART + '；你在另外 1 个对话里还各有一份他在那儿的样子，这里看不到。',
                                      'text': NO_PERSON}
    done, _ = write(store, ('understand_person', {'layer': 'person', 'content': 'A 说话直接，先给结论。',
                                                  'short': '直接，先给结论'}))
    assert done['state'] == 'COMMITTED' and done['person_understanding_update']['state'] == 'COMMITTED'
    lane = FakeLane(store, [FakeTurn([THINK, ('recall', {'person': 'A'})], '在。')])
    there_ep = Coordinator(store, lane).ingest({**CALLED, 'event_id': 'e3'})
    [(*_, there, ok)] = [r for r in lane.tool_results if r[2] == 'recall']
    person = there['person']
    assert ok and person['text'] == 'A 说话直接，先给结论。' and person['short'] == '直接，先给结论'
    assert person['written'].startswith('最后是在') and person['written_at']
    assert there['here'] == {'text': NO_HERE}, "the direct chat's here layer stays there"
    assert there_ep['context']['people_from_program']['items'][0]['short'] == '直接，先给结论'
    # The other way: written in the group about B, read in B's direct chat with where it was written.
    lane = FakeLane(store, [FakeTurn([THINK, ('understand_person', {'layer': 'person', 'content': 'B 做事要先看方案。',
                                                                    'short': '先给他方案'})], '好。')])
    Coordinator(store, lane).ingest({**CALLED, 'event_id': 'e4', 'person_id': 'B'})
    assert lane.tool_results[-1][-1], lane.tool_results
    _, dm, _ = ContextBuilder(store).prepare({'event_id': 'e5', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '在吗'})
    person = dm['relationship']['person']
    assert person['text'] == 'B 做事要先看方案。' and person['written'].startswith('最后是在') and person['written_at']
    assert dm['relationship']['here'].startswith('B 希望'), "the group's here layer is not his direct chat's"
    assert '换个群还成立吗' in dm['understanding_update_from_program']['target']


def test_both_layers_in_one_turn_each_once_and_the_layer_is_required(store):
    done, lane = write(store, ('understand_person', {'layer': 'here', 'content': '在私聊里他放松很多。', 'short': '私聊放松'}),
                       ('understand_person', {'layer': 'person', 'content': '他重视守时。', 'short': '守时'}),
                       ('understand_person', {'layer': 'person', 'content': '再写一次。', 'short': '再一次'}),
                       ('understand_person', {'content': '没选层。', 'short': '没选层'}))
    results = [r for r in lane.tool_results if r[2] == 'understand_person']
    assert [r[-1] for r in results] == [True, True, False, False]
    assert '人那层' in str(results[2][-2]) and 'UNDERSTANDING_LAYER_REQUIRED' in str(results[3][-2])
    assert head_records.current(store, 'relationship:A', 'scene:dm-a')[1]['content']['body'] == '在私聊里他放松很多。'
    assert head_records.current(store, 'relationship:A', 'person')[1]['content']['body'] == '他重视守时。'


def test_erasing_the_conversation_it_came_from_takes_it_back(store):
    write(store, ('understand_person', {'layer': 'person', 'content': '他重视守时。', 'short': '守时'}))
    assert head_records.current(store, 'relationship:A', 'person')[1]['content'] == {'body': '他重视守时。', 'short': '守时'}
    PrivacyService(store).delete_memory('M09', operator=True)
    assert head_records.current(store, 'relationship:A', 'person') is None
