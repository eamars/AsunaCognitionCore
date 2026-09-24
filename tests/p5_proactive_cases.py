"""ADR-005 P5 离线用例：没被@的那一次要不要醒，用假集合真算一遍。

python3 tools/p5_offline_check.py 直接跑，不需要 Mongo／pytest／模型。
假掉的只有 import 期的第三方和数据库本身（沿用 P2 那份假集合），
proactive.observe／decide／consider、channels.group_context、ContextBuilder.prepare、
Chat 的挂钩方法都是仓库里那份真代码在跑。
每条用例都对着 ACCEPTANCE §Q7 的一条确定性检查，或 DELIVERY_PLAN §P5 的一条边界。
"""
import contextlib
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from queue import Queue
from types import ModuleType, SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import p2_summary_loop_cases as base                      # noqa: E402  装好第三方假件＋假集合


def _stub_dsh():
    '''只假掉 DSH 原生驱动：本文件不跑模型，只要 chat 模块能导入。'''
    try:
        import deepseek_harness                             # noqa: F401
        return False
    except Exception:
        module = ModuleType('deepseek_harness')
        module.DeepSeekHarness = object
        module.__getattr__ = lambda name: object
        sys.modules['deepseek_harness'] = module
        return True


STUBBED_DSH = _stub_dsh()

from asuna import proactive                                # noqa: E402
from asuna.channels import group_context                   # noqa: E402
from asuna.chat import Chat                                # noqa: E402
from asuna.context import ContextBuilder                   # noqa: E402

GROUP = base.GROUP
GROUP_SCOPE = base.GROUP_SCOPE
PERSON, PERSON_B, EPOCH, T0 = base.PERSON, base.PERSON_B, base.EPOCH, base.T0
BOT = '2910137276'
EVIDENCE = base.FakeEvidence
_iso = base._iso

ENABLED = {'enabled': True, 'utc_offset_minutes': 480, 'quiet_hours': [['23:00', '08:00']]}
NIGHT = datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc).timestamp()   # 本地 UTC+8 → 凌晨 4 点


def config_for(proactive_block=ENABLED, scene_id=GROUP):
    route = {'scene_id': scene_id, 'target': {'type': 'group', 'id': '10001'}, 'members': {}}
    if proactive_block is not None:
        route['proactive'] = proactive_block
    return {'channels': {'qq': {'account_id': BOT, 'token': 't' * 24, 'routes': {'g1': route}}}}


def data_for(messages, scene_id=GROUP, kind='group'):
    """复用 P2 那份脚手架，只多绑一条通道路由（主动模式是按场景配置的，不是全局开关）。"""
    sequence = max([row.get('scene_seq') or 0 for row in messages] or [0])
    data = base._scaffold(scene_id, kind, [PERSON, PERSON_B], messages, 0, sequence)
    scene = data['scenes'][0]
    scene['channel_id'] = 'qq'
    data['scenes'] = [scene]
    return data


def scene_of(store):
    return store.db.scenes.find_one({'_id': GROUP})


@contextlib.contextmanager
def frozen(moment):
    """挂钩里的钟点走 proactive.now_ts 这一个缝：检查里冻住它，不谎称真等到那个时刻。"""
    real = proactive.now_ts
    proactive.now_ts = lambda: moment
    try:
        yield
    finally:
        proactive.now_ts = real


def seed_real(store, data=None):
    '''把同一批夹具灌进真库（操作员那侧的定向检查用）。'''
    for name, docs in (data or data_for(calm_rows())).items():
        for doc in docs:
            store.put(name, doc, stream='p5')


def event_of(row):
    """按生产里入站事件的形状拼一份：通道信息＋场景＋那条旁听行的 group_context。"""
    return {'event_id': row['platform_event_id'], 'scene_id': GROUP, 'person_id': row['author'],
            'text': row['text'], 'channel': {'id': 'qq', 'account_id': BOT, 'sender_id': '10001',
                                             'target': {'type': 'group', 'id': '10001'}},
            'group_context': row['event']['group_context']}


def g_in(scene, seq, author, text, at, topic='topic-1', wake=None, reply_message_id=None,
         proactive_record=None, **extra):
    group = {'wake_reason': wake, 'topic_id': topic, 'topic_via': 'new', 'reply_to': None,
             'reply_message_id': reply_message_id, 'mentioned_account_ids': []}
    row = base._in(scene, seq, author, text, at, {'group_context': group}, **extra)
    if proactive_record is not None:
        row['proactive'] = proactive_record
    return row


