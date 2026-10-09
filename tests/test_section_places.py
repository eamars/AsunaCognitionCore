"""ADR-032: a persona section pinned to places renders only in turns there; every recall is recorded."""
import pytest

from asuna import visibility
from asuna.coordinator import Coordinator
from asuna.documents import DocumentError, DocumentStore
from asuna.lanes import FakeLane, FakeTurn
from asuna.render import estimate_tokens, render_status, render_system
from test_adr009_p2 import owner, THINK
from test_engineering_m1 import event


def pin(store, heading, body, tags, visibility_='public'):
    docs = DocumentStore(store, 'P1')
    return docs.apply('persona', {'op': 'append_section', 'heading': heading, 'visibility': visibility_, 'inject': 'always',
                                  'tags': tags, 'reason': 'test'}, body, base_revision_id=docs.read('persona')[0],
                      author='character', mutation_id='pin-' + heading)


def test_the_place_of_a_turn_is_decided_by_the_program(store, monkeypatch):
    owner(store)
    place = lambda scene, person: visibility.place(store.config, store.db, store.db.scenes.find_one({'_id': scene}), person)
    assert place('dm-a', 'A') == 'home'
    assert place('g1', 'A') == 'group'
    assert place('dm-b', 'B') == 'dm'
    monkeypatch.setattr(visibility.channel_kinds, 'home', lambda scene_id: scene_id == 'dm-b')
    assert place('dm-b', 'B') == 'peer', 'a trusted home channel line'


def test_a_section_pinned_to_groups_renders_only_in_group_turns_and_still_counts_against_the_budget(store):
    before = render_status(store, 'P1')['estimate_tokens']
    pin(store, '群里才用', 'ONLY_IN_GROUPS ' * 40, ['place:group'])
    pin(store, '到处都用', 'EVERYWHERE_LINE', [])
    group, _ = render_system(store, 'P1', visibility.PUBLIC, 'group')
    home, _ = render_system(store, 'P1', visibility.OWNER_PRIVATE, 'home')
    dm, _ = render_system(store, 'P1', visibility.PUBLIC, 'dm')
    assert 'ONLY_IN_GROUPS' in group and 'ONLY_IN_GROUPS' not in home and 'ONLY_IN_GROUPS' not in dm
    assert all('EVERYWHERE_LINE' in text for text in (group, home, dm))
    after = render_status(store, 'P1')['estimate_tokens']
    assert after == max(estimate_tokens(group), estimate_tokens(home), estimate_tokens(dm),
                        estimate_tokens(render_system(store, 'P1', visibility.OWNER_PRIVATE, 'peer')[0]))
    assert after > before, 'the largest render is the one bounded'


def test_a_place_that_does_not_exist_is_refused_so_a_typo_cannot_hide_a_rule(store):
    with pytest.raises(DocumentError, match='不是地方'):
        pin(store, '写错了', 'BODY', ['place:groups'])
    pin(store, '别的标签照旧', 'BODY', ['values', 'place:home'])


def test_a_turn_renders_for_its_place(store):
    owner(store)
    pin(store, '群里才用', 'ONLY_IN_GROUPS', ['place:group'])
    lane = FakeLane(store, [FakeTurn([THINK], '嗯。'), FakeTurn([THINK], '嗯。')])
    home = Coordinator(store, lane).ingest(event('place-home'))
    group = Coordinator(store, lane).ingest(event('place-group', scene='g1'))
    assert home['system_ref']['place'] == 'home' and group['system_ref']['place'] == 'group'
    system = [call['messages'][0]['content'] for call in lane.calls]
    assert 'ONLY_IN_GROUPS' not in system[0] and 'ONLY_IN_GROUPS' in system[1], 'the text reaches the request sent to the model'


def test_every_recall_is_recorded_with_what_came_back(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    docs.seed('notes', 'working', '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    read = ('recall', {'query': '笔记', 'sections': [{'doc': 'notes', 'sid': '私密'}, {'doc': 'notes', 'sid': '没有'}]})
    Coordinator(store, FakeLane(store, [FakeTurn([THINK, read], '看到了。')])).ingest(event('recall-kept'))
    row = store.db.audit_events.find_one({'type': 'recall.read'})
    assert row['payload']['query'] == '笔记' and row['payload']['place'] == 'home'
    assert row['payload']['sections_read'] == [{'doc': 'notes', 'sid': '私密'}]
    assert row['payload']['sections_missing'] == ['notes#没有：没有这一节'] and row['occurred_at']


def test_a_write_receipt_shows_the_tags_and_places_the_section_now_has(store):
    owner(store)
    docs = DocumentStore(store, 'P1')
    sid = docs.read('persona')[1]['sections'][-1]['sid']
    tag = ('write_document', {'doc': 'persona', 'op': 'set_tags', 'sid': sid, 'tags': ['place:group'], 'reason': '只在群里'})
    lane = FakeLane(store, [FakeTurn([THINK, tag], '改好了。')])
    Coordinator(store, lane).ingest(event('tag-receipt'))
    receipt = lane.tool_results[1][4]
    assert receipt['now']['tags'] == ['place:group'] and receipt['now']['places'] == ['group']


def test_her_delivered_line_says_which_part_the_platform_did_not_store(store):
    from asuna.config import character_id
    from asuna.context import landing_lost
    assert landing_lost({'result': 'verified', 'sent_segments': ['text', 'face'], 'stored_segments': ['text', 'face']}) is None
    store.db.messages.insert_one({'_id': 'out-face', 'schema_version': 1, 'scene_id': 'g1', 'policy_epoch': 1,
        'scene_seq': 900, 'direction': 'outbound', 'author': character_id(store.config), 'delivery_state': 'DELIVERED',
        'text': '好饿[表情:干饭]', 'platform_receipt': {'response': {'verification': {
            'result': 'segment_mismatch', 'sent_segments': ['text', 'face'], 'stored_segments': ['text']}}}})
    lane = FakeLane(store, [FakeTurn([THINK], '嗯。')])
    ep = Coordinator(store, lane).ingest(event('face-lost', scene='g1'))
    [row] = [r for r in ep['context']['delivered_history'] if r.get('text') == '好饿[表情:干饭]']
    assert row['not_landed'] == '平台收下了这句，但小黄脸没落成：对方看到的没有它' and 'platform_receipt' not in row
