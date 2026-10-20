"""ADR-086 §11.9: her own persona edits after stage 1 pass the publish flow's validation unchanged, and her policy tool
can set every key she asked for. The real persona package is read, never written: the diff is applied to a copy."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from asuna import persona_model
from asuna.affect import affect_model, from_words, project
from asuna.policy import PolicyStore

PACKAGE = Path(__file__).resolve().parents[1] / 'packages' / 'personas' / 'xiaoman' / 'persona-model.json'
PERSON_KINDS = ('gratitude', 'closeness', 'hurt')
HALF_LIVES = {'irritation': 6, 'unease': 12}
AROUSAL = {'joy': '有些波动', 'curiosity': '有些波动', 'satisfaction': '平稳', 'calm': '平稳', 'gratitude': '平稳',
           'closeness': '平稳', 'unease': '有些波动', 'sadness': '平稳', 'irritation': '有些波动', 'hurt': '有些波动'}
EDITED_STANCE = '不熟，就是闲聊：友好、好奇，可以开玩笑、聊两句、说说自己怎么看；不替他干活。他要你帮忙做事，你可以推，怎么推由你。'


def her_model_with_the_diff():
    """A copy of her real model with persona-diff-for-her.md applied (D1, D2, D3, D4's quiet band, the policy keys)
    and one stance edited as she said she would."""
    if not PACKAGE.exists():
        pytest.skip('UNCHECKED, not passed: her persona package is not in this tree')
    model = json.loads(PACKAGE.read_text(encoding='utf-8'))
    affect = model['affect']
    for kind in PERSON_KINDS:
        affect['kinds'][kind]['about'] = 'person'
    for kind, hours in HALF_LIVES.items():
        affect['kinds'][kind]['half_h'] = hours
    for kind, word in AROUSAL.items():
        affect['kinds'][kind]['arousal'] = word
    for band in affect['bands']:
        if band.get('label') == '不错':
            band['quiet'] = True
    words = list((affect.get('scale') or affect_model({})['scale'])['arl'])
    keys = model.setdefault('policy_keys', {})
    for kind, spec in affect['kinds'].items():
        keys['affect.kinds.%s.half_h' % kind] = {'type': 'number', 'min': 0.25, 'max': 168, 'what': '%s的半衰期（小时）' % spec['label']}
        keys['affect.kinds.%s.arousal' % kind] = {'type': 'string', 'enum': words, 'what': '%s默认的激动程度' % spec['label']}
    model['people']['familiarity']['new']['stance'] = EDITED_STANCE
    return model


def test_her_persona_with_the_diff_and_an_edited_stance_passes_the_publish_validation(tmp_path):
    model = her_model_with_the_diff()
    copy = tmp_path / 'persona-model.json'
    copy.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding='utf-8')
    loaded = persona_model.load(copy, model['persona']['id'])         # what floor.js runs before activation
    assert loaded['affect']['kinds']['closeness']['about'] == 'person'
    assert loaded['people']['familiarity']['new']['stance'] == EDITED_STANCE
    assert 'affect.kinds.irritation.arousal' in persona_model.writable_keys(loaded)
    assert persona_model.load(PACKAGE, model['persona']['id'])        # and her file as it is today still loads


def test_each_new_policy_key_set_through_the_policy_path_changes_the_projection():
    model = her_model_with_the_diff()
    policy = PolicyStore(None, model['persona']['id'], model)
    at = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
    event = {'id': 'e1', 'kind': 'irritation', 'val': -20, 'arl': 0, 'ts': (at - timedelta(hours=6)).isoformat()}
    before = project(affect_model(model), [event], [], at)['val']
    changes = policy.validate([{'key': 'affect.kinds.irritation.half_h', 'value': 24, 'what': '试试更久'},
                               {'key': 'affect.kinds.irritation.arousal', 'value': '激动', 'what': '试试更冲'}])
    applied = affect_model(model, changes)
    after = project(applied, [event], [], at)['val']
    assert before == pytest.approx(-10) and after < before                    # a longer half-life holds the feeling
    assert from_words(applied, {'kind': 'irritation', 'intensity': '轻微', 'ref': 'r', 'why': 'w'})['arl'] == applied['scale']['arl']['激动']
    with pytest.raises(ValueError):                                             # a word outside her scale is refused
        policy.validate([{'key': 'affect.kinds.irritation.arousal', 'value': '狂躁', 'what': 'x'}])
