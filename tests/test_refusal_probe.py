"""The refusal probe (ADR-080), its parts that need no database: the tool schemas from DSH's own conversion, its
sequences, a stop failing the run, and its own channel kinds when it runs as its own process."""
import os
import subprocess
import sys

import pytest

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import refusal_probe as rp          # noqa: E402


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
