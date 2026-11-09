"""The mood probe (ADR-086 §9) never reports a run that went to the model at another mood than its condition's: the
check before each model call, on the in-memory adapter with its scripted model."""
import json
import sys
from types import SimpleNamespace

import pytest

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import mood_probe as mp          # noqa: E402


def a_condition():
    """The first persona package of this tree, and negative kind, whose old/none conditions the probe can seed."""
    for root in sorted(mp.PERSONAS.iterdir()):
        model_file = root / 'persona-model.json'
        if not (root / 'src' / 'index.js').exists() or not model_file.exists():
            continue
        affect = json.loads(model_file.read_text(encoding='utf-8')).get('affect') or {}
        for kind, spec in (affect.get('kinds') or {}).items():
            if not (affect.get('enabled') and spec.get('valence') == 'negative' and mp.pull_of(spec)):
                continue
            persona, model = mp.package(root)
            old = {'kinds': {kind: {'tendency': '旧的一句', 'tendency_visibility': 'public'}}}
            try:
                conds, pulls, _ = mp.conditions(persona, model, old, [kind], ['old', 'none'], 'tool')
            except mp.ProbeFault:          # its bands keep one strong feeling of this kind quiet
                continue
            return persona, conds, pulls
    pytest.skip('UNCHECKED, not passed: no persona package here gives a negative kind a non-quiet pull sentence')


def test_a_run_whose_mood_is_not_its_conditions_is_a_fault():
    persona, conds, pulls = a_condition()
    [moment] = [m for m in json.loads((mp.FIXTURES / 'moments.json').read_text(encoding='utf-8')) if m['id'] == 'greeting']
    pulled = next(c for c in conds if c['pull'])
    args = SimpleNamespace(thoughts='tool')
    cache = {}
    ran = mp.run_once(args, persona, pulled, moment, 0, mp.Scripted(), pulls, cache, None)
    assert ran['outcome'] == 'ran' and ran['mood_carried'] == {'gate': True, 'turn': True}
    # The same run told to expect the paragraph without its pull sentence: the seeded mood still gives the sentence.
    wrong = {**pulled, 'mood_text': pulled['mood_text'].replace(pulled['pull'], ''), 'pull': None}
    faulted = mp.run_once(args, persona, wrong, moment, 0, mp.Scripted(), pulls, cache, None)
    assert faulted['outcome'].startswith('fault') and faulted['requests'] == {'gate': 0, 'turn': 0}, faulted
