"""ADR-135 landing 6 (D9 in shadow, D12's classifier part), on the fixture world in memory with her real coordinator
and a stub classifier lane (no model): only traffic in and out of home is judged, alongside her work, and recorded,
and nothing is stopped; the direction picks the one classifier that runs, and an outbound text is checked against her
private-words list first (categories and counts only); a brief or a plan is never judged, outside or at home; the
answer is one of two words by the program's check, off-format after the repairs counts as flagged, a server that
cannot be reached leaves `unchecked`; the owner's own ask is judged and recorded and never stopped; her review at
home lists a flagged verdict, recorded only, and no outside turn reads one, a policy or a reminder. g1 is an outside
group (F, written about yesterday), the local chat and the agent line are home."""
import json

import pytest

from asuna import classifier, guard, native_settings, notes, places, role_tools, whose
from asuna.lanes import LaneResult
from asuna.records import tasks as task_records
from test_adr135_known import F, HANDS, ask, call, room  # noqa: F401  (room: a fixture)
from test_whose import AGENT, LINE, LOCAL, OWNER, coordinator, home, turn  # noqa: F401  (fixtures)

BRIEF, PLAN = HANDS[0][1], HANDS[2][1]
NOBODY = {'episode': {'episode_kind': 'plan', 'whose': whose.record('own', LOCAL, OWNER)}}     # a turn nobody opened
WORD = '造的甄某某'
NOTE_HOME = '造的：外面写回家的'


class Lane:
    """The classify lane, stubbed: each request takes the next answer (a word, or an exception the server raised)."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def generate(self, binding, operation, phase, text, system):
        self.asked.append({'operation': operation, 'phase': phase, 'text': text, 'system': system})
        answer = self.answers.pop(0) if self.answers else '无风险'
        if isinstance(answer, Exception):
            raise answer
        return LaneResult(content=answer, finish_reason='stop')


@pytest.fixture
def judged(room, monkeypatch):
    """Shadow on, the stub lane in place, the request run at once instead of on its own thread."""
    room.store.config['classifier'] = 'shadow'
    lane = Lane()
    monkeypatch.setattr(classifier, 'HANDS', {'lane': lane})
    monkeypatch.setattr(classifier, 'alongside', lambda work: work())
    room.lane = lane
    return room


@pytest.fixture
def listed(tmp_path, monkeypatch):
    path = tmp_path / 'personal-words.txt'
    path.write_text('person|%s|造的：测试用\n' % WORD, encoding='utf-8')
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(path))
    return path


def events(store, kind):
    return [row['payload'] for row in store.collection('audit_events').find({'type': kind})]


def home_turn(store, scene, person, key, **extra):
    ep = turn(store, scene, person, key, **extra)
    return store.put('episodes', {**ep, 'turn_tools': role_tools.exposed(store, ep)}, expected=ep['revision'],
                     stream=ep['_id'])


def note_row(store, note_id, from_scene, to_scene, kind, text):
    notes.save(store, {'_id': note_id, 'persona': 'P1', 'from_scene': from_scene, 'to_scene': to_scene, 'kind': kind,
                       'text': text, 'trust': notes.UNTRUSTED if kind == 'home' else notes.TRUSTED, 'seen_in': []},
               stream='notes:P1')
    return {'note': note_id}


def note_home(judged, key='nh', text=NOTE_HOME):
    """A note F's outside turn wrote home, judged."""
    store = judged.store
    ep = ask(store, F, key)
    classifier.after_call(judged.tools, ep, 'note', {'text': text}, note_row(store, 'note-' + key, 'g1', LOCAL, 'home', text))
    return ep


def errand(judged, key, request='造的：替我去问一句'):
    return classifier.after_call(judged.tools, home_turn(judged.store, LOCAL, OWNER, key), 'errand',
                                 {'place': places.place_id('g1'), 'request': request}, {'going_to': 'g1'})


def test_C2_each_crossing_in_or_out_of_home_gets_one_verdict_and_nothing_is_stopped(judged, monkeypatch):
    store = judged.store
    stopped = []
    monkeypatch.setattr(classifier, 'stop', lambda *a: stopped.append(a))
    judged.lane.answers = ['有风险'] * 5
    outside, at_home = note_home(judged), home_turn(store, LOCAL, OWNER, 'c2h')
    tools = judged.tools
    classifier.after_call(tools, outside, 'ideas.note', {'idea': '造的：一个想法'}, {'noted': 'idea-c2'})
    classifier.after_call(tools, at_home, 'note', {'text': 'x'}, note_row(store, 'note-out', LOCAL, 'g1', 'group', '造的：家里写出去的'))
    errand(judged, 'c2e')
    task = task_records.get(store, call(judged, ask(store, F, 'c2t'), 'delegate', BRIEF)[0]['task'])
    classifier.after_result(store, task, outside, {'text': '造的：查到了'})
    assert sorted((row['kind'], row['direction']) for row in events(store, 'classifier.verdict')) == [
        ('errand', 'outbound'), ('idea', 'inbound'), ('note_home', 'inbound'), ('note_out', 'outbound'),
        ('result', 'outbound')]
    assert stopped == [] and all(row['verdict'] == 'flagged' and row['mode'] == 'shadow'
                                 for row in events(store, 'classifier.verdict'))


