"""ADR-099: her thoughts can come from the model's own thinking. In `thinking` mode no request asks the character
brain for its thoughts and no check waits for one; `tool` mode, the default, is today's, and its tests stay as they
are. Offline: the refusal probe's scripted provider stands in for the model."""
import argparse
import json
import re
import sys

import pytest

from asuna import block_guide, native_settings, role_tools
from asuna.config import ROOT
from asuna.coordinator import THINK_FIRST

sys.path.insert(0, str(ROOT / 'tools'))
import refusal_probe as rp          # noqa: E402

CHAT = str(rp.FIXTURES / 'sequences' / 'chat.json')
DONE = rp.reply('end_turn', [])
# What asking for her thoughts looks like: the tool's name, or a step that has her write 心里话 first.
ASKS = re.compile(r'(?<![A-Za-z])think(?![A-Za-z])|第一步[^。\n]{0,8}心里话|先[^。\n]{0,4}写[^。\n]{0,4}心里话')


def args(**extra):
    base = dict(sequences=[CHAT], dry_run=False, provider='scripted', keep_text='', repeat=1, progress=False,
                model='', key_env='', base_url='', max_tokens=4096, thoughts='thinking')
    return argparse.Namespace(**{**base, **extra})


def speak(i, text='在呢'):
    return rp.reply('tool_use', [{'type': 'tool_use', 'id': 's%d' % i, 'name': 'speak',
                                  'input': {'parts': [{'kind': 'text', 'text': text}]}}])


class Watching(rp.Scripted):
    """Keeps what each request carried: the system text, the messages and the tools it showed."""
    def __init__(self, script=None):
        super().__init__(script)
        self.sent = []

    def call(self, system, messages, schemas, names):
        self.sent.append({'system': system, 'messages': json.dumps(messages, ensure_ascii=False),
                          'tools': json.dumps({n: schemas[n] for n in names}, ensure_ascii=False), 'names': list(names)})
        return super().call(system, messages, schemas, names)


def asked(sent):
    return [where for where in ('system', 'messages', 'tools') if ASKS.search(sent[where])]


def test_in_thinking_mode_no_request_of_any_conversation_asks_for_her_thoughts():
    provider = Watching()
    rp.probe(args(dry_run=True, sequences=None), provider=provider)          # every fixture conversation
    assert len(provider.sent) > 10
    for sent in provider.sent:
        assert 'think' not in sent['names'] and not asked(sent), asked(sent)


def test_in_tool_mode_the_same_check_finds_the_stage_in_every_request():
    provider = Watching()
    rp.probe(args(dry_run=True, thoughts='tool'), provider=provider)
    assert provider.sent and all('think' in sent['names'] and asked(sent) for sent in provider.sent)
    first = provider.sent[0]['messages']
    assert json.dumps(THINK_FIRST, ensure_ascii=False)[1:-1] in first


def test_in_thinking_mode_she_speaks_without_a_thought_and_nothing_hands_the_turn_back():
    out, text = rp.probe(args(), provider=rp.Scripted([speak(1), DONE, speak(2), DONE]))
    assert out['result'] == 'PASS', text
    assert out['requests'] == 4, 'no hand-back asked for a thought'


def test_in_tool_mode_speaking_before_a_thought_is_still_refused():
    provider = Watching([speak(1), DONE, speak(2), DONE])
    out, _ = rp.probe(args(thoughts='tool'), provider=provider)
    assert out['result'] != 'PASS'
    assert json.dumps(role_tools.THINK_FIRST, ensure_ascii=False)[1:-1] in provider.sent[1]['messages']


def test_the_turn_steps_follow_the_mode_and_tool_mode_keeps_its_words():
    tool, unset, thinking = block_guide.guide({'thoughts': 'tool'}), block_guide.guide({}), block_guide.guide(
        {'thoughts': 'thinking'})
    assert tool == unset and '1. 第一步调用 think' in tool
    assert not ASKS.search(thinking.split('# 每回合的资料')[0])
    assert '1. 需要时用工具' in thinking and '2. ' in thinking and '3. ' not in thinking.split('说话时')[0]


