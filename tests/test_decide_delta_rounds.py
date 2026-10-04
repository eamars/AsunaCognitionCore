"""DECIDE 可选字段「按条目去重」的 MongoDB 用例：``next=recall`` 之后的第二次 DECIDE（ADR-009 §9.1）。

离线套件（``python3 tools/decide_delta_rounds_offline_check.py``）假掉的只有存储与模型；这里跑真
Mongo、真 CAS、真 GridFS、真夹具世界与真流水线（ingest → MONOLOGUE → DECIDE →（WRITE）→ 回想 →
再 DECIDE → SPEAK）。两边都不代替操作员在宿主上跑的完整 pytest。

要验的事（2026-10-05 复核的验收条件）：模型回想之后常把整份决策重写一遍，第二轮逐字带着第一轮的
pin / affect / policy_set / write_docs 再加一条新的 —— 旧条目只生效一次，新条目生效一次；同一份
delta 崩溃重放仍然 no-op；attach 以最后一次 DECIDE 为准（被退回就不带图，不无声留下上一张）；
read 在一轮里只被验一遍。去重按每个条目的语义键，不按整份 delta 的指纹，也不按条目在这一轮的位置。
"""
import copy
import json

from conftest import FIXTURES

from asuna import decide_delta, group_admin, outbound_media
from asuna.coordinator import Coordinator
from asuna.documents import DocumentStore
from asuna.ingress import episode_id as episode_id_for, persist_input
from asuna.lanes import FakeLane, LaneResult
from test_adr009_p2 import decide, owner
from test_engineering_m1 import event
from test_outbound_image import JPEG, LOCAL, LOCAL_SCOPE, PNG, attach_rejections, channel_scene, import_bytes, link, speak_rows

DM = 'dm-a'
QQ = 'dm-qq'
# 心情那一段直接照搬夹具里被审过的 demo 模型：clamp / bands / policy 缺一个都会在 context.prepare
# 投影心情时炸（手写一份很容易漏掉 clamp）。
DEMO_MODEL = json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8'))
LEDGER_SEED = '## 答应过的事\n暂无。'


def model():
    """这一组用例要的人格模型：心情开着、结算每天能提两条记忆、说话一条一段。"""
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': '示例角色'},
            'speak': {'max_messages': 1, 'split_marker': '---split---', 'chars_per_second': 4,
                      'min_gap_s': 1, 'max_gap_s': 3},
            'affect': copy.deepcopy(DEMO_MODEL['affect']),
            'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}}}


def pinnable(store, count=2):
    """这一轮真会被带进 ``ref_index`` 的记忆 id（测试环境没有向量后端 → 取本场景可读的前 6 条）。

    不够就补几条本场景的活记忆；返回的是「按同一套取法真能取到」的那几个，不硬编码 id。
    """
    readable = ['scene:' + DM, 'global-safe', 'owner-private:P1']

    def window():
        return [row['_id'] for row in store.db.memory_units.find(
            {'scope_key': {'$in': readable}, 'status': 'active', 'policy_epoch': 1}, {'_id': 1}).sort('_id', 1).limit(6)]

    n = 0
    while len(window()) < count:
        store.put('memory_units', {'_id': 'a-dr-mem-%d' % n, 'kind': 'memory_unit', 'scope_key': 'scene:' + DM,
                                   'policy_epoch': 1, 'status': 'active', 'pinned': False,
                                   'body_markdown': '他记得我提过的那件小事', 'origin': 'test'}, stream='dr')
        n += 1
    return window()[:count]


def policy_revisions(store, ep_id):
    return store.db.state_revisions.count_documents({'mutation_id': {'$regex': '^' + ep_id + ':policy_set:'}})


def sections(store, slug='ledger'):
    return DocumentStore(store, 'P1').read(slug)[1]['sections']


# 这一轮的事件行；channel 给了就是托管入站（QQ 私聊那条路）。round_() 与 citable() 共用一份。
def turn_event(key, *, scene=DM, person='A', text='我回来了。', channel=None):
    row = {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text}
    if channel:
        row['channel'] = {'id': 'replay', 'account_id': 'bot', 'target': {'type': 'dm', 'id': 'peer'},
                          'platform_event_id': 'p-' + key}
    return row