def my_speech(scene, seq, text, at, topic='topic-1'):
    """我上次主动插的一句话：出站行 + 它由哪条入站叫醒的（origin 带 proactive wake_reason）。"""
    ep = 'ep-say-%d' % seq
    origin = base._in(scene, seq - 1, PERSON_B, '他们还在聊标签怎么打', at - 5,
                      {'group_context': {'wake_reason': proactive.WAKE_REASON, 'topic_id': topic,
                                         'topic_via': 'proactive', 'reply_to': None,
                                         'reply_message_id': None, 'mentioned_account_ids': []}},
                      proactive={'wake': True})
    origin['_id'] = 'in-' + ep
    origin['scene_seq'] = seq - 1
    speech = base._out(scene, seq, text, at, episode_id=ep, platform_message_id='msg-out-%d' % seq)
    return [origin, speech]


def calm_rows(trigger_text='给新买的那台设备重新做个标签吧', topic='topic-1'):
    """一个不像在抢着说的群：三条间隔一分钟以上，最后一条没@她。"""
    return [g_in(GROUP, 11, PERSON, '月湾盒放玄关第二格', T0 - 300, topic='topic-0'),
            g_in(GROUP, 12, PERSON_B, '行，我去搬', T0 - 240, topic='topic-0'),
            g_in(GROUP, 13, PERSON, trigger_text, T0, topic=topic)]


def run(store, row, moment=T0 + 60, config=None, can_run=True, block=ENABLED):
    evidence = EVIDENCE()
    decision, updated = proactive.consider(store, evidence, config or config_for(block),
                                           scene_of(store), row, now_ts=moment, can_run=can_run)
    return decision, updated, evidence


# ── Q7①：有参与机会，而不是只有@才能跑 ────────────────────
def q1_unprompted_message_can_get_a_chance():
    store = base.bind_store(data_for(calm_rows()))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, updated, evidence = run(store, trigger)
    assert decision['fire'], decision
    assert 'unprompted_group_message' in decision['signals'], decision
    assert updated['processing_outcome'] == proactive.OUTCOME_WAKE, updated['processing_outcome']
    assert updated['event']['group_context']['wake_reason'] == proactive.WAKE_REASON
    assert any(row['type'] == 'proactive.wake' for row in evidence.rows), evidence.rows
    # 反证：旧口径「没有 wake_reason 就到此为止」在这个现场结论相反。
    assert not trigger['event']['group_context'].get('wake_reason'), \
        '旧口径根本不会评估这句，新口径会问一次'
    return '没@她的一条群消息也能换来一次参与机会，决定写进那一行并进证据'


def q1_topic_line_reaches_the_role_context():
    store = base.bind_store(data_for(calm_rows()))
    current = {'event_id': 'evt-next', 'scene_id': GROUP, 'person_id': PERSON_B, 'text': '那我搬两个',
               'group_context': {'wake_reason': proactive.WAKE_REASON, 'topic_id': 'topic-1',
                                 'topic_via': 'proactive', 'reply_to': None,
                                 'reply_message_id': 'in-%s-13' % GROUP, 'mentioned_account_ids': []}}
    base.add_row(store, 'messages', {'_id': 'in-ep-proactive', 'scene_id': GROUP,
                                     'scope_key': GROUP_SCOPE, 'policy_epoch': EPOCH,
                                     'scene_seq': 14, 'direction': 'inbound', 'author': PERSON_B,
                                     'text': '那我搬两个', 'platform_event_id': 'evt-next',
                                     'occurred_at': _iso(T0 + 30), 'received_at': _iso(T0 + 30),
                                     'revision': 1,
                                     'event': {'group_context': current['group_context']}})
    _system, context, _manifest = ContextBuilder(store, retrieval=None).prepare(current)
    continuity = context['group_continuity_from_program']
    ids = {row['_id'] for row in continuity['related_messages']}
    assert {'in-%s-13' % GROUP, 'in-ep-proactive'} <= ids, ids      # 旁听行也在话题线里
    assert 'proactive_from_program' in continuity, sorted(continuity)
    assert '沉默不需要理由' in continuity['proactive_from_program']
    plain = {**current, 'event_id': 'evt-plain',
             'group_context': {**current['group_context'], 'wake_reason': 'mentioned_account'}}
    base.add_row(store, 'messages', {'_id': 'in-ep-plain', 'scene_id': GROUP,
                                     'scope_key': GROUP_SCOPE, 'policy_epoch': EPOCH,
                                     'scene_seq': 15, 'direction': 'inbound', 'author': PERSON_B,
                                     'text': '那我搬两个', 'platform_event_id': 'evt-plain',
                                     'occurred_at': _iso(T0 + 31), 'received_at': _iso(T0 + 31),
                                     'revision': 1,
                                     'event': {'group_context': plain['group_context']}})
    _system, second, _m = ContextBuilder(store, retrieval=None).prepare(plain)
    assert 'proactive_from_program' not in second['group_continuity_from_program'], '被@了就不是插话'
    return '醒来看见的是整条话题线（含旁听行），外加一句不催她开口的说明'