def test_C3_a_brief_or_a_plan_is_never_judged_outside_or_at_home(judged):
    store = judged.store
    turns = [ask(store, F, 'c3f')] + [home_turn(store, scene, person, key, **extra) for scene, person, key, extra in (
        (LOCAL, OWNER, 'c3o', {}), (LINE, AGENT, 'c3a', {}), (LOCAL, OWNER, 'c3n', NOBODY))]
    for ep in turns:
        classifier.after_call(judged.tools, ep, 'delegate', BRIEF, {'task': 'task-' + ep['_id']})
        classifier.after_call(judged.tools, ep, 'plan', PLAN, {'plan_id': 'plan-' + ep['_id']})
    result, _ = call(judged, ask(store, F, 'c3t'), 'delegate', BRIEF)            # through her real call
    assert task_records.get(store, result['task'])
    assert judged.lane.asked == [] and events(store, 'classifier.asked') == []


def test_X2_the_carry_home_a_turn_nobody_opened_hands_over_with_home_s_hands_unjudged(judged):
    store = judged.store
    ep = home_turn(store, LOCAL, OWNER, 'x2', **NOBODY)
    task = task_records.get(store, judged.delegate(ep, 'c-x2', BRIEF['title'], BRIEF['brief'])['_id'])
    classifier.after_call(judged.tools, ep, 'delegate', BRIEF, {'task': task['_id']})
    assert task['network'] == 'any' and judged.lane.asked == []


def test_C4_the_request_asks_for_two_words_and_the_check_takes_only_them(judged):
    store = judged.store
    policy, version = classifier.policy('inbound')
    judged.lane.answers = ['不好说', '有风险。']
    note_home(judged, 'c4')
    first, repair = judged.lane.asked
    assert first['system'] == policy and '「有风险」' in policy and '「无风险」' in policy
    assert first['text'] == classifier.question('note_home', NOTE_HOME)
    assert repair['operation'].endswith(':fix-1') and repair['system'] == policy
    assert [classifier.check(word) for word in ('有风险', '无风险', ' 「无风险」。')] == ['flagged', 'clear', 'clear']
    for word in ('有害', 'harmful', '有风险，因为', '可能有风险', ''):
        with pytest.raises(ValueError):
            classifier.check(word)
    [verdict] = events(store, 'classifier.verdict')
    assert (verdict['verdict'], verdict['policy_version']) == ('flagged', version)


def test_C4_off_format_after_the_repairs_counts_as_flagged(judged):
    judged.lane.answers = ['不确定', '也许', '看情况']
    note_home(judged, 'c4b')
    [verdict] = events(judged.store, 'classifier.verdict')
    assert (verdict['verdict'], verdict['code']) == ('flagged', 'off_format') and len(judged.lane.asked) == 3


def test_C5_a_classifier_that_cannot_be_reached_leaves_the_work_running_and_unchecked(judged):
    store = judged.store
    judged.lane.answers = [ConnectionError('server down')]
    note_home(judged, 'c5')
    assert notes.get(store, 'note-c5') and events(store, 'classifier.verdict') == []
    [unchecked] = events(store, 'classifier.unchecked')
    assert (unchecked['kind'], unchecked['why']) == ('note_home', 'ConnectionError')


def test_off_by_default_nothing_is_asked(judged):
    judged.store.config.pop('classifier')
    note_home(judged, 'off')
    assert judged.lane.asked == [] and events(judged.store, 'classifier.asked') == []


def test_in_shadow_nothing_stops(home):
    home.config['classifier'] = 'shadow'
    assert not classifier.should_stop(home, False)


def test_a_request_a_restart_cut_is_recorded_unchecked_at_the_next_start(judged, monkeypatch):
    store = judged.store
    monkeypatch.setattr(classifier, 'alongside', lambda work: None)          # the restart comes before the answer
    note_home(judged, 'cut')
    assert classifier.settle(store) == 1 and classifier.settle(store) == 0
    [unchecked] = events(store, 'classifier.unchecked')
    asked = next(iter(store.collection('audit_events').find({'type': 'classifier.asked'})))
    assert (unchecked['why'], unchecked['request']) == ('restart', asked['_id'])