# 这一轮 context.ref_index 里真会有的 id：事件本身 + 那条入站消息行（与 context.py 同一算法）。
# affect 条目的 ref 必须是这里面的一个 —— 自己编一个会被 AFFECT_REF_NOT_IN_INDEX 退回。
def citable(key, **kw):
    row = turn_event(key, **kw)
    return [row['event_id'], 'in-' + episode_id_for(row)]


# items() 的 ref 由 citable() 现取：affect 的 ref 得是本轮真能引用的那个 id，不写死。
def items(store, ref):
    """第一轮那几样（pin / affect / policy_set / write_docs）与第二轮要新加的那条 pin。"""
    old, new = pinnable(store)
    return {'pin_old': {'memory_id': old, 'pinned': True}, 'pin_new': {'memory_id': new, 'pinned': True},
            'affect': {'intensity': '明显', 'direction': '好', 'ref': ref, 'why': '他记得我提过的那件小事',
                       'cost': '我停下来想了一会儿'},
            'policy': {'key': 'render.budget_tokens', 'value': 40000, 'reason': '想少带点上下文'},
            'write': {'doc': 'ledger', 'op': 'append_section', 'heading': '今天的一件小事', 'reason': '值得记下来',
                      'visibility': 'public', 'tags': ['entry']}}


def round_(store, outputs, *, key='dr', scene=DM, person='A', text='我回来了。', channel=None):
    """真流水线跑一轮；``channel`` 给了就走托管入站（QQ 私聊那条路）。"""
    lane = FakeLane(store, outputs)
    coordinator = Coordinator(store, lane)
    event_row = turn_event(key, scene=scene, person=person, text=text, channel=channel)
    if channel:
        persist_input(store, event_row, managed=True)
    return coordinator, lane, coordinator.ingest(event_row)


def phases(lane):
    return [call['phase'] for call in lane.calls]


# ── 1) 回想之后的第二次 DECIDE ────────────────────────────────────────────────
def test_DR1_second_decide_after_recall_applies_old_items_once_and_the_new_one_once(store):
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    part = items(store, citable('dr1')[0])
    first = decide(next='recall', recall_query='小事', pin=[part['pin_old']], affect=[part['affect']],
                   policy_set=[part['policy']], write_docs=[part['write']])
    # 回想之后：整份决策重写一遍（逐字带着第一轮那四条），只多加一条新的 pin
    second = decide(pin=[dict(part['pin_old']), dict(part['pin_new'])], affect=[dict(part['affect'])],
                    policy_set=[dict(part['policy'])], write_docs=[dict(part['write'])])
    _coordinator, lane, ep = round_(store, [LaneResult('想。'),                       # MONOLOGUE
                                            first,                                     # DECIDE（带四条）
                                            LaneResult('他等了我很久。'),   # WRITE：那一节的正文
                                            LaneResult('再想想。'),                 # MONOLOGUE（回想之后）
                                            second,                                    # DECIDE（逐字重写 + 一条新 pin）
                                            LaneResult('好。')], key='dr1')            # SPEAK
    assert ep['state'] == 'COMMITTED', ep
    assert part['affect']['ref'] in ep['context']['ref_index'], ep['context']['ref_index']
    assert phases(lane).count('DECIDE') == 2, phases(lane)
    assert not ep['rejections'], ep['rejections']
    assert store.db.affect_events.count_documents({}) == 1, '旧的那条心情在第二轮又记了一遍'
    assert policy_revisions(store, ep['_id']) == 1, '同一个键同一个值又改了一遍'
    assert [row['heading'] for row in sections(store)] == ['答应过的事', '今天的一件小事'], '同一节又追加了一遍'
    assert store.db.memory_units.find_one({'_id': part['pin_new']['memory_id']})['pinned'] is True, '第二轮的新 pin 没生效'
    assert [row['memory_id'] for row in ep['delta_results']['pin']] == [part['pin_old']['memory_id'],
                                                                        part['pin_new']['memory_id']]
    assert len(ep['delta_effects']) == 5, ep['delta_effects']              # 四条旧的 + 一条新的，各一条
    assert phases(lane).count('WRITE') == 1, '旧条目的 WRITE 阶段又跑了一次：%s' % phases(lane)


