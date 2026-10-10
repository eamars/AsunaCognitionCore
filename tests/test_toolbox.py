"""A conversation lists the same tools in every turn (ADR-038): its place and channel decide them, never the turn, so
the start of each request stays cached. The turn's own rules decide which of them it may use; a listed tool the turn
may not use is refused with when it can be used."""
import pytest

from asuna import channel_kinds, role_tools, visibility
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import owner
from test_engineering_m1 import THINK

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
LOCAL, LINE = 'dm-a', 'agent:home:dm:claude-code'
GROUP, OWNER_QQ, OTHER_QQ = 'qq:900000001:group:900000002', 'qq:900000001:dm:900000003', 'qq:900000001:dm:900000004'
KINDS = ('external', 'task_feedback', 'presence', 'scheduled', 'settlement', 'self_development', 'note', 'consult')
CONTEXTS = ({}, {'task_state_from_program': [{'_id': 'task-x', 'report': '报告 3 页'}],
                 'ideas_from_program': {'items': [{'_id': 'idea-1'}]},
                 'places_from_program': {'items': [{'place': 'g'}]},
                 'errand_places_from_program': [{'place': 'g'}],
                 'understanding_update_from_program': {'available': True},
                 'note_places_from_program': {'items': [{'place': 'g'}]}})


def conversations(store):
    owner(store)
    for scene, kind, channel in ((LOCAL, 'dm', None), (LINE, 'dm', 'agent'), (GROUP, 'group', 'qq'),
                                 (OWNER_QQ, 'dm', 'qq'), (OTHER_QQ, 'dm', 'qq')):
        if store.db.scenes.find_one({'_id': scene}):
            continue                                                # the fixture's own scenes (the local chat)
        store.put('scenes', {'_id': scene, 'kind': kind, 'scope_key': 'scene:' + scene, 'policy_epoch': 1,
                             'members': [], 'sequence': 0, **({'channel_id': channel} if channel else {})}, stream='t')
    home, public = visibility.OWNER_PRIVATE, visibility.PUBLIC
    return {LOCAL: home, LINE: home, GROUP: public, OWNER_QQ: home, OTHER_QQ: public}


def turn(scene, cls, kind='external', context=None):
    return {'_id': 'ep-' + kind, 'scene_id': scene, 'person_id': 'A', 'episode_kind': kind,
            'manifest': {'session_class': cls}, 'context': context or {}}


def test_a_conversation_lists_the_same_tools_in_every_turn_and_each_turn_uses_some_of_them(store):
    for scene, cls in conversations(store).items():
        listed = role_tools.toolbox(store, turn(scene, cls))
        for kind in KINDS:
            for context in CONTEXTS:
                ep = turn(scene, cls, kind, context)
                assert role_tools.toolbox(store, ep) == listed, (scene, kind)
                assert set(role_tools.exposed(store, ep)) <= set(listed), (scene, kind)
        assert listed == sorted(listed, key=role_tools.TOOL_NAMES.index)       # one order, the registration's


def test_each_kit_is_where_its_place_needs_it(store):
    listed = {scene: set(role_tools.toolbox(store, turn(scene, cls))) for scene, cls in conversations(store).items()}
    local, line, group, owner_qq, other_qq = (listed[s] for s in (LOCAL, LINE, GROUP, OWNER_QQ, OTHER_QQ))
    # The local chat: her heartbeats, nights and vault; her shelf to tidy; the owner may send her on errands.
    assert {'visit', 'promote_memory', 'credential', 'errand', 'sticker', 'restart', 'read_report'} <= local
    # A trusted line is text only and not the owner: about herself yes, his errands, vault and outings no.
    assert {'restart', 'update_self', 'read_ideas', 'write_document', 'pass_note'} <= line
    assert not {'credential', 'errand', 'visit', 'sticker', 'read_image', 'attach_image', 'watch'} & line
    # The owner's QQ chat: his errands and watching people there; no vault (a password does not travel through QQ).
    assert {'errand', 'watch', 'sticker', 'restart'} <= owner_qq and not {'credential', 'visit'} & owner_qq
    # Groups and other people's chats: nothing of home.
    assert {'await_answer', 'quote', 'find_member', 'leave_note', 'watch', 'write_document'} <= group
    assert {'leave_note', 'watch'} <= other_qq and not {'write_document', 'await_answer'} & other_qq
    for public in (group, other_qq):
        assert not set(role_tools.AT_HOME) - {'write_document', 'group_focus'} & public
        assert not {'errand', 'credential'} & public
    assert 'pin_memory' not in role_tools.TOOLS


def test_a_listed_tool_outside_its_turn_is_refused_with_when_it_works(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('visit', {'place': 'g', 'intent': 'start_topic'})], '嗯。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'm1', 'scene_id': LOCAL, 'person_id': 'A', 'text': '在吗'})
    assert 'visit' in lane.calls[0]['tools'] and 'visit' not in ep['turn_tools']
    [(said, ok)] = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'visit']
    assert not ok and said == role_tools.NOT_NOW['visit'] and '心跳或计划到点' in said
    # The action brain's question: the conversation's list as always, only the answer usable.
    assert role_tools.not_now(store, turn(LOCAL, visibility.OWNER_PRIVATE, 'consult'), 'plan') == role_tools.CONSULT_ONLY
    with pytest.raises(role_tools.Refused, match='只在行动脑问你话'):
        Coordinator(store, lane).tools.call(ep['_id'], 'y', 'answer_action', {'answer': 'a'})