# ── Q7②：冷却与安静时段只压未请求的插话 ───────────────────
def q2_quiet_hours_hold_unprompted_only():
    store = base.bind_store(data_for(calm_rows()))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger, moment=NIGHT + 60)
    assert not decision['fire'] and 'quiet_hours' in decision['holds'], decision
    assert decision['local_minutes'] == 4 * 60 + 1, decision['local_minutes']  # 本地凌晨 4:01
    store = base.bind_store(data_for(calm_rows('传感器故障了，谁看一下')))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger, moment=NIGHT + 60)
    assert decision['fire'] and 'urgent_cue' in decision['signals'], decision
    return '凌晨默认不评估；带紧急线索词只放宽这一道闸，醒了还是可以自己选沉默'


def q2_cooldown_does_not_touch_direct_questions():
    """冷却只作用在旁听行上：被@的那条走原唤醒路径，主动代码一行都不碰。"""
    store = base.bind_store(data_for(calm_rows()))
    row = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    stub = stub_for(store, config_for(ENABLED))
    Chat._proactive_consider(stub, event_of(row), 'grp-1-13', {'state': 'COMMITTED'})
    assert not stub.pending.put_rows, '直接提问那轮不该被主动逻辑插手'
    assert store.db.messages.find_one({'_id': row['_id']})['revision'] == row['revision']
    return '已唤醒的那轮（直接提问、已参与的接话）不经过分寸判断，行上一个字没改'


def q2_foreground_task_and_queued_inputs_win():
    store = base.bind_store(data_for(calm_rows()))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger, can_run=False)
    assert 'foreground_busy' in decision['holds'] and not decision['fire'], decision
    stub = stub_for(store, config_for(ENABLED), queues={GROUP: ['queued-input']})
    assert not Chat._proactive_open(stub, GROUP), '本场景队列里排着别人 → 机会作废'
    busy = stub_for(store, config_for(ENABLED))
    busy.active_task = 'task-1'
    assert not Chat._proactive_open(busy, GROUP), '前台行动在跑 → 机会作废'
    return '前台行动与已排队输入永远优先，主动机会就地作废不排队等'


# ── Q7③：节奏闸门——快速一问一答时不插话 ─────────────────
def rhythm_gate_blocks_fast_exchanges():
    fast = [g_in(GROUP, 21 + index, PERSON if index % 2 == 0 else PERSON_B,
                 '第 %d 条：标签就这么打' % index, T0 + index * 5) for index in range(6)]
    store = base.bind_store(data_for(fast))
    trigger = store.db.messages.find_one({'scene_id': GROUP}, sort=[('scene_seq', -1)])
    decision, _updated, _e = run(store, trigger, moment=T0 + 30)
    assert 'dense_exchange' in decision['holds'], decision
    assert decision['dense_median'] < decision['quiet_after'], decision
    slow = [g_in(GROUP, 21 + index, PERSON if index % 2 == 0 else PERSON_B,
                 '第 %d 条：标签就这么打' % index, T0 + index * 120) for index in range(6)]
    store = base.bind_store(data_for(slow))
    trigger = store.db.messages.find_one({'scene_id': GROUP}, sort=[('scene_seq', -1)])
    decision, _updated, _e = run(store, trigger, moment=T0 + 700)
    assert decision['fire'] and not decision['dense'], decision
    return '5 秒一条时闸门关掉机会，两分钟一条时放行——用的是 P2 那条场景自己的停顿线'