def test_DR2_new_item_at_index_zero_in_the_second_round_is_not_the_old_one(store):
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    part = items(store, citable('dr2')[0])
    first = decide(next='recall', recall_query='小事', pin=[part['pin_old']], affect=[part['affect']])
    other = {'intensity': '轻微', 'direction': '好', 'ref': citable('dr2')[0], 'why': '他把话说完了才停下来',
             'cost': '我把到嘴边的半句咽了回去'}
    # 第二轮把新的那两条排在 index 0，旧的排在后面：按位置去重会把新条目当成已生效的那条吞掉
    second = decide(pin=[dict(part['pin_new']), dict(part['pin_old'])], affect=[dict(other), dict(part['affect'])])
    _coordinator, _lane, ep = round_(store, [LaneResult('想。'), first, LaneResult('再想想。'), second,
                                             LaneResult('好。')], key='dr2')
    assert not ep['rejections'], ep['rejections']
    assert store.db.memory_units.find_one({'_id': part['pin_new']['memory_id']})['pinned'] is True
    assert store.db.memory_units.find_one({'_id': part['pin_old']['memory_id']})['pinned'] is True
    assert store.db.affect_events.count_documents({}) == 2, '第二轮的新心情被当成 index 0 那条旧的了'
    assert sorted(row['memory_id'] for row in ep['delta_results']['pin']) == \
        sorted([part['pin_old']['memory_id'], part['pin_new']['memory_id']])


def test_DR3_a_new_value_for_the_same_policy_key_is_a_new_change(store):
    owner(store)
    store.config['persona_model'] = model()
    part = items(store, citable('dr3')[0])
    first = decide(next='recall', recall_query='参数', policy_set=[part['policy']])
    changed = dict(part['policy'], value=60000, reason='还是想多看一点')
    second = decide(policy_set=[changed])
    _coordinator, _lane, ep = round_(store, [LaneResult('想。'), first, LaneResult('再想想。'), second,
                                             LaneResult('好。')], key='dr3')
    assert not ep['rejections'], ep['rejections']
    assert policy_revisions(store, ep['_id']) == 2, '同一个键换了新值，应该是一次新的修改'
    assert ep['delta_results']['policy_set'][-1]['value'] == 60000


# ── 2) 崩溃重放 ───────────────────────────────────────────────────────────────
def test_DR4_crash_replay_of_the_same_delta_changes_nothing(store):
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    part = items(store, citable('dr4')[0])
    delta = {'pin': [part['pin_old']], 'affect': [part['affect']], 'policy_set': [part['policy']],
             'write_docs': [part['write']]}
    coordinator, lane, ep = round_(store, [LaneResult('想。'), decide(**delta),
                                           LaneResult('他等了我很久。'), LaneResult('好。')], key='dr4')
    assert not ep['rejections'], ep['rejections']
    assert phases(lane).count('WRITE') == 1
    row = store.db.episodes.find_one({'_id': ep['_id']})
    # 崩在「副作用已经落了、这一轮的账还没写回」：等价于把行上那份账擦掉，再重放同一份 delta
    crashed = {k: v for k, v in row.items() if k != 'delta_effects'}
    again = decide_delta.apply(coordinator, crashed)
    assert not again['rejections'], again['rejections']
    assert store.db.affect_events.count_documents({}) == 1, '重放多记了一条心情'
    assert policy_revisions(store, ep['_id']) == 1, '重放多改了一次参数'
    assert [row_['heading'] for row_ in sections(store)] == ['答应过的事', '今天的一件小事'], '重放多写了一遍文档'
    assert store.db.memory_units.find_one({'_id': part['pin_old']['memory_id']})['pinned'] is True
    assert phases(lane).count('WRITE') == 1, '重放又跑了一次 WRITE 阶段：%s' % phases(lane)
    assert len(again['delta_effects']) == 4, again['delta_effects']


def test_DR5_reentering_a_committed_round_is_a_no_op(store):
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    part = items(store, citable('dr5')[0])
    delta = {'pin': [part['pin_old']], 'affect': [part['affect']], 'policy_set': [part['policy']],
             'write_docs': [part['write']]}
    coordinator, lane, ep = round_(store, [LaneResult('想。'), decide(**delta),
                                           LaneResult('他等了我很久。'), LaneResult('好。')], key='dr5')
    row = store.db.episodes.find_one({'_id': ep['_id']})
    again = decide_delta.apply(coordinator, dict(row))                    # 同一份 delta 再进一次 advance
    assert again['rejections'] == [], again['rejections']
    assert again['delta_effects'] == row['delta_effects']
    assert store.db.affect_events.count_documents({}) == 1
    assert [row_['heading'] for row_ in sections(store)] == ['答应过的事', '今天的一件小事']
    assert phases(lane).count('WRITE') == 1


