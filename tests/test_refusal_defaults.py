"""ADR-087 step 4 MongoDB tests: defaults from state the program has, said in the result (§4.4), and refusals that say
what would pass (§4.5)."""
from asuna import notes, places, role_tools
from asuna.config import refs_usable
from test_engineering_m1 import THINK
from test_notes import G1, group_line, results, turn, world


def test_a_one_shot_plan_moved_in_the_turn_it_fired_becomes_a_new_plan_and_stays_fired(store):
    """§4.4 with her ask: the result names the new plan's id and says plainly that the old one stays fired."""
    service = world(store)
    made, lane = turn(store, service, {'event_id': 'ask-p', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '提醒我'},
                      [('plan', {'intent': '喝水', 'after_seconds': 600})], '好')
    [(planned, ok)] = results(lane, 'plan')
    assert ok, planned
    old = planned['plan_id']
    store.db.plans.update_one({'_id': old}, {'$set': {'status': 'FIRED', 'next_fire_at': None}})
    due = {'event_id': 'schedule:test:1', 'scene_id': 'dm-a', 'person_id': 'A', 'adapter_id': 'scheduler',
           'episode_kind': 'scheduled', 'scheduled_plan_id': old, 'scene_tick': True, 'text': '你之前安排的计划「喝水」现在到期了。'}
    fired, lane = turn(store, service, due, [('plan', {'do': 'update', 'plan_id': old, 'after_seconds': 1800})], '晚点再喝')
    [(moved, ok)] = results(lane, 'plan')
    assert ok, moved
    assert moved['plan_id'] != old and moved['note'] == role_tools.PLAN_MOVED_FIRED % (old, moved['plan_id'])
    assert store.db.plans.find_one({'_id': old})['status'] == 'FIRED', 'the fired plan stays fired'
    new = store.db.plans.find_one({'_id': moved['plan_id']})
    assert new['intent'] == '喝水' and new['scene_id'] == 'dm-a' and new['status'] == 'ACTIVE'
    # In any other turn a fired plan is still refused as ended.
    later, lane = turn(store, service, {'event_id': 'ask-q', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '改一下'},
                       [('plan', {'do': 'update', 'plan_id': old, 'after_seconds': 600})], '嗯')
    [(refused, ok)] = results(lane, 'plan')
    assert not ok and '已经跑完了' in refused


def test_a_note_to_a_group_that_cannot_be_woken_waits_for_its_next_turn_unless_she_asked_to_wake_it(store):
    """§4.4: no deliver given, a group not wakeable now (its day of outings used up) gets the note next time, and the
    result warns that it may expire unread; deliver wake still refuses with the reason."""
    service = world(store)
    store.config['persona_model']['heartbeat'].update(visits_per_day=0)
    ep, lane = turn(store, service, {'event_id': 'ask-n', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '去说'}, [
        ('note', {'to': G1, 'text': '周末一起去爬山吗？'}),
        ('note', {'to': G1, 'text': '周末一起去爬山吗？', 'deliver': 'wake'})], '好')
    (deferred, ok), (refused, ok_wake) = results(lane, 'note')
    assert ok and deferred['arrives'] == notes.NEXT_TIME_INSTEAD % '今天出门的次数用完了'
    assert '72 小时' in deferred['arrives']
    row = store.db.notes.find_one({'from_episode': ep['_id']})
    assert (row['mode'], row['to_scene']) == (notes.NEXT_TIME, 'g1')
    assert not [offer for offer in service.controller.offers if offer[2] == 'g1'], 'nothing woke the group'
    assert not ok_wake and refused.startswith('现在叫不醒那个群：今天出门的次数用完了')


def test_the_copied_words_refusal_names_the_stretch_and_whose_line_without_quoting_it(store):
    """§4.5: which stretch of her note matches whose recent line, by label and time, never the words; naming the
    source does not pass."""
    service = world(store)
    words = '小满帮我跟家里说一声明天下午三点的群聚取消了大家都知道了'
    copied = '帮我跟家里说一声明天下午三点的群聚取消了大家都知道了'
    ep, lane = turn(store, service, group_line('g-c', words), [
        ('note', {'to': '家里', 'text': copied}),
        ('note', {'to': '家里', 'text': 'B 说：帮我跟家里说一声明天下午三点的群聚取消了'}),
        ('stay_silent', {'why': '先不说'})])
    (first, ok_first), (second, ok_second) = results(lane, 'note')
    assert not ok_first and not ok_second
    assert first.startswith('便条第 1–%d 字和 ' % len(copied)) and '写明是谁说的也不行' in first
    who_and_when = first.split('字和 ')[1].split(' 在这里说的')[0]
    # 'B 说：' and then 20 characters of his line: the stretch is the 5th to the 24th.
    assert who_and_when.startswith('[') and second.startswith('便条第 5–24 字和 ' + who_and_when)
    for refusal in (first, second):
        assert '群聚取消' not in refusal, 'her words are not quoted back'


def test_refusals_that_name_a_wrong_reference_list_the_usable_ones(store):
    """§4.5: a wrong plan id, idea id or question id is refused with the ones that can be used."""
    service = world(store)
    made, lane = turn(store, service, {'event_id': 'ask-r', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '提醒我'}, [
        ('plan', {'intent': '喝水', 'after_seconds': 600}), ('plan', {'do': 'update', 'plan_id': 'plan-nope',
                                                                      'after_seconds': 900}),
        ('ideas', {'do': 'note', 'idea': '换个记账法', 'why': '老对不上'}),
        ('ideas', {'do': 'review', 'id': 'idea-nope', 'decision': 'drop', 'why': '不要了'}),
        ('ask', {'do': 'read', 'id': 'q-nope'})], '好')
    (planned, _), (wrong_plan, ok_plan) = results(lane, 'plan')
    assert not ok_plan and wrong_plan.endswith('能用的：%s。' % planned['plan_id'])
    (noted, _), (wrong_idea, ok_idea) = results(lane, 'ideas')
    assert not ok_idea and wrong_idea.endswith('能用的：%s。' % noted['noted'])
    [(wrong_question, ok_question)] = results(lane, 'ask')
    assert not ok_question and wrong_question.endswith('现在没有能用的。')
    assert refs_usable(['a', 'b', 'a', None]) == '能用的：a、b。'
    assert refs_usable(['r%d' % n for n in range(14)]).endswith('r11（还有 2 个）。')