# ── Q7④：没有新消息不重开旧话题（结构上就没有定时器） ───────
def no_timer_reopens_nothing():
    source = open(os.path.join(ROOT, 'src', 'asuna', 'proactive.py'), encoding='utf-8').read()
    for forbidden in ('Thread(', 'Timer', 'time.sleep', 'sched'):
        assert forbidden not in source, '主动评估里不该出现定时器／线程：%s' % forbidden
    store = base.bind_store(data_for(calm_rows()))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    assert run(store, trigger)[0]['fire']
    scene = scene_of(store)
    profile = proactive.observe(store, scene, now_ts=T0 + 86400, trigger=trigger,
                                limits=proactive.route_settings(config_for(ENABLED), scene))
    assert profile['since_wake'] is None and profile['my_proactive_rows'] == 0, profile
    return '评估只由新入站行触发；一天没消息也不会有第二次询问，代码里没有任何定时器'


# ── Q7⑤：一次没被回应的主动插话不跟着催问 ───────────────
def one_unanswered_attempt_per_topic():
    block = dict(ENABLED, min_interval_seconds=60, probe_interval_seconds=30)
    messages = calm_rows() + my_speech(GROUP, 20, '标签我可以自己写', T0 - 600, topic='topic-1')
    store = base.bind_store(data_for(messages))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger, moment=T0 + 60, block=block)
    assert 'topic_attempt_unanswered' in decision['holds'], decision
    assert decision['topic_attempts'] == 1 and decision['topic_responded'] is False, decision
    replied = g_in(GROUP, 21, PERSON_B, '那交给你', T0 + 20, topic='topic-1',
                  wake='reply_to_character', reply_message_id='%s:speak:20' % GROUP)
    base.add_row(store, 'messages', replied)
    decision, _updated, _e = run(store, trigger, moment=T0 + 60, block=block)
    assert decision['fire'] and 'topic_was_replied' in decision['signals'], decision
    return '同一话题没人接就只试一次；被接了才允许再试，不催问'


def scene_cooldown_and_hourly_cap():
    messages = calm_rows() + my_speech(GROUP, 20, '标签我可以自己写', T0 + 30, topic='topic-9') \
        + my_speech(GROUP, 30, '这个我熟', T0 - 1800, topic='topic-8') \
        + my_speech(GROUP, 40, '我来贴', T0 - 3500, topic='topic-7')
    store = base.bind_store(data_for(messages))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger)
    assert {'scene_cooldown', 'hourly_cap'} <= set(decision['holds']), decision
    assert decision['utterances_last_hour'] == 3, decision
    assert decision['since_utterance'] == 30.0, decision                          # 距上次开口 30 秒
    return '场景级最小间隔与每小时上限都从已送达的主动出站行倒推，不另存计数器'


def probe_budget_counts_the_chance_not_the_speech():
    asked = g_in(GROUP, 13, PERSON, '给新买的那台设备重新做个标签吧', T0,
                 proactive_record={'wake': True})
    head = calm_rows()
    store = base.bind_store(data_for([head[0], head[1], asked]))
    fresh = g_in(GROUP, 14, PERSON_B, '标签上写什么好', T0 + 60, topic='topic-2')
    base.add_row(store, 'messages', fresh)
    decision, _updated, _e = run(store, fresh)
    assert 'probe_cooldown' in decision['holds'], decision      # 刚问过，她选了沉默，也不立刻再问
    store = base.bind_store(data_for([head[0], head[1], asked]))
    decision, _updated, _e = run(store, asked)                  # 那次问过的那一行自己再来一次
    assert 'probe_cooldown' not in decision['holds'], decision
    return '机会预算按“上次问她”算，不按“她说了没”算；也不把自己那次算进冷却'