def test_the_tool_lists_drop_think_only_in_thinking_mode():
    assert 'think' in role_tools.EVERYWHERE
    assert role_tools.thinking_mode({'thoughts': 'thinking'}) and not role_tools.thinking_mode({})
    assert role_tools.asks_thought({'turn_tools': ['think', 'recall']})
    assert not role_tools.asks_thought({'turn_tools': ['recall']}) and not role_tools.asks_thought({})
    assert 'think' not in role_tools.STAY_SILENT_THINKING and '心里话' not in role_tools.STAY_SILENT_THINKING
    assert 'think' not in role_tools.CONSULT_ONLY_THINKING


DEPLOYMENT = {'database': 'd', 'mongo_uri': 'mongodb://127.0.0.1', 'chat': {},
              'embedding': {'base_url': 'http://127.0.0.1:9/v1', 'model': 'm'}}
MODELS = {'character': {'model': 'x'}, 'action': {'model': 'x'}}


def test_the_setting_is_tool_or_thinking_and_shown_as_tool_by_default():
    for value in ('tool', 'thinking'):
        assert native_settings.runtime_settings({**DEPLOYMENT, 'thoughts': value}, {}, MODELS, persona='p')['thoughts'] == value
    assert 'thoughts' not in native_settings.runtime_settings(DEPLOYMENT, {}, MODELS, persona='p')
    with pytest.raises(ValueError, match='INVALID_THOUGHTS'):
        native_settings.runtime_settings({**DEPLOYMENT, 'thoughts': 'off'}, {}, MODELS, persona='p')
    assert native_settings.export_settings({'chat': {}})['deployment']['thoughts'] == 'tool'
    assert native_settings.export_settings({'chat': {}, 'thoughts': 'thinking'})['deployment']['thoughts'] == 'thinking'


# ---- capture, links and projection (§3.1 items 3-5) ------------------------------------------------------------------
from asuna import reasons                 # noqa: E402

THOUGHT = '他问我家有没有猫，我想起橘猫那天的事，想顺着聊两句，不太想把话题拉远。' * 5     # 190 characters, past the 120 cut


def thinking(text=THOUGHT):
    return {'type': 'thinking', 'thinking': text, 'signature': 'sig'}


def with_thought(i, block=None, text='在呢'):
    head = [block] if block else []
    return rp.reply('tool_use', head + [{'type': 'tool_use', 'id': 's%d' % i, 'name': 'speak',
                                         'input': {'parts': [{'kind': 'text', 'text': text}]}}])


def test_the_first_thinking_of_a_turn_is_recorded_and_comes_back_short_marked_and_with_what_it_led_to():
    provider = Watching([with_thought(1, thinking()), DONE, with_thought(2, thinking('又来问了')), DONE])
    out, text = rp.probe(args(), provider=provider)
    assert out['result'] == 'PASS', text
    assert out['thoughts_recorded'] == {'taken': 2, 'none': {}}
    # The next turn's notice (the program's context; the history also replays the model's own thinking block).
    notice = json.loads(provider.sent[2]['messages'])[-1]['content'][0]['text']
    assert reasons.THINKING_LABEL in notice and THOUGHT[:20] in notice
    assert THOUGHT[:130] not in notice, 'cut at 120 characters'


def test_a_turn_whose_model_did_not_think_or_was_redacted_says_so_in_the_audit_and_nothing_waits():
    provider = rp.Scripted([with_thought(1), DONE, with_thought(2, {'type': 'redacted_thinking', 'data': 'x'}), DONE])
    out, text = rp.probe(args(), provider=provider)
    assert out['result'] == 'PASS', text
    assert out['thoughts_recorded'] == {'taken': 0, 'none': {'no_thinking': 1, 'redacted': 1}}


