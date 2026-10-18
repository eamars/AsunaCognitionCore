"""ADR-079 step 3: her tools as each conversation's channel declared them, fixed for a session (§9.7).

`speak` lists the parts and the quote the running adapter declared, so a function the platform there cannot carry is
not shown; a call that names one anyway is refused in her words. When a channel stops or starts carrying one, each of
its conversations is told once. Kazusa's QQ Bot conversations speak through `speak` as Xiaoman's do."""
import pytest

from asuna import capabilities, channel_kinds, role_tools, visibility
from asuna.config import ROOT
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import THINK
from test_group_admin import SCENE
from test_reply_actions import mention, world

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'qq-bot' / 'python', 'module': 'qq_bot'},
                    {'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
APP, GROUP = '1000000001', '0B1C2D3E4F5A6B7C8D9E0F1A2B3C4D5E'
BOT_SCENE = 'qqbot:%s:group:%s' % (APP, GROUP)
EVERYTHING = ['image', 'sticker', 'poke', *capabilities.POINTERS]


def speak_of(specs):
    return next(spec for spec in specs if spec['name'] == 'speak')


def bot_group(store):
    store.put('scenes', {'_id': BOT_SCENE, 'kind': 'group', 'scope_key': 'scene:' + BOT_SCENE, 'policy_epoch': 1,
                         'sequence': 0, 'channel_id': 'qqbot'})
    capabilities.declared(store, 'qqbot', ['image'])           # what the QQ Bot bridge declares today
    return store.db.scenes.find_one({'_id': BOT_SCENE})


def test_where_everything_is_declared_speak_is_the_shared_definition_byte_for_byte(store):
    world(store)
    assert role_tools.session_specs(store, SCENE) == role_tools.all_specs()


def test_a_qq_bot_conversation_shows_text_and_picture_and_no_quote(store):
    bot_group(store)
    speak = speak_of(role_tools.session_specs(store, BOT_SCENE))
    item = speak['parameters']['parts']['items']['properties']
    assert item['kind']['enum'] == ['text', 'picture'] and set(item) == {'kind', 'text', 'artifact_id'}
    assert 'quote' not in speak['parameters'] and 'recall' not in speak['description']
    assert speak['description'].startswith(role_tools.SPEAK_HEAD + 'text、picture，各写它的字段；有一条不对')


def test_kazusas_conversations_speak_only_through_speak(store):
    scene = bot_group(store)
    ep = {'scene_id': scene['_id'], 'persona': 'P1', 'manifest': {'session_class': visibility.PUBLIC}}
    names = role_tools.abilities(store, ep)
    assert 'speak' in names and not set(role_tools.REPLY_REPLACES) & set(names)


def test_a_pointer_not_declared_is_hidden_and_refused_in_her_words(store):
    world(store)
    capabilities.forget()
    capabilities.declared(store, 'qq', ['image', 'sticker', 'poke', 'quote_in', 'react_in'])
    speak = speak_of(role_tools.session_specs(store, SCENE))
    assert speak['parameters']['parts']['items']['properties']['kind']['enum'] == ['text', 'sticker', 'picture', 'poke']
    assert 'quote' not in speak['parameters'] and 'line' not in speak['parameters']['parts']['items']['properties']
    lane = FakeLane(store, [FakeTurn([THINK, ('speak', {'parts': [{'kind': 'react', 'line': '这条', 'face': '赞'}]}),
                                      ('speak', {'parts': [{'kind': 'text', 'text': '嗯'}], 'quote': '这条'})])])
    Coordinator(store, lane).ingest(mention('s3-1'), persona='P1')
    refused = [str(row[4]) for row in lane.tool_results if row[2] == 'speak']
    assert '第 1 条 react 这里发不了：这条腿做不了点表情' in refused[0]
    assert 'quote：这条腿做不了引用' in refused[1]


def test_a_function_lost_or_regained_is_told_once_in_each_conversation(store):
    world(store)
    capabilities.forget()
    capabilities.declared(store, 'qq', [name for name in EVERYTHING if name != 'quote'])
    _, context, _ = ContextBuilder(store).prepare(mention('s3-2'))
    assert context['speak_from_program']['leg'] == '这条腿做不了引用。'
    _, context, _ = ContextBuilder(store).prepare(mention('s3-3'))
    assert 'leg' not in context['speak_from_program'], 'once'
    capabilities.forget()
    capabilities.declared(store, 'qq', EVERYTHING)
    _, context, _ = ContextBuilder(store).prepare(mention('s3-4'))
    assert context['speak_from_program']['leg'] == '这条腿又能引用了。'


def test_the_first_declaration_of_a_channel_tells_nothing(store):
    world(store)                                               # its first declaration
    _, context, _ = ContextBuilder(store).prepare(mention('s3-5'))
    assert 'leg' not in context['speak_from_program']


def test_a_private_chat_that_refused_a_reaction_is_not_shown_react_until_restart(store, monkeypatch):
    world(store)
    monkeypatch.setattr(role_tools, 'REACT_OFF_IN_DMS', {'qq'})
    dm = {'_id': 'qq:90000:dm:20002', 'kind': 'dm', 'channel_id': 'qq'}
    assert 'react' not in role_tools.speak_kinds(store, dm)
    assert 'react' in role_tools.speak_kinds(store, {**dm, '_id': SCENE, 'kind': 'group'})


@pytest.mark.parametrize('kinds', [('text',), ('text', 'recall'), ('text', 'react')])
def test_the_line_field_says_only_what_the_listed_parts_use(kinds):
    item = role_tools.speak_spec(kinds, True)['parameters']['parts']['items']['properties']
    if 'line' not in item:
        assert kinds == ('text',)
        return
    said = item['line']['description']
    assert ('react：' in said) == ('react' in kinds) and ('recall：' in said) == ('recall' in kinds)


# Her thought under a line of hers, wherever someone else points at it (the owner's ask; Xiaoman's two rules: once a
# turn however many point at it, and never under anyone else's line).
def her_line_and_pointers(store, monkeypatch):
    from asuna import reasons
    from test_adr079_pointers import numbered_scene
    from test_people import row
    scene = numbered_scene(store)
    store.put('messages', {'_id': 'out-9', 'scene_id': scene['_id'], 'direction': 'outbound', 'author': 'demo',
                           'text': '这戏我从中午就没下过班', 'delivery_state': 'DELIVERED', 'scene_seq': 400,
                           'policy_epoch': 1, 'scope_key': 'scene:' + scene['_id']})
    monkeypatch.setattr(reasons, 'for_message', lambda store, message_id: '他夸我，我挺得意。' if message_id == 'out-9' else None)
    reacted = {**row(20002, '给 〔400〕 你：这戏我从中午就没下过班 点了「爱心」', card='阿杰'), 'scene_seq': 401}
    reacted['event']['raw']['asuna_notice'] = {'kind': 'reaction', 'words': '给{line}点了「爱心」', 'line': {'row': 'out-9'}}
    quoted = {**row(20003, '真会演', card='老王', reply='out-9', at='2026-10-04T01:07:00+00:00'), 'scene_seq': 402}
    quoted['event']['group_context']['reply_to'] = 'p-out-9'
    return scene, reacted, quoted


def test_a_reaction_to_her_line_carries_the_anchor_a_quote_of_it_has(store, monkeypatch):
    from asuna.people import People, anchors_shown
    scene, reacted, _ = her_line_and_pointers(store, monkeypatch)
    anchors_shown(scene['_id'])
    shown = People(store).transcript(scene, reacted)
    assert shown.endswith('  > （你说那句时心里想的：他夸我，我挺得意。）') and '给 〔400〕 你：' in shown


def test_the_anchor_comes_once_a_turn_and_the_gates_view_keeps_its_own(store, monkeypatch):
    from asuna.people import People, anchors_shown
    scene, reacted, quoted = her_line_and_pointers(store, monkeypatch)
    anchors_shown(scene['_id'])
    people = People(store)
    assert '心里想的' in people.transcript(scene, reacted)
    assert '心里想的' not in people.transcript(scene, quoted), 'the same line, the same turn: once'
    assert '心里想的' in people.transcript(scene, quoted, once=False), "the gate's view is not her conversation"
    anchors_shown(scene['_id'])                                # her turn's context was ready: the next turn's count
    assert '心里想的' in people.transcript(scene, quoted)


def test_no_anchor_under_anyone_elses_line(store, monkeypatch):
    from asuna.people import People, anchors_shown
    from test_people import row
    scene, _, _ = her_line_and_pointers(store, monkeypatch)
    store.put('messages', {**row(20004, '我考过了', card='小雨'), '_id': 'in-x', 'scene_seq': 403})
    other = {**row(20002, '给 〔403〕 小雨：我考过了 点了「赞」', card='阿杰', at='2026-10-04T01:08:00+00:00'),
             'scene_seq': 404}
    other['event']['raw']['asuna_notice'] = {'kind': 'reaction', 'words': '给{line}点了「赞」', 'line': {'row': 'in-x'}}
    anchors_shown(scene['_id'])
    assert '心里想的' not in People(store).transcript(scene, other)