# ── 3) read 只验一遍 ──────────────────────────────────────────────────────────
def test_DR6_read_rejections_are_recorded_once_per_recall_round(store):
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('notes', 'working',
                                    '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    recall = decide(next='recall', recall_query='笔记', read=[{'doc': 'notes'}, {'doc': 'notes', 'sid': '没有的节'}])
    _coordinator, _lane, ep = round_(store, [LaneResult('想看笔记。'), recall, LaneResult('看到了。'), decide(),
                                             LaneResult('好。')], key='dr6')
    reads = [row for row in ep['rejections'] if row['field'] == 'read']
    assert [row['code'] for row in reads] == ['ITEM_INVALID', 'DOC_SECTION_NOT_FOUND'], ep['rejections']
    assert len([row for row in ep['rejections'] if row['code'] == 'DOC_SECTION_NOT_FOUND']) == 1, ep['rejections']


# ── 4) attach：图只看最后一次 DECIDE（没写就没图，被退回也没图） ────────────────────────────
def test_DR7_the_second_decide_governs_the_attached_picture(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    first = import_bytes(store, LOCAL_SCOPE, PNG, target='artifacts/one.png', workspace=tmp_path)['artifact']
    second = import_bytes(store, LOCAL_SCOPE, JPEG, target='artifacts/two.jpg', workspace=tmp_path)['artifact']
    round_one = decide(next='recall', recall_query='再想想', attach=[{'artifact_id': first['artifact_id'],
                                                                      'why': '先给他看这张'}])
    round_two = decide(attach=[{'artifact_id': second['artifact_id'], 'why': '还是发那张新的'}])
    _coordinator, _lane, ep = round_(store, [LaneResult('想。'), round_one, LaneResult('再想想。'), round_two,
                                             LaneResult('这张给你。')], key='dr7', scene=QQ, channel=True)
    assert not attach_rejections(ep), attach_rejections(ep)
    attached = ep['delta_results']['attach']
    assert len(attached) == 1, '一轮至多一张（schema maxItems=1），旧的那张要整份换掉'
    assert attached[0]['artifact_id'] == second['artifact_id'] and attached[0]['round'] == 1
    rows = speak_rows(store, ep['_id'])
    assert rows[0]['attachment']['artifact_id'] == second['artifact_id'], rows[0].get('attachment')
    assert rows[0]['attachment']['sha256'] == second['sha256'], '第一段挂的还是第一轮那张'


def test_DR8_a_refused_picture_in_the_second_decide_leaves_no_picture(store, tmp_path):
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    first = import_bytes(store, LOCAL_SCOPE, PNG, target='artifacts/one.png', workspace=tmp_path)['artifact']
    round_one = decide(next='recall', recall_query='再想想', attach=[{'artifact_id': first['artifact_id'],
                                                                      'why': '给他看这张'}])
    round_two = decide(attach=[{'artifact_id': 'blob-not-offered-this-turn', 'why': '换这张'}])
    _coordinator, _lane, ep = round_(store, [LaneResult('想。'), round_one, LaneResult('再想想。'), round_two,
                                             LaneResult('那就不发了。')], key='dr8', scene=QQ, channel=True)
    assert list(attach_rejections(ep)) == ['ATTACH_ARTIFACT_NOT_IN_CONTEXT'], attach_rejections(ep)
    assert not any(row.get('attachment') for row in speak_rows(store, ep['_id'])), '第二轮的图被退回，却把第一轮那张无声发出去'


# ── 5) group_action / promote 两条 apply 路径 ─────────────────────────────────
def test_DR9_a_restated_group_action_queues_only_once(store):
    from test_group_admin import episode as group_episode, setup as group_setup    # 群夹具要 napcat 包，宿主上才有
    group_setup(store, 'admin')
    ep = group_episode(store)
    mute = {'kind': 'mute', 'who': '#2', 'duration': '10分钟', 'reason': '连着刷屏'}      # #2 = 阿杰，普通成员
    key = decide_delta.semantic_key('group_action', mute)
    first = group_admin.queue(store, ep, 0, mute, key=key)
    again = group_admin.queue(store, ep, 0, mute, key=key)                    # 第二轮逐字重写这一条
    assert first['state'] == again['state'] == '已交给平台，等确认', (first, again)
    assert first['who'] == again['who'] == '[阿杰 #2]', (first, again)
    assert store.db.artifacts.count_documents({'kind': 'group_action'}) == 1, '同一件事排了第二条'
    other = {'kind': 'mute', 'who': '#2', 'duration': '1小时', 'reason': '还在刷屏'}      # 同一个人，另一件事
    queued = group_admin.queue(store, ep, 0, other, key=decide_delta.semantic_key('group_action', other))
    assert queued['who'] == '[阿杰 #2]' and queued['duration'] == '1小时', queued      # 标签写法
    assert store.db.artifacts.count_documents({'kind': 'group_action'}) == 2, '同一个人换时长的禁言被当成同一条吞掉了'


# promote 走 apply()：真实流程在 apply 层就按语义键去重，配额按 results 条数算，重放不该撞配额。
def test_DR10_a_promotion_restated_through_apply_creates_one_memory_unit(store):
    owner(store)
    store.config['persona_model'] = model()
    for source, day in (('dr10-a', '2026-09-28'), ('dr10-b', '2026-09-29')):
        store.put('episodes', {'_id': source, 'scene_id': DM, 'source_event_id': 'in-' + source,
                               'episode_kind': 'reply', 'state': 'COMMITTED'}, stream='dr')
        store.db.audit_events.insert_one({'_id': 'audit-' + source, 'schema_version': 1, 'stream_id': source,
                                          'seq': 1, 'type': 'context.prepared', 'scope_key': 'scene:' + DM,
                                          'occurred_at': day + 'T10:00:00+00:00',
                                          'payload': {'manifest': {'selected': []}},
                                          'prev_hash': '0' * 64, 'event_hash': '1' * 64})
    item = {'fact': '他记得我提过的那件小事', 'appraisal': '我在意这种被记住', 'signal': '稳定的在意',
            'source_ids': ['dr10-a', 'dr10-b'], 'visibility': 'owner_private'}
    settle = store.put('episodes', {'_id': 'dr10-settle', 'scene_id': DM, 'person_id': 'A', 'persona': 'P1',
                                    'episode_kind': 'settlement', 'scope_key': 'scene:' + DM, 'policy_epoch': 1,
                                    'source_event_id': 'in-dr10', 'state': 'DECISION_ACCEPTED',
                                    'decision': {'next': 'silent'}, 'decision_delta': {'promote': [item]},
                                    'context': {'ref_index': []}, 'manifest': {'session_class': 'owner_private'},
                                    'rejections': [], 'delta_results': {}, 'delta_effects': [],
                                    'monologue_refs': []}, stream='dr10-settle')
    coordinator = Coordinator(store, FakeLane(store, []))        # promote 不调模型，lane 用不上
    first = decide_delta.apply(coordinator, settle)
    assert not first['rejections'], first['rejections']
    assert len(first['delta_results']['promote']) == 1, first['delta_results']

    # 同一份决策再进一次 apply（崩溃重放 / advance 重入）：账上已有这条 → 跳过，不往 results 里
    # 添第二条，也就不会把 daily_quota 数满而报 PROMOTION_QUOTA。
    again = decide_delta.apply(coordinator, store.db.episodes.find_one({'_id': 'dr10-settle'}))
    assert not again['rejections'], again['rejections']
    assert len(again['delta_results']['promote']) == 1, again['delta_results']
    assert store.db.memory_units.count_documents({'episode_id': 'dr10-settle'}) == 1

    # 换了内容的那条是新的：逐字带着旧的再加一条新的，旧的跳过、新的写进去（配额 2 还够）
    row = store.db.episodes.find_one({'_id': 'dr10-settle'})
    changed = dict(item, appraisal='这次是我主动记下的')
    third = decide_delta.apply(coordinator, dict(row, decision_delta={'promote': [dict(item), changed]}))
    assert not third['rejections'], third['rejections']
    assert len(third['delta_results']['promote']) == 2, third['delta_results']
    assert store.db.memory_units.count_documents({'episode_id': 'dr10-settle'}) == 2, '换了内容的那条没被写进去'


def test_DR11_a_round_that_applied_nothing_does_not_swallow_the_second_decide(store):
    """第一轮只给了 read（那一轮 apply 什么也没办成）：第二轮的条目不能被当成「已经生效过」。"""
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    DocumentStore(store, 'P1').seed('notes', 'working',
                                    '<!-- asuna-seed {"visibility": "owner_private"} -->\n## 私密\nPRIVATE_NOTE_BODY\n')
    part = items(store, citable('dr11')[0])
    first = decide(next='recall', recall_query='笔记', read=[{'doc': 'notes', 'sid': '私密'}])
    second = decide(pin=[dict(part['pin_old'])], write_docs=[dict(part['write'])])
    _coordinator, lane, ep = round_(store, [LaneResult('想看笔记。'), first, LaneResult('再想想。'), second,
                                            LaneResult('他等了我很久。'), LaneResult('好。')], key='dr11')
    assert not ep['rejections'], ep['rejections']
    assert ep['delta_effects'] and len(ep['delta_effects']) == 2, ep['delta_effects']
    assert store.db.memory_units.find_one({'_id': part['pin_old']['memory_id']})['pinned'] is True
    assert [row['heading'] for row in sections(store)] == ['答应过的事', '今天的一件小事']
    assert phases(lane).count('WRITE') == 1, phases(lane)


def test_DR12_a_second_decide_without_attach_sends_no_picture(store, tmp_path):
    """图只看最后一次 DECIDE：回想之后重写的那一份没写 attach，这一条就不带图。"""
    owner(store)
    channel_scene(store, QQ)
    link(store, QQ, LOCAL)
    first = import_bytes(store, LOCAL_SCOPE, PNG, target='artifacts/one.png', workspace=tmp_path)['artifact']
    round_one = decide(next='recall', recall_query='再想想', attach=[{'artifact_id': first['artifact_id'],
                                                                      'why': '给他看这张'}])
    round_two = decide()                                             # 重写整份，没再写 attach
    _coordinator, _lane, ep = round_(store, [LaneResult('想。'), round_one, LaneResult('再想想。'), round_two,
                                             LaneResult('那就说话。')], key='dr12', scene=QQ, channel=True)
    assert not attach_rejections(ep), attach_rejections(ep)
    assert 'attach' not in ep['delta_results'], ep['delta_results']
    rows = speak_rows(store, ep['_id'])
    assert rows and not any(row.get('attachment') for row in rows), '最后一次 DECIDE 没写 attach，图却还是发出去了'


def test_DR13_two_appends_for_one_document_with_different_reasons_are_both_written(store):
    """reason 是「要写什么」的一部分：同一轮对同一份文档追加两次（理由不同）两条都得生效。"""
    owner(store)
    store.config['persona_model'] = model()
    DocumentStore(store, 'P1').seed('ledger', 'ledger', LEDGER_SEED)
    first = {'doc': 'ledger', 'op': 'append_section', 'heading': '今天的一件小事', 'reason': '他今天等了我很久',
             'visibility': 'public', 'tags': ['entry']}
    second = dict(first, reason='我把话说晚了，记一下')
    round_one = decide(next='recall', recall_query='小事', write_docs=[first, second])
    round_two = decide(write_docs=[dict(first), dict(second)])       # 回想之后逐字重写这两条
    _coordinator, lane, ep = round_(store, [LaneResult('想。'), round_one,
                                            LaneResult('他等了我很久。'), LaneResult('我把话说晚了。'),
                                            LaneResult('再想想。'), round_two, LaneResult('好。')], key='dr13')
    assert not ep['rejections'], ep['rejections']
    headings = [row['heading'] for row in sections(store)]
    assert headings == ['答应过的事', '今天的一件小事', '今天的一件小事'], '第二条被当成同一条悄悄跳过了：%s' % headings
    assert phases(lane).count('WRITE') == 2, '第二轮逐字重写又生成了一遍正文：%s' % phases(lane)
    assert len(ep['delta_effects']) == 2, ep['delta_effects']