# ── Q7⑥：一条消息不清除另一人的请求 ─────────────────────
def one_message_does_not_clear_another_request():
    block = dict(ENABLED, min_interval_seconds=60, probe_interval_seconds=30)
    messages = calm_rows(topic='topic-1') + my_speech(GROUP, 20, '标签我可以自己写', T0 - 600,
                                                     topic='topic-1')
    store = base.bind_store(data_for(messages))
    before = dict(store.db.messages.find_one({'_id': '%s:speak:20' % GROUP}).get('event', {}))
    other = g_in(GROUP, 21, PERSON_B, '相机那事还没定镜头', T0 + 10, topic='topic-2')
    base.add_row(store, 'messages', other)
    decision, _updated, _e = run(store, other, moment=T0 + 60, block=block)
    assert decision['fire'] and decision['topic_attempts'] == 0, decision
    again = store.db.messages.find_one({'_id': '%s:speak:20' % GROUP})
    assert again.get('event', {}) == before and again.get('proactive') is None, \
        'B 那句不该动 A 那条话题上的记录'
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger, moment=T0 + 61, block=block)
    assert 'topic_attempt_unanswered' in decision['holds'], decision
    return '状态按话题分开：别人的一句新话不会抹掉另一条话题上“已经试过没被接”'


# ── 挂钩本身：写什么、什么时候不写 ───────────────────────
def unenrolled_scene_is_left_alone():
    store = base.bind_store(data_for(calm_rows()))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, updated, evidence = run(store, trigger, block=None)
    assert not decision['fire'] and decision['holds'] == ['not_enrolled'], decision
    assert updated is None
    row = store.db.messages.find_one({'_id': trigger['_id']})
    assert 'proactive' not in row and row.get('processing_outcome') is None, row
    assert not evidence.rows
    return '没开主动模式的场景一切照旧：旁听行不被改写，也不产生任何证据'


def row_without_time_is_not_guessed():
    messages = calm_rows()
    messages[2].pop('occurred_at')
    messages[2].pop('received_at')
    store = base.bind_store(data_for(messages))
    trigger = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    decision, _updated, _e = run(store, trigger)
    assert 'trigger_without_time' in decision['holds'], decision
    return '触发行读不到时间就照实拦下，不拿写入时间或序号冒充发生时间'


def hook_enqueues_only_after_overheard_row():
    store = base.bind_store(data_for(calm_rows()))
    row = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    stub = stub_for(store, config_for(ENABLED))
    with frozen(T0 + 60):
        Chat._proactive_consider(stub, event_of(row), 'grp-1-13', {'state': 'RECEIVED_NO_WAKE'})
    assert len(stub.pending.put_rows) == 1, stub.pending.put_rows
    queued_event, episode = stub.pending.put_rows[0]
    assert episode == 'grp-1-13' and 'grp-1-13' in stub.enqueued
    assert queued_event['group_context']['wake_reason'] == proactive.WAKE_REASON
    stored = store.db.messages.find_one({'_id': row['_id']})
    assert stored['processing_outcome'] == proactive.OUTCOME_WAKE, stored['processing_outcome']
    assert stored['proactive']['wake'] is True and stored['proactive']['holds'] == []
    return '旁听行落库后才评估，放行就把同一条事件按主动回合重新入队（不新增一行原文）'


def recheck_holds_when_the_gate_closed():
    """入队时那句插话还没送达，真跑之前已经送达且没人接 → 再核一次，不建 episode、不调模型。"""
    block = dict(ENABLED, min_interval_seconds=60, probe_interval_seconds=30)
    lines = calm_rows(topic='topic-2') + my_speech(GROUP, 20, '标签我可以自己写', T0 - 90,
                                                   topic='topic-2')
    speech = lines[-1]
    speech['delivery_state'] = 'PENDING'          # 入队那一刻：宿主还不知道自己已经说过这句
    store = base.bind_store(data_for(lines))
    row = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    stub = stub_for(store, config_for(block))
    event = event_of(row)
    event['group_context'] = {**event['group_context'], 'wake_reason': proactive.WAKE_REASON}
    with frozen(T0 + 60):
        assert Chat._proactive_stale(stub, event, 'grp-1-13') is False, '那句还没送达，不该拦'
        current = store.db.messages.find_one({'_id': speech['_id']})
        store.put('messages', {**current, 'delivery_state': 'DELIVERED'},
                  expected=current['revision'], stream='p5')   # 送达回执到了
        assert Chat._proactive_stale(stub, event, 'grp-1-13') is True
    stored = store.db.messages.find_one({'_id': row['_id']})
    assert stored['processing_outcome'] == proactive.OUTCOME_HOLD, stored['processing_outcome']
    assert stored['proactive']['wake'] is False, stored['proactive']
    assert 'topic_attempt_unanswered' in stored['proactive']['recheck_hold'], stored['proactive']
    assert any(item['type'] == 'proactive.hold' and item['payload'].get('stage') == 'recheck'
               for item in stub.app.evidence.rows), stub.app.evidence.rows
    return '真跑之前再核一次闸门：拦下来就不建 episode、不调模型，并记下是哪条闸'


