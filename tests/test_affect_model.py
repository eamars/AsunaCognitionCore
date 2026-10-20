"""ADR-086 stage 1: feelings toward a person leave the global mood (D1), arousal comes from the kind (D3), the mood she
reads is one paragraph and nothing at a quiet band (D4, D6), someone calling her is said as a choice (E2, E3), and the
dice review shows the band (D7)."""
import json

from asuna import affect
from asuna.affect import affect_model, from_words, interpret, person_feelings, project
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.role_tools import CALLED_NOTE, called
from conftest import FIXTURES

MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))
THINK = ('think', {'thought': '嗯。'})
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
    assert '秘密' in home['心情'] and len(home['reasons']) == 2 and all(len(r['event_id']) == 12 for r in home['reasons'])
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


def test_the_gate_reads_the_public_paragraph_or_nothing(store):
    from asuna import attend
    from test_adr009_p3 import setup as persona_setup
    from test_attend import gated_event, setup
    from test_people import SCENE
    setup(store)
    persona_setup(store)
    store.config['persona_model'] = json.loads(json.dumps(store.config['persona_model']))
    scene = store.db.scenes.find_one({'_id': SCENE})
    ev = gated_event(20002, '今晚开黑吗')
    row = {'author': 'qq:20002', 'scene_seq': 1, 'text': '今晚开黑吗', 'received_at': AT, 'event': ev}
    quiet = attend.material(store, scene, ev, row, 'P1')
    assert 'mood' not in quiet                                              # no feelings: the fallback band is quiet
    from asuna.affect import AffectLedger
    ledger = AffectLedger(store, 'P1', store.config['persona_model'])
    from datetime import datetime, timedelta, timezone
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()      # the gate projects at the real now
    store.db.affect_events.insert_one({**event('joy', 40, scope=scene['scope_key'], why='他夸了我'), '_id': 'joy-here', 'ts': fresh,
                                       'persona': 'P1', 'origin': 'asuna', 'schema_version': 1})
    assert ledger.enabled
    loud = attend.material(store, scene, ev, row, 'P1')
    assert isinstance(loud['mood'], str) and '他夸了我' in loud['mood']
    store.config['persona_model']['affect']['gate'] = 'none'
    assert 'mood' not in attend.material(store, scene, ev, row, 'P1')


def test_feel_lands_a_person_feeling_with_the_person_only_where_it_cannot_be_a_guess(store):
    """D1: in a one-to-one conversation an unwritten who is the person there; in a group it stays global, and the
    receipt says so; a who she writes is resolved from the label."""
    from test_adr009_p3 import setup
    from test_engineering_m1 import event as turn_event
    setup(store)
    store.config['persona_model'] = json.loads(json.dumps(store.config['persona_model']))
    store.config['persona_model']['affect']['kinds']['attachment']['about'] = 'person'
    if True:
        record = ('feel', {'do': 'record', 'feeling': 'attachment', 'intensity': '明显', 'ref': 'dm-1', 'why': '聊得来', 'cost': '无'})
        lane = FakeLane(store, [FakeTurn([THINK, record], '嗯。')])
        Coordinator(store, lane).ingest(turn_event('dm-1'))
        receipt = lane.tool_results[1][4]
        stored = store.db.affect_events.find_one({'why': '聊得来'})
        assert receipt['landed'].startswith('记在了对') and stored['who'] == 'A'
        lane = FakeLane(store, [FakeTurn([THINK, ('feel', {**record[1], 'ref': 'group-1', 'why': '群里聊得来'})], '嗯。')])
        Coordinator(store, lane).ingest(turn_event('group-1', scene='g1'))
        assert lane.tool_results[1][4]['landed'] == '没写对谁，算进了你的心情'
        assert 'who' not in store.db.affect_events.find_one({'why': '群里聊得来'})
        lane = FakeLane(store, [FakeTurn([THINK, ('feel', {**record[1], 'ref': 'group-2', 'why': '错的人', 'who': '[没有这人 #99]'})], '嗯。')])
        Coordinator(store, lane).ingest(turn_event('group-2', scene='g1'))
        assert not lane.tool_results[1][5] and '不是这个对话里的人' in lane.tool_results[1][4]


def test_someone_calling_her_is_said_as_her_choice_and_silence_says_what_it_leaves(store):
    from test_adr009_p3 import setup
    from test_engineering_m1 import event as turn_event
    setup(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'why': '不想说'})])])
    ep = Coordinator(store, lane).ingest(turn_event('dm-call'))
    assert ep['context']['called_from_program'] == CALLED_NOTE
    assert lane.tool_results[1][4]['left'].endswith('想回头回就挂一条 plan。')
    assert not called({'episode_kind': 'heartbeat', 'person_id': 'A', 'context': {'event': {}}})
    assert called({'episode_kind': 'external', 'person_id': 'A',
                   'context': {'event': {'group_context': {'wake_reason': 'mentioned_account'}}}})
    assert not called({'episode_kind': 'external', 'person_id': 'A',
                       'context': {'event': {'group_context': {'wake_reason': 'proactive_unprompted'}}}})


def test_the_dice_review_names_the_band_at_each_roll(store):
    from asuna import dice
    from test_adr009_p3 import setup
    setup(store)
    from datetime import datetime
    store.db.audit_events.insert_one({'_id': 'roll-1', 'schema_version': 1, 'stream_id': 'presence', 'type': 'presence.rolled',
                                      'scope_key': 'global-safe', 'occurred_at': AT,
                                      'payload': {'outcome': 'nothing', 'period': 'awake', 'reaches': False, 'occurrence': 'x'}})
    rows = dice.review(store, 'P1', 'y', datetime.fromisoformat(AT))['rolls']
    assert rows and rows[-1]['mood']
