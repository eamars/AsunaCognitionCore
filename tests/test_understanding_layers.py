"""Her understanding of a person in two layers (owner 2026-10-08, with her wording): the person layer is read
wherever she meets them and always opens with the line that it is only part of them; the here layer stays in its
conversation."""
import pytest

from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.privacy import PrivacyService
from asuna.role_tools import Refused
from asuna.understanding import NO_HERE, NO_PERSON, PART

THINK = ('think', {'thought': '这条换个地方也成立。'})
DM = {'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '我说话一向直接。'}
GROUP = {'event_id': 'e2', 'scene_id': 'g1', 'person_id': 'A', 'text': '在吗'}


def write(store, *calls, event=DM):
    lane = FakeLane(store, [FakeTurn([THINK, *calls], '好。')])
    return Coordinator(store, lane).ingest(event), lane


def test_the_person_layer_is_read_elsewhere_with_where_it_was_written(store):
    _, before, manifest = ContextBuilder(store).prepare(GROUP)
    assert before['relationship']['person'] == {'first': PART + '；你在另外 1 个对话里还各有一份他在那儿的样子，这里看不到。',
                                                'text': NO_PERSON}
    assert manifest['person_revision'] is None and manifest['person_entity_key'] == 'relationship:A|person'
    done, _ = write(store, ('understand_person', {'layer': 'person', 'body': 'A 说话直接，先给结论。'}))
    assert done['state'] == 'COMMITTED' and done['person_understanding_update']['state'] == 'COMMITTED'
    _, there, _ = ContextBuilder(store).prepare({**GROUP, 'event_id': 'e3'})
    person = there['relationship']['person']
    assert person['text'] == 'A 说话直接，先给结论。' and person['written'].startswith('最后是在') and '刚才' in person['written']
    assert there['relationship']['here'] == NO_HERE, 'the direct chat\'s here layer stays there'
    assert '换个群还成立吗' in there['understanding_update_from_program']['target']


def test_both_layers_in_one_turn_each_once_and_the_layer_is_required(store):
    done, lane = write(store, ('understand_person', {'layer': 'here', 'body': '在私聊里他放松很多。'}),
                       ('understand_person', {'layer': 'person', 'body': '他重视守时。'}),
                       ('understand_person', {'layer': 'person', 'body': '再写一次。'}),
                       ('understand_person', {'body': '没选层。'}))
    results = [r for r in lane.tool_results if r[2] == 'understand_person']
    assert [r[-1] for r in results] == [True, True, False, False]
    assert '人那层' in str(results[2][-2]) and 'UNDERSTANDING_LAYER_REQUIRED' in str(results[3][-2])
    assert store.head('relationship:A', 'scene:dm-a')[1]['content']['body'] == '在私聊里他放松很多。'
    assert store.head('relationship:A', 'person')[1]['content']['body'] == '他重视守时。'


def test_erasing_the_conversation_it_came_from_takes_it_back(store):
    write(store, ('understand_person', {'layer': 'person', 'body': '他重视守时。'}))
    assert store.head('relationship:A', 'person')
    PrivacyService(store).delete_memory('M09', operator=True)
    assert store.head('relationship:A', 'person') is None
