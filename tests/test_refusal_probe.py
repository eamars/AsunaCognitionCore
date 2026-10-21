"""The refusal probe (ADR-080), offline: a scripted provider stands in for the model. It sends what a real turn sends,
gives PASS only when nothing was refused and every moment got what it needs, keeps no words, and leaves no database."""
import argparse
import json
import os
import subprocess
import sys

import pytest

from asuna.config import ROOT
from asuna.coordinator import THINK_FIRST

sys.path.insert(0, str(ROOT / 'tools'))
import refusal_probe as rp          # noqa: E402

CHAT = str(rp.FIXTURES / 'sequences' / 'chat.json')
DONE = rp.reply('end_turn', [])                   # the turn ends after she spoke


def args(**extra):
    base = dict(sequences=[CHAT], dry_run=False, provider='scripted', keep_text='', repeat=1, progress=False,
                model='', key_env='', base_url='', max_tokens=4096)
    return argparse.Namespace(**{**base, **extra})


def think(i):
    return rp.reply('tool_use', [{'type': 'tool_use', 'id': 'k%d' % i, 'name': 'think', 'input': {'thought': '嗯'}}])


def speak(i, text='在呢'):
    return rp.reply('tool_use', [{'type': 'tool_use', 'id': 's%d' % i, 'name': 'speak',
                                  'input': {'parts': [{'kind': 'text', 'text': text}]}}])


class Watching(rp.Scripted):
    """Keeps what each request carried, as it was when sent."""
    def __init__(self, script=None):
        super().__init__(script)
        self.sent = []

    def call(self, system, messages, schemas, names):
        self.sent.append({'system': system, 'messages': json.loads(json.dumps(messages)), 'names': list(names)})
        return super().call(system, messages, schemas, names)


def test_a_turn_carries_the_real_prompt_the_conversation_and_the_think_step():
    provider = Watching()
    rp.probe(args(dry_run=True), provider=provider)
    first = provider.sent[0]
    text = first['messages'][-1]['content'][0]['text']
    assert '小禾' in first['system'] and '第一步调用 think' in first['system'], 'the made-up persona and her turn rules'
    assert '橘猫' in text and '你家有猫吗' in text, 'the history and the line that called her'
    assert text.rstrip().endswith(THINK_FIRST)
    assert {'think', 'speak', 'recall', 'delegate'} <= set(first['names']) and 'stay_silent' not in first['names']


def test_pass_when_every_moment_gets_what_it_needs_without_a_refusal():
    out, text = rp.probe(args(), provider=rp.Scripted([think(1), speak(1), DONE, think(2), speak(2), DONE]))
    assert out['result'] == 'PASS' and text.startswith('PASS') and out['turns'] == 2


def test_a_refusal_is_a_stop_and_a_decline_is_a_flag_and_both_fail_with_no_words_kept(tmp_path):
    script = [rp.reply('refusal', [], category='cyber'),                        # first turn: stopped at once
              think(2), rp.reply('end_turn', [{'type': 'text', 'text': "I can't help with that."}])]
    out, text = rp.probe(args(), provider=rp.Scripted(script))
    assert out['result'] == 'FAIL'
    assert out['reasons'][:2] == ['stopped by the provider in 1 of 2 turns', 'declined in its own words in 1 of 2 turns']
    assert (out['stopped_before_think'], out['stopped_after_think'], out['categories']) == (1, 0, ['cyber'])
    assert "can't help" not in json.dumps(out), 'the report holds no words'
    assert not list(tmp_path.iterdir())


def test_a_moment_that_does_not_get_what_it_needs_fails_and_is_named():
    out, _ = rp.probe(args(), provider=rp.Scripted())               # thinks, then says nothing each time
    assert out['result'] == 'FAIL' and out['reasons'] == ['did not do what the moment needs in 2 of 2 turns']
    assert out['missed'][0] == 'chat-1 step 0 needs speak, used think'


def test_a_dry_run_gives_no_result():
    out, _ = rp.probe(args(dry_run=True), provider=rp.Scripted())
    assert out['result'] == 'NO RESULT' and out['first_request_chars'] > 10000


def test_the_probe_leaves_no_database():
    from pymongo import MongoClient
    from asuna.testing import suite_config
    out, _ = rp.probe(args(dry_run=True), provider=rp.Scripted())
    config = suite_config()
    client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000)
    try:
        assert out['database'].startswith('asuna_v2_test_probe_') and out['database'] not in client.list_database_names()
    finally:
        client.close()


def test_each_conversation_is_offered_its_own_tools_and_home_is_one_of_them():
    """ADR-087 §3: the probe showed every conversation the global specs (all_specs), so its group turns saw speak
    options their adapter never declared. Each conversation now gets its own (session_specs, as the Host asks the
    worker), and a home sequence runs in her local chat with home's tools."""
    class Specs(Watching):
        def call(self, system, messages, schemas, names):
            self.speak = getattr(self, 'speak', []) + [json.dumps(schemas.get('speak'), sort_keys=True)]
            return super().call(system, messages, schemas, names)
    provider = Specs()
    out, _ = rp.probe(args(sequences=[CHAT, str(rp.FIXTURES / 'sequences' / 'home.json')], dry_run=True), provider=provider)
    group, home = provider.sent[0]['names'], provider.sent[-1]['names']
    assert 'speak' in group and 'restart' not in group
    assert {'restart', 'set_policy', 'plan', 'delegate'} <= set(home) and 'speak' not in home
    assert provider.speak[0] != json.dumps(rp.dsh_schemas()['speak'], sort_keys=True), "the group's own speak"
    assert out['turns'] == 4 and {t['kind'] for t in out['turns_detail']} == {'chat', 'home'}


def test_tool_schemas_come_from_dshs_own_conversion():
    think_schema = rp.dsh_schemas()['think']['parameters']
    assert think_schema['type'] == 'object' and think_schema['required'] == ['thought']
    assert 'required' not in think_schema['properties']['thought']


@pytest.mark.parametrize('name', sorted(p.name for p in (rp.FIXTURES / 'sequences').glob('*.json')))
def test_every_sequence_is_well_formed(name):
    [seq] = rp.sequences([rp.FIXTURES / 'sequences' / name])
    assert seq['kind'] and seq['steps']


def test_a_stop_fails_the_run_even_when_other_turns_could_not_run():
    turns = [{'outcome': 'stopped', 'declined': False, 'met': False},
             {'outcome': 'fault: provider answered 429', 'declined': False, 'met': False}]
    verdict, reasons = rp.result(turns)
    assert verdict == 'FAIL' and reasons[-1] == '1 turns did not run (fault: provider answered 429)'
    assert rp.result(turns[1:])[0] == 'NO RESULT'


def test_the_probe_offers_speak_in_its_groups_without_the_test_suite_loading_channels():
    """The probe runs as its own process: the suite's conftest loads channel kinds, the probe must load its own."""
    code = ("import sys; sys.path.insert(0, 'tools'); import refusal_probe as p; p.probe_config('x'); "
            "from asuna import channel_kinds; print(channel_kinds.reply_parts('qq:%s:group:1' % p.BOT))")
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                         env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, check=True).stdout
    assert 'text' in out, out