# ── 话题派生：channels.group_context 给每一行都认线 ────────
def topic_is_derived_for_every_group_row():
    recent = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    parent_overheard = {'_id': 'in-parent', 'scene_id': GROUP, 'policy_epoch': EPOCH,
                        'direction': 'inbound', 'author': PERSON, 'received_at': recent,
                        'event': {'channel': {'platform_event_id': 'evt-parent'},
                                  'group_context': {'wake_reason': None, 'topic_id': 'topic-A',
                                                    'topic_via': 'new'}}}
    parent_woken = {'_id': 'in-woken', 'scene_id': GROUP, 'policy_epoch': EPOCH,
                    'direction': 'inbound', 'author': PERSON, 'received_at': recent,
                    'event': {'channel': {'platform_event_id': 'evt-woken'},
                              'group_context': {'wake_reason': 'mentioned_account',
                                                'topic_id': 'topic-B', 'topic_via': 'mentioned'}}}
    store = SimpleNamespace(db=base.FakeDB({
        'scenes': [{'_id': GROUP, 'kind': 'group', 'policy_epoch': EPOCH, 'members': [PERSON]}],
        'messages': [parent_overheard, parent_woken]}))
    route = {'scene_id': GROUP}
    over = group_context(store, route, {'account_id': BOT, 'mentioned_account_ids': [],
                                        'reply_to': 'evt-parent'}, 'evt-new')
    assert over['wake_reason'] is None and over['topic_id'] == 'topic-A', over
    assert over['topic_via'] == 'reply_chain', over        # 认得出是哪条线，但不因此唤醒
    woken = group_context(store, route, {'account_id': BOT, 'mentioned_account_ids': [],
                                         'reply_to': 'evt-woken'}, 'evt-new2')
    assert woken['wake_reason'] == 'reply_in_active_topic', woken   # 旧唤醒口径不变
    assert woken['topic_id'] == 'topic-B', woken
    fresh = group_context(store, route, {'account_id': BOT, 'mentioned_account_ids': []}, 'evt-3')
    assert fresh['wake_reason'] is None and fresh['topic_id'] == 'evt-3', fresh
    assert fresh['topic_via'] == 'new', fresh
    assert parent_overheard['event']['group_context']['wake_reason'] is None
    return '每一条群消息都带得上话题号（旁听行也是），唤醒口径一个字没改'


# ── 假宿主外壳：只给真方法需要的东西 ────────────────────
def proactive_errors_do_not_break_the_round():
    """分寸判断是可选腿：它自己读不动只记证据，不许把一轮改成失败、也不许对用户报错。"""
    store = base.bind_store(data_for(calm_rows()))
    row = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    stub = stub_for(store, config_for(ENABLED))
    event = event_of(row)
    woken = {**event, 'group_context': {**event['group_context'],
                                        'wake_reason': proactive.WAKE_REASON}}
    real = proactive.observe
    proactive.observe = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('假库读不动'))
    try:
        Chat._proactive_consider(stub, event, 'grp-1-13', {'state': 'RECEIVED_NO_WAKE'})
        held = Chat._proactive_stale(stub, woken, 'grp-1-13')
    finally:
        proactive.observe = real
    assert held is True, '再核读不动就当拦下，宁可少说一次'
    assert not stub.pending.put_rows, '炸了就不该把事件塞回队列'
    kinds = [item['type'] for item in stub.app.evidence.rows]
    assert 'proactive.consider_error' in kinds and 'proactive.recheck_error' in kinds, kinds
    assert store.db.messages.find_one({'_id': row['_id']})['revision'] == row['revision'], \
        '旁听行不该被半写的判断改到一半'
    return '主动这条腿炸了也只留证据：不重排队列、不改那一行、不把一轮变成用户看得见的报错'


