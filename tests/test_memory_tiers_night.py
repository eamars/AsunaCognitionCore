"""ADR-062 phase 2, the night: a short list chosen by rule (a gist due, a memory met in several conversations, a
near-duplicate pair, one old thing a week), never keep or drop; the gist keeps her basis; a promotion lands in the
fact store of its subject."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import memory_tiers, memory_pilot
from asuna.context import ContextBuilder
from asuna.documents import DocumentStore
from asuna.memory_tiers import AT_HAND, CARRIED, PUT_AWAY, Tiers, night_list
from test_adr009_p2 import owner
from test_engineering_m1 import event

LONG = '周六早上烤松饼的事。' * 30                                     # well over the gist's listing length
NIGHT = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def on(store, monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    owner(store)
    return store


def append(store, slug, heading, body, **intent):
    docs = DocumentStore(store, 'P1')
    before = docs.read(slug)
    docs.apply(slug, {'op': 'append_section', 'heading': heading, 'reason': 'r', **intent}, body,
               base_revision_id=before[0], author='character', mutation_id=slug + heading)
    after = docs.read(slug)[1]
    Tiers(store, 'P1').written(slug, {'op': 'append_section', **intent}, before[1], after, scene_id='dm-a')
    return after['sections'][-1]['sid']


def rewrite(store, slug, sid, body):
    docs = DocumentStore(store, 'P1')
    before = docs.read(slug)
    docs.apply(slug, {'op': 'replace_section', 'sid': sid, 'reason': 'r'}, body, base_revision_id=before[0],
               author='character', mutation_id='%s:%s:%d' % (slug, sid, len(body)))
    tiers = Tiers(store, 'P1')
    tiers.written(slug, {'op': 'replace_section', 'sid': sid}, before[1], docs.read(slug)[1], before_revision=before[0])
    return tiers


def lapse(store, slug, sid):
    tiers = Tiers(store, 'P1')
    tiers.move(tiers.item(slug, sid), AT_HAND, 'stay')


def test_a_lapsed_long_item_is_listed_for_its_gist_and_the_gist_keeps_the_verbatim_and_its_basis(on):
    sid = append(on, 'persona', '周六', LONG + '\n依据：主人说过三次')
    lapse(on, 'persona', sid)
    [entry] = night_list(on, 'P1', NIGHT)['items']
    assert (entry['what'], entry['ref']) == ('写一句意思', 'doc:persona#' + sid) and '依据' in entry['how']
    tiers = rewrite(on, 'persona', sid, '周六早上烤松饼。')
    assert tiers.notes and '没带依据' in tiers.notes[-1], 'a gist that drops the basis is told so'
    assert not tiers.item('persona', sid)['gist'].get('done') and tiers.item('persona', sid)['place'] == AT_HAND
    assert night_list(on, 'P1', NIGHT + timedelta(days=1))['items'][0]['why'] == memory_tiers.NIGHT_WHY['gist_basis']
    tiers = rewrite(on, 'persona', sid, '周六早上烤松饼。\n依据：主人说过三次')
    row = tiers.item('persona', sid)
    assert row['gist']['done'] and row['place'] == AT_HAND, 'the gist stays at hand'
    from asuna.role_tools import read_sections
    [read], _ = read_sections(on, {'persona': 'P1', 'scene_id': 'dm-a'}, [{'doc': 'persona', 'sid': sid}], 'owner_private')
    assert read['body'].startswith('周六早上烤松饼。') and read['detail'].startswith(LONG[:20]), 'the verbatim behind it'


def test_a_gist_passed_over_on_two_nights_goes_put_away_as_it_is(on):
    sid = append(on, 'persona', '周六', LONG)
    lapse(on, 'persona', sid)
    for night in range(2):
        assert night_list(on, 'P1', NIGHT + timedelta(days=night))['items'][0]['what'] == '写一句意思'
    assert night_list(on, 'P1', NIGHT + timedelta(days=2)) is None
    assert Tiers(on, 'P1').item('persona', sid)['place'] == PUT_AWAY


def test_a_memory_met_in_two_conversations_is_offered_its_meaning_once_a_week(on):
    sid = append(on, 'work_log', '那天', '那天学会了做蛋饼', **{'from': '别人说的'})
    tiers = Tiers(on, 'P1')
    tiers.surfaced([('work_log', sid)], 'dm-a')
    tiers.surfaced([('work_log', sid)], 'g1')
    [entry] = night_list(on, 'P1', NIGHT)['items']
    assert entry['what'] == '几处都提到' and '进 core' in entry['how'] and '记成事实' in entry['how']
    assert not any(word in entry['how'] for word in ('保留', '删除', '带着')), 'no keep or drop'
    assert night_list(on, 'P1', NIGHT + timedelta(days=1)) is None, 'not again within the week'


def test_her_own_judgment_is_not_offered_as_a_fact_until_someone_confirms_it(on):
    """Her rule (2026-10-13): a fact needs an author who can correct it; she does not sign for herself."""
    sid = append(on, 'work_log', '先不放开', '这个群先不放开', **{'from': '我自己的判断'})
    tiers = Tiers(on, 'P1')
    tiers.surfaced([('work_log', sid)], 'dm-a')
    tiers.surfaced([('work_log', sid)], 'g1')
    [entry] = night_list(on, 'P1', NIGHT)['items']
    assert entry['what'] == '几处都提到' and '记成事实' not in entry['how']
    tiers.rows.update_one({'_id': tiers.item('work_log', sid)['_id']}, {'$set': {'confirmed': NIGHT.isoformat()}})
    tiers.rows.delete_many({'row': 'offer'})
    assert '记成事实' in night_list(on, 'P1', NIGHT)['items'][0]['how'], 'confirmed from elsewhere, it may be'


def test_a_judgment_is_confirmed_only_by_the_same_from_someone_else(on):
    """Owner's call (2026-10-13): a near-duplicate from another person or conversation confirms; one she wrote in the
    same conversation herself does not."""
    tiers = Tiers(on, 'P1')
    mine = append(on, 'work_log', '判断一', '这个群先不放开', **{'from': '我自己的判断'})
    again = append(on, 'work_log', '判断二', '这个群先别放开', **{'from': '我自己的判断'})
    told = append(on, 'work_log', '别人说', '群主也说先别放开', **{'from': '别人说的'})
    shadow = on.db[memory_pilot.COLLECTION]
    for key, sid in (('s1', mine), ('s2', again), ('s3', told)):
        shadow.insert_one({'_id': key, 'row': 'item', 'status': 'active', 'doc': 'work_log', 'sid': sid})
    shadow.insert_one({'_id': 'pair:a', 'row': 'pair', 'store': 'journal', 'items': ['s1', 's2'], 'score': 0.97})
    night_list(on, 'P1', NIGHT)
    assert not tiers.item('work_log', mine).get('confirmed'), 'her own echo in the same conversation is not someone else'
    shadow.insert_one({'_id': 'pair:b', 'row': 'pair', 'store': 'journal', 'items': ['s1', 's3'], 'score': 0.97})
    night_list(on, 'P1', NIGHT + timedelta(days=1))
    assert tiers.item('work_log', mine).get('confirmed'), 'the same from someone else confirms it'


def test_a_write_may_not_sign_her_judgment_as_a_fact_but_a_checked_rewrite_may(on):
    from asuna.coordinator import Coordinator
    from asuna.lanes import FakeLane, FakeTurn
    from test_adr009_p2 import THINK
    sid = append(on, 'persona', '先不放开', '这个群先不放开', **{'from': '我自己的判断'})
    signed = {'doc': 'persona', 'op': 'set_tags', 'sid': sid, 'nature': '事实', 'reason': '我觉得是事实'}
    relabel = {'doc': 'persona', 'op': 'set_tags', 'sid': sid, 'from': '查过的', 'reason': '查过了'}
    both = {'doc': 'persona', 'op': 'append_section', 'heading': '新的', 'nature': '事实', 'from': '我自己的判断',
            'body': '新判断', 'reason': 'r'}
    checked = {'doc': 'persona', 'op': 'replace_section', 'sid': sid, 'from': '查过的', 'reason': '查过了',
               'body': '这个群先不放开\n依据：10/12 群主在群公告里写了'}
    lane = FakeLane(on, [FakeTurn([THINK, ('write_document', signed), ('write_document', relabel),
                                   ('write_document', both), ('write_document', checked)], '好。')])
    ep = Coordinator(on, lane).ingest(event('e-sign'))
    calls = sorted(ep['tool_calls'].values(), key=lambda call: call['seq'])[1:]
    assert [memory_tiers.JUDGMENT_NOT_FACT in (call.get('refused') or '') for call in calls] == [True, True, True, False]
    row = Tiers(on, 'P1').item('persona', sid)
    assert (row['from'], row['nature']) == ('查过的', '事实'), 'checked, with its basis: a fact'


def test_near_duplicates_in_a_fact_store_must_merge_and_meeting_one_elsewhere_is_memorable(on):
    a = append(on, 'persona', '松饼一', '周六烤松饼')
    b = append(on, 'persona', '松饼二', '周六要烤松饼')
    tiers = Tiers(on, 'P1')
    tiers.rows.update_one({'_id': tiers.item('persona', b)['_id']}, {'$set': {'scene_id': 'g1'}})
    shadow = on.db[memory_pilot.COLLECTION]
    for key, sid in (('sa', a), ('sb', b)):
        shadow.insert_one({'_id': key, 'row': 'item', 'status': 'active', 'doc': 'persona', 'sid': sid})
    shadow.insert_one({'_id': 'pair:1', 'row': 'pair', 'store': 'persona', 'items': ['sa', 'sb'], 'score': 0.97})
    [entry] = night_list(on, 'P1', NIGHT)['items']
    assert entry['what'] == '合并' and '要合并' in entry['how'] and entry['with']['ref'] == 'doc:persona#' + b
    assert tiers.item('persona', a)['last_moment'] == 'duplicate_elsewhere'


def test_one_put_away_thing_a_week_comes_back_to_look_at_and_the_list_holds_five_at_most(on):
    tiers = Tiers(on, 'P1')
    for n in range(7):
        sid = append(on, 'persona', '长的 %d' % n, LONG + str(n))
        lapse(on, 'persona', sid)
    old = append(on, 'work_log', '旧事', '很早以前的一件事')
    row = tiers.item('work_log', old)
    tiers.rows.update_one({'_id': row['_id']}, {'$set': {'place': PUT_AWAY, 'uses': 2}})
    listed = night_list(on, 'P1', NIGHT)['items']
    assert len(listed) == memory_tiers.NIGHT_ITEMS and all(entry['what'] == '写一句意思' for entry in listed)
    tiers.rows.delete_many({'row': 'item', 'doc': 'persona'})
    assert night_list(on, 'P1', NIGHT)['items'][0]['what'] == '回头看'
    assert night_list(on, 'P1', NIGHT + timedelta(days=1)) is None, 'once a week'


def test_the_settlement_turn_has_the_night_list_instead_of_the_notes_review(on):
    sid = append(on, 'persona', '周六', LONG)
    lapse(on, 'persona', sid)
    _, context, _ = ContextBuilder(on).prepare({**event('settlement:1'), 'episode_kind': 'settlement'}, 'P1')
    assert context['night_list_from_program']['items'][0]['ref'] == 'doc:persona#' + sid
    assert 'notes_review_from_program' not in context


def test_a_promotion_about_herself_lands_in_core_as_a_carried_fact(on):
    from asuna.role_tools import promote
    on.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
                                  'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2}}}
    for i in (1, 2):
        on.db.episodes.insert_one({'_id': 'ep-%d' % i, 'schema_version': 1, 'scene_id': 'dm-a', 'episode_kind': 'external',
                                   'source_event_id': 'in-%d' % i})
        on.db.audit_events.insert_one({'_id': 'ctx-%d' % i, 'schema_version': 1, 'type': 'context.prepared',
                                       'stream_id': 'ep-%d' % i, 'occurred_at': '2026-10-0%dT12:00:00+00:00' % i})
    ep = {'_id': 'ep-settle', 'persona': 'P1', 'episode_kind': 'settlement', 'tool_calls': {}, 'scene_id': 'dm-a'}
    item = {'fact': '我做事先查再说', 'appraisal': '这是我', 'signal': '会一直这样', 'why': '两天里两次都这样',
            'source_ids': ['ep-1', 'ep-2'], 'about': 'self'}
    result = promote(on, ep, item, key='k1')
    assert result['landed'].startswith('doc:core#')
    sid = result['landed'].split('#')[1]
    row = Tiers(on, 'P1').item('core', sid)
    assert (row['place'], row['nature'], row['stay_days']) == (CARRIED, '事实', 56)
    body = DocumentStore(on, 'P1').read('core')[1]['sections'][-1]['body']
    assert body == '我做事先查再说\n依据：两天里两次都这样', 'a claim with its basis'
