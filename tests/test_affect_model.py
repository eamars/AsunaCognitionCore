"""ADR-086 stage 1: feelings toward a person leave the global mood (D1), arousal comes from the kind (D3), the mood she
reads is one paragraph and nothing at a quiet band (D4, D6), someone calling her is said as a choice (E2, E3), and the
dice review shows the band (D7)."""
import json

from asuna import affect
from asuna.affect import affect_model, from_words, interpret, person_feelings, project
from conftest import FIXTURES

MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))
AT = '2026-10-21T02:00:00+00:00'


def model_with(**affect_changes):
    base = json.loads(json.dumps(MODEL))
    base['affect'].update(affect_changes)
    return affect_model(base)


def event(kind, val, who=None, hours_ago=0.5, scope='global-safe', why='why'):
    from datetime import datetime, timedelta
    ts = (datetime.fromisoformat(AT) - timedelta(hours=hours_ago)).isoformat()
    return {'id': 'e-%s-%s-%s' % (kind, who, hours_ago), 'kind': kind, 'val': val, 'arl': 0, 'ts': ts, 'why': why,
            'source_scope': scope, **({'who': who} if who else {})}


def test_a_feeling_toward_a_person_is_left_out_of_the_global_mood_and_counted_for_that_person():
    model = model_with(kinds={**MODEL['affect']['kinds'], 'attachment': {**MODEL['affect']['kinds']['attachment'], 'about': 'person'}})
    events = [event('joy', 20), event('attachment', 40, who='qq:1'), event('attachment', 40, who='qq:2')]
    whole = project(model, events, [], AT)
    assert round(whole['val']) == round(20 * 0.5 ** (0.5 / model['kinds']['joy']['half_h']))
    assert [row['kind'] for row in whole['contributions']] == ['joy']
    theirs = project(model, events, [], AT, who='qq:1')
    assert [row['kind'] for row in theirs['contributions']] == ['attachment'] and theirs['val'] > 30
    felt = person_feelings(model, theirs, 'public')
    assert felt == [{'feeling': 'attachment', 'strength': '强烈', 'when': felt[0]['when']}]
    assert 'why' in person_feelings(model, theirs, 'owner_private')[0]        # the reason only at home


def test_arousal_comes_from_the_kind_when_she_writes_none_and_her_own_word_wins():
    model = model_with(kinds={**MODEL['affect']['kinds'], 'joy': {**MODEL['affect']['kinds']['joy'], 'arousal': '有些波动'}})
    scale = model['scale']['arl']
    assert from_words(model, {'kind': 'joy', 'intensity': '明显', 'ref': 'r', 'why': 'w'})['arl'] == scale['有些波动']
    assert from_words(model, {'kind': 'joy', 'intensity': '明显', 'arousal': '激动', 'ref': 'r', 'why': 'w'})['arl'] == scale['激动']
    assert from_words(model, {'kind': 'calm', 'intensity': '明显', 'ref': 'r', 'why': 'w'})['arl'] == scale['平稳']   # no word on the kind


def test_the_mood_is_one_paragraph_with_the_causes_readable_here_and_nothing_at_a_quiet_band():
    model = model_with()
    strong = project(model, [event('joy', 40, scope='g1', why='他夸了我'), event('pride', 40, scope='owner-private:P1', why='秘密')], [], AT)
    here = interpret(model, strong, 'public', scope='g1')
    assert set(here) == {'心情'} and '他夸了我（这里记的）' in here['心情'] and '秘密' not in here['心情']
    assert affect.PUBLIC_MORE_NOTE in here['心情'] and '这会儿你把方法记下来' in here['心情']   # a cause elsewhere; the pull
    elsewhere = interpret(model, strong, 'public', scope='g2')
    assert '他夸了我' not in elsewhere['心情'] and affect.PUBLIC_MOOD_NOTE in elsewhere['心情']
    home = interpret(model, strong, 'owner_private')
    assert '秘密' not in home['心情'] and 'pride（强烈' in home['心情']          # home names the cause; its words are in reasons
    assert [r['why'] for r in home['reasons']] == ['秘密', '他夸了我'] and all(len(r['event_id']) == 12 for r in home['reasons'])
    assert not any(ch.isdigit() for ch in home['心情'])
    faint = project(model, [event('sadness', -20, scope='g1')], [], AT)        # the fallback band: quiet by default
    assert interpret(model, faint, 'public', scope='g1') is None
    assert set(interpret(model, faint, 'owner_private')) == {'reasons'}      # at home the ids stay, to close or void
    old = model_with(paragraph=False)
    assert {'label', 'policy', 'tendencies', 'note'} <= set(interpret(old, strong, 'public'))


def test_a_band_marked_quiet_sends_nothing_even_with_causes():
    bands = [{**band, 'quiet': True} if band.get('label') == '愉快' else band for band in MODEL['affect']['bands']]
    model = model_with(bands=bands)
    state = project(model, [event('joy', 40, scope='g1', why='他夸了我')], [], AT)
    assert interpret(model, state, 'public', scope='g1') is None