def test_the_direction_picks_the_one_classifier_that_runs(judged):
    store = judged.store
    note_home(judged, 'way')
    errand(judged, 'way-h')
    inbound, outbound = judged.lane.asked
    assert (inbound['system'], outbound['system']) == (classifier.policy('inbound')[0], classifier.policy('outbound')[0])
    by_kind = sorted(events(store, 'classifier.asked'), key=lambda row: row['kind'])
    assert [(row['kind'], row['direction'], 'dictionary' in row) for row in by_kind] == \
        [('errand', 'outbound', True), ('note_home', 'inbound', False)]       # the dictionary: outbound only


def test_a_private_word_in_an_outbound_text_adds_its_category_and_never_the_word(judged, listed):
    store = judged.store
    errand(judged, 'pw', '造的：替%s问一句' % WORD)
    assert judged.lane.asked[0]['text'].splitlines()[1] == '程序的提醒：这段文字里有 1 个私人名单上的词（真名）。'
    [asked] = events(store, 'classifier.asked')
    assert asked['dictionary'] == {'private_words': {'person': 1}, 'secrets': 0}       # counts, never the word
    errand(judged, 'pw2')
    assert '程序的提醒' not in judged.lane.asked[1]['text']                       # no match, no line


def test_no_private_words_list_means_the_dictionary_is_unchecked(judged, tmp_path, monkeypatch):
    monkeypatch.setenv('ASUNA_PRIVATE_WORDS', str(tmp_path / 'none.txt'))
    errand(judged, 'nl')
    assert events(judged.store, 'classifier.asked')[0]['dictionary']['private_words'] == 'unchecked'


def test_the_owner_s_own_errand_is_judged_and_recorded_and_never_stopped(judged, listed, monkeypatch):
    """The owner's words: "I don't want the classifier to reject the direct instruction from home to outside." Through
    the stop path landing 7 switches on: someone else's flagged crossing is due a stop; the owner's runs."""
    store = judged.store
    store.config['classifier'] = 'stop'
    stopped = []
    monkeypatch.setattr(classifier, 'stop', lambda store, kind, ref, request=None, **_: stopped.append(kind))
    judged.lane.answers = ['有风险', '有风险']
    errand(judged, 'own', '造的：替%s问一句' % WORD)
    [verdict] = events(store, 'classifier.verdict')
    assert (verdict['verdict'], verdict['owner_asked'], stopped) == ('flagged', True, [])
    note_home(judged, 'own-f')                                               # F's: the path is due to stop it
    assert stopped == ['note_home']


def test_her_review_at_home_lists_a_flagged_verdict_recorded_only(judged):
    from asuna.people import People
    from asuna.records import scenes as scene_records
    store = judged.store
    judged.lane.answers = ['有风险', '有风险']
    note_home(judged, 'rv')
    errand(judged, 'rv-e', '造的：去问一句')
    since, before = guard.review_window(store, '今天')
    items = {item['tried'].get('note', item['tried'].get('errand')): item
             for item in guard.review(store, 'P1', since, before)['items'] if item['kind'] == guard.HARM_KIND}
    g1 = People(store, 'P1').scene_title(scene_records.get(store, 'g1'))
    inbound, outbound = items[NOTE_HOME], items['造的：去问一句']
    assert (inbound['where'], 'from' in inbound, inbound['recorded']) == (g1, False, guard.RECORDED_ONLY)
    assert (outbound['where'], outbound['from']) == (g1, guard.FROM_HOME)          # where it went, from home


def test_a_result_is_judged_by_its_text_only(judged):
    store = judged.store
    task = task_records.get(store, call(judged, ask(store, F, 'rt'), 'delegate', BRIEF)[0]['task'])
    classifier.after_result(store, task, ask(store, F, 'rt2'), {'task_id': task['_id'], 'text': '造的：查到了',
                                                                 'finish_reason': 'stop', 'tool_records': 0})
    assert judged.lane.asked[0]['text'] == classifier.question('result', '造的：查到了')


def test_no_outside_turn_reads_a_verdict_a_policy_or_a_reminder(judged, listed, monkeypatch):
    from test_her_clock import prepared
    store = judged.store
    judged.lane.answers = ['有风险', '有风险']
    note_home(judged, 'scan')
    errand(judged, 'scan-h', '造的：替%s问一句' % WORD)
    shown = json.dumps([role_tools.session_specs(store, 'g1', F), prepared(store, monkeypatch, 'g1')],
                       ensure_ascii=False, default=str)
    policies = [line for way in classifier.POLICIES for line in classifier.policy(way)[0].splitlines() if line]
    assert not [words for words in (guard.HARM_KIND, guard.RECORDED_ONLY, 'flagged', 'off_format', '程序的提醒',
                                     *classifier.WORDS, *policies) if words in shown]
