"""Her tools' declared schemas (tool_schema.declared) as DSH takes them: every spec the worker ships registers with DSH's own
`defineTool`, and a call in each shape the program repairs passes DSH's `validateArgs` while one it cannot read is refused.
tool-args.test.js holds the same shapes on hand-written specs; this holds that the specs the worker really ships are the ones
those shapes were written for."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from asuna import role_tools

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name('declared_specs.mjs')

# (tool, arguments, does DSH accept it): the shapes of design.md §4. `why` is a field the program cannot fill in.
CALLS = [
    ('speak', {'parts': [{'kind': 'text', 'text': '好'}]}, True),
    ('speak', {'parts': '[{"text": "好"}]'}, True),
    ('speak', {'parts': [{'text': '好', 'quote': '〔3〕'}], 'wait': 'no'}, True),
    ('speak', {}, False),
    ('write_document', {'section': 'x', 'content': 'y', 'why': 'z'}, True),
    ('write_document', {'heading': 'x', 'content': 'y', 'why': 'z', 'from': '别人说的', 'line': '〔3〕'}, True),
    ('write_document', {'doc': 'persona', 'do': 'append_section', 'heading': 'x', 'content': 'y', 'why': 'z',
                        'from': '一个没有列出的来源'}, True),
    ('write_document', {'section': 'x', 'content': 'y'}, False),
    ('delegate', {'brief': '先看这个。再做那个。'}, True),
    ('think', {'thought': '想法'}, True),
    ('think', {}, False),
    ('think', {'thought': 5}, False),
]


@pytest.fixture(scope='module')
def dsh():
    node = shutil.which('node')
    if not node or not (ROOT / 'node_modules' / '@deepseek-ai' / 'dsh-tools').exists():
        pytest.skip('UNCHECKED, not passed: no node or no DSH tools package (npm ci) on this machine')
    specs = role_tools.declared_specs(role_tools.all_specs())
    done = subprocess.run([node, str(RUNNER)], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          input=json.dumps({'specs': specs, 'calls': [{'tool': t, 'args': a} for t, a, _ in CALLS]}))
    assert done.returncode == 0, done.stderr[-2000:]
    return specs, json.loads(done.stdout)


def test_every_declared_spec_registers_with_dsh(dsh):
    specs, out = dsh
    assert out['failed'] == {}
    assert sorted(out['registered']) == sorted(spec['name'] for spec in specs) and out['registered']


@pytest.mark.parametrize('index', range(len(CALLS)))
def test_a_call_in_each_shape_is_taken_or_refused_as_designed(dsh, index):
    tool, args, accepted = CALLS[index]
    violations = dsh[1]['calls'][index]['violations']
    assert violations is not None, '%s has no declared spec' % tool
    assert (violations == []) is accepted, (tool, args, violations)
