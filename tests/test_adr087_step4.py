"""ADR-087 step 4 (§4.4, §4.5), on the fixture world in memory: a note from home to a group that cannot be woken now
waits for its next turn there unless she chose `deliver`; a one-shot plan moved in the turn it fired stays fired and
a new plan takes the timing; a note from outside that copies someone's recent line is refused with where the copy is
and whose line it is, never the line; a refusal naming a wrong reference lists the usable ones. dm-a is home (the
owner A's chat); g1 is a group with A and B. The native scheduler is a recording stand-in (test_plan_zone_service)."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from asuna import clock, local_time, notes, places, role_tools, switches, visibility
from asuna.people import People
from asuna.records import plans as plan_records
from asuna.records import scenes as scene_records
from asuna.role_tools import Refused, RoleTools
from asuna.schedule import PRESENCE_PLAN, ScheduleService
from test_plan_zone_service import NativeStandIn

PERSONA = 'P1'
G1 = places.place_id('g1')


class Controller:
    """Records what the service queues; a queued input never runs here."""

    def __init__(self):
        self.settings, self.offers = {'persona': PERSONA}, []

    def offer_internal(self, kind, event_id, scene_id, person, text, **extra):
        self.offers.append((kind, event_id, scene_id, person))


@pytest.fixture
def her(world):
    world.config['chat'] = {**(world.config.get('chat') or {}), 'scene_id': 'dm-a', 'person_id': 'A',
                            'persona': PERSONA}
    world.config['channels']['qq'] = {'account_id': 'acct', 'routes': {
        'r1': {'scene_id': 'g1', 'target': {'type': 'group', 'id': 'G1'},
               'members': {'s-a': {'person_id': 'A'}, 's-b': {'person_id': 'B'}}, 'proactive': {'enabled': True}}}}
    service = ScheduleService.__new__(ScheduleService)
    service.app, service.store, service.lane = SimpleNamespace(config=world.config, store=world), world, NativeStandIn()
    service.controller = Controller()
    coordinator = SimpleNamespace(store=world, scheduler=service, context=SimpleNamespace(),
                                  _update=lambda ep, **changes: world.put('episodes', {**ep, **changes},
                                                                         expected=ep['revision'], stream=ep['_id']))
    return SimpleNamespace(store=world, service=service, tools=RoleTools(coordinator), serial=[0])


def turn(her, tools, *, scene='dm-a', person='A', cls=visibility.OWNER_PRIVATE, kind='external', event=None,
         context=None):
    her.serial[0] += 1
    ep_id = 'ep-087-%d' % her.serial[0]
    her.store.put('episodes', {
        '_id': ep_id, 'scene_id': scene, 'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'persona': PERSONA,
        'person_id': person, 'episode_kind': kind, 'state': 'TURN', 'source_event_id': 'evt-' + ep_id,
        'monologue_refs': [], 'context': context or {}, 'manifest': {'session_class': cls},
        'turn_tools': ['think', *tools], 'turn_thought': True, 'tool_calls': {}}, stream=ep_id)
    if event is not None:
        her.store.put('messages', {'_id': 'in-' + ep_id, 'scene_id': scene, 'direction': 'inbound', 'author': person,
                                   'policy_epoch': 1, 'text': '', 'event': event})
    return ep_id


def call(her, ep_id, name, args, n=0):
    return her.tools.call(ep_id, '%s:%d' % (ep_id, n), name, args)[0]


def refused(her, ep_id, name, args, n=0):
    with pytest.raises(Refused) as caught:
        call(her, ep_id, name, args, n)
    return caught.value


# ── 1. a group that cannot be woken now ─────────────────────────────
def test_a_note_to_a_group_that_cannot_be_woken_goes_next_time_unless_she_chose_deliver(her):
    ep_id = turn(her, ['note'])
    switches.set_switch(her.store, {'_id': ep_id, 'persona': PERSONA, 'scope_key': 'scene:dm-a'}, 'mute',
                        label='一群', scene_id='g1')
    why = places.eligibility(her.store, {'_id': 'g1'}, {}, {'per_day': 9}, clock.now(), None)[1]
    assert why.startswith('你把这个群静音了')

    sent = call(her, ep_id, 'note', {'to': G1, 'text': '周末大家想去哪儿玩？'})
    assert sent['arrives'] == notes.NEXT_TIME_INSTEAD % why
    assert '72 小时' in sent['arrives'] and 'notes_sent_from_program' in sent['arrives']
    row = notes.get(her.store, sent['note'])
    assert (row['to_scene'], row['mode'], row['trust']) == ('g1', notes.NEXT_TIME, notes.TRUSTED)
    assert her.service.controller.offers == [], 'a next_time note opens no turn there'

    chosen = refused(her, ep_id, 'note', {'to': G1, 'text': '周末大家想去哪儿玩？', 'deliver': 'wake'}, 1)
    assert chosen.codes[0] == 'NOTE_VISIT_NOT_NOW' and why in str(chosen)
    assert 'plan' in str(chosen) and 'next_time' in str(chosen)
    assert notes.count_sent(her.store, ep_id) == 1 and her.service.controller.offers == []


def test_a_note_to_a_group_whose_day_is_used_up_goes_next_time_and_a_free_group_is_woken(her):
    her.store.config['persona_model'] = {**(her.store.config.get('persona_model') or {}),
                                         'heartbeat': {'visits': True, 'visits_per_day': 1}}
    her.store.put('plans', {'_id': PRESENCE_PLAN, 'kind': 'presence', 'scene_id': 'dm-a', 'person_id': 'A',
                            'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'status': 'ACTIVE', 'visits': []},
                  stream=PRESENCE_PLAN)            # her heartbeat's plan holds the day's visits
    ep_id = turn(her, ['note'])
    woken = call(her, ep_id, 'note', {'to': G1, 'text': '在一群里问问大家周末去哪儿玩。'})
    assert woken['arrives'] == notes.MODE_WORDS[notes.WAKE]
    assert [(kind, scene) for kind, _, scene, _ in her.service.controller.offers] == [('visit', 'g1')]
    assert [visit['intent'] for visit in plan_records.get(her.store, PRESENCE_PLAN)['visits']] == ['note']
    later = turn(her, ['note'])
    sent = call(her, later, 'note', {'to': G1, 'text': '再问一句：周日下午行不行？'})
    assert sent['arrives'] == notes.NEXT_TIME_INSTEAD % '今天出门的次数用完了'
    assert notes.get(her.store, sent['note'])['mode'] == notes.NEXT_TIME and len(her.service.controller.offers) == 1


# ── 2. a one-shot plan moved in the turn it fired ───────────────────
def fired_turn(her, plan_id='plan-fired', intent='提醒主人喝水'):
    her.store.put('plans', {'_id': plan_id, 'scene_id': 'dm-a', 'person_id': 'A', 'scope_key': 'scene:dm-a',
                            'policy_epoch': 1, 'source_episode_id': 'ep-before', 'intent': intent,
                            'rule': {'at': (clock.now() - timedelta(minutes=1)).isoformat(timespec='minutes'),
                                     'at_utc': True}, 'plan_version': 1, 'status': 'FIRED',
                            'schedule_id': 'native-old', 'created_at': clock.now().isoformat()}, stream=plan_id)
    return turn(her, ['plan'], kind='scheduled', event={'scheduled_plan_id': plan_id})


def test_a_plan_moved_in_the_turn_it_fired_stays_fired_and_a_new_one_takes_the_timing(her):
    ep_id = fired_turn(her)
    before = plan_records.get(her.store, 'plan-fired')
    moved = call(her, ep_id, 'plan', {'do': 'update', 'plan_id': 'plan-fired', 'after_seconds': 3600})
    new = moved['plan_id']
    assert new != 'plan-fired' and moved['note'] == role_tools.PLAN_MOVED_FIRED % ('plan-fired', new)
    made = plan_records.get(her.store, new)
    assert (made['intent'], made['rule'].get('after_seconds')) == ('提醒主人喝水', 3600), 'the old intent, the new timing'
    assert made['status'] == 'ACTIVE' and made['source_episode_id'] == ep_id
    after = plan_records.get(her.store, 'plan-fired')
    assert after['status'] == 'FIRED' and after['revision'] == before['revision'], 'the fired plan is untouched'

    worded = call(her, ep_id, 'plan', {'do': 'update', 'plan_id': 'plan-fired', 'after_seconds': 7200,
                                       'intent': '提醒主人起来走走'}, 1)
    assert plan_records.get(her.store, worded['plan_id'])['intent'] == '提醒主人起来走走'
    assert worded['plan_id'] not in (new, 'plan-fired') and worded['note'] == role_tools.PLAN_MOVED_FIRED % (
        'plan-fired', worded['plan_id'])


# ── 3. a note in someone else's words ───────────────────────────────
def test_a_note_that_copies_someones_recent_line_is_refused_with_where_and_whose_never_the_line(her):
    line = '明天下午三点的群聚取消了大家都知道了别再问'
    her.store.put('messages', {'_id': 'in-line-b', 'scene_id': 'g1', 'direction': 'inbound', 'author': 'B',
                               'policy_epoch': 1, 'scene_seq': 1, 'text': line,
                               'received_at': clock.now().isoformat()})
    ep_id = turn(her, ['note'], scene='g1', person='B', cls=visibility.PUBLIC)
    label = People(her.store, PERSONA).speaker(scene_records.get(her.store, 'g1'), 'B')
    draft = '%s说：%s' % (label, line)                     # naming the source does not make it hers
    no = refused(her, ep_id, 'note', {'to': '家里', 'text': draft})
    assert no.codes[0] == 'NOTE_NOT_OWN_WORDS'
    words = str(no)
    first, last = draft.index(line) + 1, len(draft)
    assert '便条第 %d–%d 字' % (first, last) in words
    assert '写明是谁说的也不行' in words and line[:notes.OWN_WORDS_RUN] not in words
    at = local_time.stamp(her.store.collection('messages').get('in-line-b')['received_at'], local_time.her_zone(her.store))
    assert '字和 %s %s 在这里说的一句一样' % (label, at) in words, 'whose line, by label and time'
    assert notes.count_sent(her.store, ep_id) == 0

    own = call(her, ep_id, 'note', {'to': '家里', 'text': '群里 B 说明天的聚会不办了，他想让家里知道。'}, 1)
    assert notes.get(her.store, own['note'])['trust'] == notes.UNTRUSTED


# ── 4. a wrong reference lists the usable ones ──────────────────────
def test_a_plan_id_that_is_not_hers_lists_the_ones_she_can_use(her):
    listed = [{'_id': 'plan-walk'}, {'_id': 'plan-tea'}]
    ep_id = turn(her, ['plan'], context={'plans_from_program': listed})
    no = refused(her, ep_id, 'plan', {'do': 'update', 'plan_id': 'plan-nope', 'after_seconds': 600})
    assert no.codes[0] == 'PLAN_UNKNOWN'
    assert str(no).endswith('能用的：plan-walk、plan-tea。') and 'plan-nope' in str(no)
    empty = turn(her, ['plan'])
    assert str(refused(her, empty, 'plan', {'do': 'cancel', 'plan_id': 'plan-nope'})).endswith('现在没有能用的。')