def recheck_never_touches_a_woken_reply():
    """再核只针对她自己插的那句：被@的那条就算深夜、就算没开主动模式，也不许被它拦掉。"""
    store = base.bind_store(data_for(calm_rows()))
    row = store.db.messages.find_one({'_id': 'in-%s-13' % GROUP})
    mentioned = {**event_of(row), 'group_context': {**row['event']['group_context'],
                                                    'wake_reason': 'mentioned_account'}}
    for block in (ENABLED, None):
        stub = stub_for(store, config_for(block))
        with frozen(NIGHT + 60):               # 凌晨＋安静时段，闸门全都会拦
            assert Chat._proactive_stale(stub, mentioned, 'grp-1-13') is False, block
        assert store.db.messages.find_one({'_id': row['_id']})['revision'] == row['revision']
    return '再核认得清这是接话还是插话：接话照跑，一个字段都不多写'


class FakeFair:
    def __init__(self, queues=None):
        self.queues = dict(queues or {})


class FakePending:
    def __init__(self, queues=None):
        self.mutex = threading.Lock()
        self.queue = FakeFair(queues)
        self.put_rows = []

    def put(self, item):
        self.put_rows.append(item)


class StubChat:
    """只借 Chat 的主动方法本体（含出错包一层的那道）；宿主外壳给最小假件。"""

    _proactive_open = Chat._proactive_open
    _proactive_group_row = Chat._proactive_group_row
    _proactive_consider = Chat._proactive_consider
    _proactive_consider_inner = Chat._proactive_consider_inner
    _proactive_stale = Chat._proactive_stale
    _proactive_stale_inner = Chat._proactive_stale_inner

    def __init__(self, store, config, queues=None, evidence=None):
        self.app = SimpleNamespace(store=store, config=config, evidence=evidence or EVIDENCE())
        self.pending = FakePending(queues)
        self.enqueued = set()
        self.ingress_lock = threading.RLock()
        self.active_task = None
        self.task_queue = Queue()
        self.latest = None
        self.settings = {'persona': 'P1'}


def stub_for(store, config, queues=None, evidence=None):
    return StubChat(store, config, queues, evidence)


def fragments_within_ten_seconds_are_one_candidate():
    """DECISIONS §7：10 秒内的片段算一波。不排队等也不逐条回——这波没发完就不评估。"""
    lines = [g_in(GROUP, 11, PERSON, '月湾盒放玄关第二格', T0 - 400),
             g_in(GROUP, 12, PERSON_B, '行，我去搬', T0 - 60),
             g_in(GROUP, 13, PERSON, '还有那台设备', T0 - 4),
             g_in(GROUP, 14, PERSON_B, '标签我来写', T0)]
    store = base.bind_store(data_for(lines))
    trigger = store.db.messages.find_one({'_id': 'in-%s-14' % GROUP})
    decision, _updated, _e = run(store, trigger, moment=T0 + 1)   # 评估就发生在最后一条刚到那一下
    assert 'candidate_merge_window' in decision['holds'], decision
    assert not decision['dense'], decision          # 不是靠密度闸拦的，是合并窗口本身
    assert decision['burst_rows'] == 2 and decision['merge_window_seconds'] == 10.0, decision
    return '连着发的两条算一个候选：这波还没发完，不抢着接'


CASES = [q1_unprompted_message_can_get_a_chance,
         q1_topic_line_reaches_the_role_context,
         q2_quiet_hours_hold_unprompted_only,
         q2_cooldown_does_not_touch_direct_questions,
         q2_foreground_task_and_queued_inputs_win,
         rhythm_gate_blocks_fast_exchanges,
         fragments_within_ten_seconds_are_one_candidate,
         no_timer_reopens_nothing,
         one_unanswered_attempt_per_topic,
         scene_cooldown_and_hourly_cap,
         probe_budget_counts_the_chance_not_the_speech,
         one_message_does_not_clear_another_request,
         unenrolled_scene_is_left_alone,
         row_without_time_is_not_guessed,
         hook_enqueues_only_after_overheard_row,
         recheck_holds_when_the_gate_closed,
         topic_is_derived_for_every_group_row,
         proactive_errors_do_not_break_the_round,
         recheck_never_touches_a_woken_reply]


def run_all():
    results = []
    for case in CASES:
        try:
            results.append((case.__name__, True, case()))
        except AssertionError as exc:
            results.append((case.__name__, False, str(exc) or '断言失败'))
        except Exception as exc:            # 假库没接住也报成失败，不冒充通过
            results.append((case.__name__, False, '%s: %s' % (type(exc).__name__, exc)))
    return results


if __name__ == '__main__':
    for name, ok, note in run_all():
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ' — ' + note if note else ''))