def test_a_turn_with_no_call_is_captured_from_its_one_response():
    home = str(rp.FIXTURES / 'sequences' / 'home.json')
    provider = rp.Scripted([rp.reply('end_turn', [thinking(), {'type': 'text', 'text': '好呀'}])] * 4)
    out, _ = rp.probe(args(sequences=[home]), provider=provider)
    assert out['thoughts_recorded']['taken'] >= 1


def test_tool_mode_records_nothing_from_thinking():
    provider = rp.Scripted([rp.reply('tool_use', [thinking(), {'type': 'tool_use', 'id': 'k1', 'name': 'think',
                                                               'input': {'thought': '嗯'}}]), with_thought(1), DONE])
    out, _ = rp.probe(args(thoughts='tool'), provider=provider)
    assert 'thoughts_recorded' not in out


def test_shown_cuts_and_marks_only_a_summary_and_recall_reads_more():
    mine = {'body_markdown': '我' * 300}
    summary = {'body_markdown': '摘' * 300, 'source': 'thinking'}
    assert reasons.shown(mine) == '我' * 300 and reasons.shown({}) is None
    short = reasons.shown(summary)
    body = lambda text: text[len(reasons.THINKING_LABEL):]
    assert short.startswith(reasons.THINKING_LABEL) and body(short).count('摘') == reasons.THINKING_CHARS
    assert body(reasons.shown(summary, 1200, recall=True)).count('摘') == 300


def test_a_summary_led_to_the_call_it_came_with_and_every_call_after_it_has_it_as_reason():
    from types import SimpleNamespace
    import mongomock
    db = mongomock.MongoClient().db
    plan = {'op': 'create', 'intent': '明早提醒他带伞'}
    for seq, (cid, tool, args) in enumerate([('c1', 'plan', plan), ('c2', 'stay_silent', {'reason': '先不说'})]):
        db.audit_events.insert_one({'stream_id': 'ep-1', 'type': 'role_tool', 'seq': seq,
                                    'payload': {'call_id': cid, 'tool': tool, 'args': args}})
    from asuna import records
    store = SimpleNamespace(db=db, collection=records.on(db).collection)   # the owners' way to the same rows
    lines = reasons.then(store, {'_id': 'mono-ep-1:c1', 'episode_id': 'ep-1', 'source': 'thinking'})
    assert lines[0].startswith('所以我定了个计划') and lines[1] == '所以我没说话：先不说'
    mine = reasons.then(store, {'_id': 'mono-ep-1:c1', 'episode_id': 'ep-1'})
    assert mine == ['所以我没说话：先不说'], 'a think call itself is not what it led to'
    episode = {'_id': 'ep-1', 'tool_calls': {'c1': {'tool': 'plan', 'seq': 1}}, 'thinking_ref': 'mono-ep-1:c1'}
    assert reasons.newest(episode, 5) == 'mono-ep-1:c1' and reasons.newest({'_id': 'e', 'tool_calls': {}}) is None


def test_a_view_of_a_person_in_a_turn_without_a_thought_takes_the_line_she_answers(store):
    from asuna.context import ContextBuilder
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    store.config['thoughts'] = 'thinking'
    store.db.state_heads.delete_many({'_id': {'$regex': '^relationship:A\|'}})
    lane = FakeLane(store, [FakeTurn([('understand_person', {'layer': 'here', 'content': 'A 喜欢先听结论。',
                                                              'short': '先说结论'})], '好。')])
    event = {'event_id': 'no-thought', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '结论先说。'}
    done = Coordinator(store, lane).ingest(event)
    assert done['state'] == 'COMMITTED'
    _, revision = store.head('relationship:A', 'scene:dm-a')
    sources = revision['source_ids']
    assert sources and all(source.startswith('chunk-') for source in sources), 'the line she answered, made on demand'
    _, after, _ = ContextBuilder(store).prepare({**event, 'event_id': 'later'})
    assert after['relationship']['here'] == 'A 喜欢先听结论。'
