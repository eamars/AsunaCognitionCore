"""DECIDE 可选字段「按条目去重」的离线回归：``next=recall`` 之后的第二次 DECIDE。

本机跑：``python3 tools/decide_delta_rounds_offline_check.py`` —— 不需要 Mongo、不需要 pytest、
不联网、不发 QQ、不调模型。装真跑的是仓库里那份代码：``decide_delta.apply`` 的整条 apply 路径
（pin / policy_set / write_docs / affect / attach）、``DocumentStore`` 的 mutation_id 重放、
``PolicyStore`` 的同一份修订、``AffectLedger`` 的插入幂等、``outbound_media`` 的 attach 元数据。
假掉的只有存储（沿用 ``tests/outbound_image_cases.py`` 那套内存集合 + 内存 GridFS，补上
``head``）与模型（WRITE 阶段用「同一 operation 返回同一份答案」的替身，与 ``lanes.FakeLane``
的 receipt 幂等语义同形）。

覆盖（2026-10-05 复核的验收条件）：
- 第二轮 = 第一轮原样条目 + 一条新条目 → 旧的只生效一次、新的生效一次；
- 第二轮把新条目排在 index 0 → 不被误认成第一轮 index 0 那一条（不按位置去重）；
- 同一份 delta 崩溃重放 / advance 重入 → no-op；
- attach 只看最后一次 DECIDE：那一份给了就发那张，没给（或整份决策里没有可选字段）就不发图，
  被退回时也不无声丢图 —— 前一次那张不会跟着走；
- 去重键含什么由「引擎吃什么」决定：write_docs 的 reason 是 intent 的一部分（同一轮或跨轮对
  同一份文档追加两次、理由不同 = 两件事），policy_set 的 reason 只是措辞（同键同值换个说法
  不再生效一次）；
- 开发期不写旧数据兼容：行上没有 delta_effects 就是空账，也不再写 delta_applied 那个整份标记；
- read 在 recall 那一轮只被验一遍（同一条拒收不记两次）；
- 去重按条目语义、不按整份 delta 指纹：换个理由措辞不变成新效果。

promote / group_action 两条 apply 路径要真夹具（结算回合、群成员快照），由宿主侧
``tests/test_decide_delta_rounds.py`` 复测；这里用结构面守住它们的 id 由语义键导出。
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import outbound_image_cases as base          # noqa: E402  假存储 + 替身库（本模块只借它这套夹具）

from asuna import decide_delta, outbound_media   # noqa: E402
from asuna.blobs import BlobStore                 # noqa: E402
from asuna.documents import DocumentStore         # noqa: E402

PERSONA = 'xiaoman'
EP = 'ep-rounds'
PNG, JPEG = base.PNG, base.JPEG

CONFIG = copy.deepcopy(base.CONFIG)
CONFIG['persona_model'] = {'model_version': 1, 'persona': {'id': PERSONA, 'display_name': '小满'},
                           'affect': {'enabled': True, 'default_half_h': 24, 'arl_half_h': 12,
                                      'kinds': {'开心': {'label': '开心', 'valence': 'positive', 'half_h': 24}}}}

PIN_OLD = {'memory_id': 'mu-old', 'pinned': True}
PIN_NEW = {'memory_id': 'mu-new', 'pinned': True}
AFFECT_ONE = {'intensity': '明显', 'direction': '好', 'ref': 'mu-old', 'why': '他记得我提过的那件小事'}
AFFECT_TWO = {'intensity': '轻微', 'direction': '好', 'ref': 'mu-new', 'why': '他把话说完了才停下来'}
POLICY_ONE = {'key': 'render.budget_tokens', 'value': 1024, 'reason': '想少带点上下文'}
POLICY_OTHER_WORDING = {'key': 'render.budget_tokens', 'value': 1024, 'reason': '少带一点上下文更好读'}
POLICY_TWO = {'key': 'render.budget_tokens', 'value': 2048, 'reason': '还是想多看一点'}
WRITE_ONE = {'doc': 'ledger', 'op': 'append_section', 'heading': '今天的一件小事', 'reason': '值得记下来',
             'visibility': 'public', 'tags': ['entry']}
WRITE_TWO = {'doc': 'ledger', 'op': 'append_section', 'heading': '另一件小事', 'reason': '这条也值得',
             'visibility': 'public', 'tags': ['entry']}


class Store(base.FakeStore):
    """补上 ``head``：policy 与文档都要按 state_heads / state_revisions 真算。"""

    def head(self, entity, scope):
        head = self.db.state_heads.find_one({'_id': entity + '|' + scope})
        if not head:
            return None
        return head, self.db.state_revisions.find_one({'_id': head['revision_id']})


class Crash(Exception):
    pass


class Lane:
    """WRITE 阶段的替身：同一 operation 重放返回同一份答案（与 lanes.FakeLane 的 receipt 同形）。"""

    def __init__(self):
        self.answers, self.calls = {}, []

    def generate(self, operation, instruction):
        if operation not in self.answers:
            self.calls.append(operation)
            self.answers[operation] = '这一轮写进去的正文 #%d' % len(self.calls)
        return self.answers[operation]


class Coordinator:
    def __init__(self, store, lane=None, updates_before_crash=None):
        self.store, self.lane = store, lane or Lane()
        self.updates, self.crash_after = 0, updates_before_crash

    def _update(self, ep, **changes):
        self.updates += 1
        if self.crash_after is not None and self.updates > self.crash_after:
            raise Crash('模拟在把这一轮写回之前崩掉')
        return dict(ep, **changes)

    def _stage(self, ep, phase, round_id=0, extra='', *, instruction=None, operation=None, shape=None, label=None):
        assert phase == 'WRITE', phase
        return self.lane.generate(operation or '%s:%s:%s' % (ep['_id'], phase, round_id), instruction)


def world():
    """一个 owner_private 私聊场景：两条可读记忆、一份 seed 过的活账、BlobStore 里两张图。"""
    store = Store(CONFIG)
    scene = base.scene_row('dm')
    store.db.scenes.insert_one(scene)
    for memory_id in ('mu-old', 'mu-new'):
        store.db.memory_units.insert_one({'_id': memory_id, 'kind': 'memory_unit', 'scope_key': base.DM_SCOPE,
                                          'status': 'active', 'pinned': False, 'revision': 1, 'body_markdown': '一件小事'})
    DocumentStore(store, PERSONA).seed('ledger', 'ledger', '## 答应过的事\n暂无。')
    return store, scene


def offer(store, scene):
    return outbound_media.offer(store, CONFIG, scene, 'owner_private')


def pictures(store):
    return [BlobStore(store).put(data, base.DM_SCOPE, 'image', media_type=outbound_media.sniff_media_type(data))
            for data in (PNG, JPEG)]


def manifest_with(store, *slugs):
    """上下文里钉住的那几份文档修订（真流水线在准备上下文时就钉好了，之后不跟着本轮的写更新）。"""
    docs = DocumentStore(store, PERSONA)
    return {slug: docs.read(slug)[0] for slug in slugs}


def episode(delta, scene, *, next_stage='speak', rounds=0, context=None, row=None, manifest=None):
    """这一轮的 episode 行；``row`` 传上一轮写回的那份（第二轮就带着已经生效的账）。"""
    ep = row if row is not None else {'_id': EP, 'scene_id': scene['_id'], 'person_id': 'owner-p',
                                      'scope_key': base.DM_SCOPE, 'persona': PERSONA,
                                      'source_event_id': 'in-' + EP, 'policy_epoch': 1, 'revision': 3,
                                      'manifest': {'session_class': 'owner_private'},
                                      'rejections': [], 'delta_results': {}, 'delta_effects': []}
    ep = dict(ep, decision={'next': next_stage}, decision_delta=delta, recall_rounds=rounds,
              context=context if context is not None else (ep.get('context') or {}))
    if manifest is not None:
        ep['manifest'] = {**(ep.get('manifest') or {}), 'documents': dict(manifest)}
    return ep


def affect_rows(store):
    return list(store.db.affect_events.find({}))


def policy_rows(store):
    return [row for row in store.db.state_revisions.find({})
            if str(row.get('mutation_id') or '').startswith(EP + ':policy_set:')]


def sections(store):
    return DocumentStore(store, PERSONA).read('ledger')[1]['sections']


def memory(store, memory_id):
    return store.db.memory_units.find_one({'_id': memory_id})


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def context_for(store, scene):
    return {'ref_index': ['mu-old', 'mu-new'], 'image_artifacts_from_program': offer(store, scene)}


# ── 1) 第二轮 DECIDE：旧条目只生效一次，新条目生效一次 ──────────────────────────
@case
def second_decide_after_recall_applies_old_items_once_and_the_new_one_once():
    store, scene = world()
    coord = Coordinator(store)
    first = {'pin': [PIN_OLD], 'affect': [AFFECT_ONE], 'policy_set': [POLICY_ONE], 'write_docs': [WRITE_ONE]}
    ep = decide_delta.apply(coord, episode(first, scene, next_stage='recall', context=context_for(store, scene)))
    assert not ep['rejections'], ep['rejections']
    assert (len(affect_rows(store)), len(policy_rows(store)), len(sections(store)), len(coord.lane.calls)) == (1, 1, 2, 1)

    # 回想之后：整份决策重写一遍（逐字带着第一轮那四条），再加一条新的 pin
    second = {'pin': [copy.deepcopy(PIN_OLD), copy.deepcopy(PIN_NEW)],
              'affect': [copy.deepcopy(AFFECT_ONE)],
              'policy_set': [copy.deepcopy(POLICY_ONE)],
              'write_docs': [copy.deepcopy(WRITE_ONE)]}
    ep = decide_delta.apply(coord, episode(second, scene, rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    assert len(affect_rows(store)) == 1, '旧的那条心情又记了一遍：%s' % [r['_id'] for r in affect_rows(store)]
    assert len(policy_rows(store)) == 1, '同一个键同一个值又改了一遍'
    assert len(sections(store)) == 2, '同一节又追加了一遍：%s' % [s['heading'] for s in sections(store)]
    assert len(coord.lane.calls) == 1, '旧条目的 WRITE 阶段又跑了一次：%s' % coord.lane.calls
    assert memory(store, 'mu-new')['pinned'] is True, '第二轮的新 pin 没生效'
    assert [row['memory_id'] for row in ep['delta_results']['pin']] == ['mu-old', 'mu-new'], ep['delta_results']['pin']
    assert len(ep['delta_effects']) == 5, ep['delta_effects']       # 四条旧的 + 一条新的，各一条
    return True, '第二轮逐字重写 + 一条新 pin：心情/参数/文档各只有一份，新记忆被 pin，账上 5 条效果'


@case
def new_item_at_index_zero_in_the_second_round_is_not_the_old_one():
    store, scene = world()
    coord = Coordinator(store)
    first = {'pin': [PIN_OLD], 'affect': [AFFECT_ONE]}
    ep = decide_delta.apply(coord, episode(first, scene, next_stage='recall', context=context_for(store, scene)))
    # 第二轮把「新的那条」排在 index 0，旧的排在后面：按位置去重会把新条目当成已生效的那条吞掉
    second = {'pin': [copy.deepcopy(PIN_NEW), copy.deepcopy(PIN_OLD)],
              'affect': [copy.deepcopy(AFFECT_TWO), copy.deepcopy(AFFECT_ONE)]}
    ep = decide_delta.apply(coord, episode(second, scene, rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    assert memory(store, 'mu-new')['pinned'] is True and memory(store, 'mu-old')['pinned'] is True
    assert len(affect_rows(store)) == 2, '第二轮的新心情被当成 index 0 那条旧的了'
    assert sorted(row['memory_id'] for row in ep['delta_results']['pin']) == ['mu-new', 'mu-old']
    assert len(affect_rows(store)) == len(ep['delta_results']['affect']), '心情记的行数与交给 SPEAK 的结果对不上'
    return True, '新条目排在 index 0 也生效：去重看条目内容，不看它排第几'


@case
def reworded_reason_does_not_make_the_same_policy_change_new_again():
    store, scene = world()
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'policy_set': [POLICY_ONE]}, scene, next_stage='recall',
                                           context=context_for(store, scene)))
    assert not ep['rejections'], ep['rejections']
    ep = decide_delta.apply(coord, episode({'policy_set': [copy.deepcopy(POLICY_OTHER_WORDING)]}, scene,
                                           rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    assert len(policy_rows(store)) == 1, '同一个键同一个值，只换了 reason 措辞，又改了一遍'
    assert len(ep['delta_effects']) == 1, ep['delta_effects']
    return True, 'policy_set 的 reason 不进身份：同一个键同一个值换个说法还是同一件事'


@case
def two_appends_for_one_document_with_different_reasons_are_two_effects():
    """同一轮对同一份文档追加两次：reason 是「要写什么」的一部分（WRITE 阶段拿整条 item 当 intent）。"""
    store, scene = world()
    coord = Coordinator(store)
    first = {'doc': 'ledger', 'op': 'append_section', 'heading': '今天的一件小事', 'reason': '他今天等了我很久',
             'visibility': 'public', 'tags': ['entry']}
    second = dict(first, reason='我把话说晚了，记一下')
    ep = decide_delta.apply(coord, episode({'write_docs': [first, second]}, scene,
                                           context=context_for(store, scene), manifest=manifest_with(store, 'ledger')))
    assert not ep['rejections'], ep['rejections']
    assert [row['heading'] for row in sections(store)] == ['答应过的事', '今天的一件小事', '今天的一件小事'], \
        '第二条被当成同一条悄悄跳过了：%s' % [row['heading'] for row in sections(store)]
    assert len(coord.lane.calls) == 2, '两次写只生成了一次正文：%s' % coord.lane.calls
    assert len(ep['delta_effects']) == 2, ep['delta_effects']
    return True, '同一轮两次追加同一份文档（理由不同）：两节都写进去，WRITE 阶段跑两次'


@case
def a_second_round_write_for_the_same_document_builds_on_the_first_one():
    """跨轮也一样：回想那一轮写过这份文档，第二轮再写它时接着刚写的那一份修订，不撞 BASE_REVISION_STALE。"""
    store, scene = world()
    coord = Coordinator(store)
    pinned = manifest_with(store, 'ledger')          # 本轮开始时钉住的那一份，之后不跟着写更新
    first = {'doc': 'ledger', 'op': 'append_section', 'heading': '今天的一件小事', 'reason': '他等了我很久',
             'visibility': 'public', 'tags': ['entry']}
    ep = decide_delta.apply(coord, episode({'write_docs': [first]}, scene, next_stage='recall',
                                           context=context_for(store, scene), manifest=pinned))
    assert not ep['rejections'], ep['rejections']
    # 回想之后重写整份：逐字带着第一条，再加一条新的（同一份文档）
    ep = decide_delta.apply(coord, episode({'write_docs': [dict(first), dict(WRITE_TWO)]}, scene, rounds=1,
                                           row=ep, manifest=pinned))
    assert not ep['rejections'], ep['rejections']
    assert [row['heading'] for row in sections(store)] == ['答应过的事', '今天的一件小事', '另一件小事'], \
        [row['heading'] for row in sections(store)]
    assert len(coord.lane.calls) == 2, '旧条目又生成了一遍正文，或新的那条没写：%s' % coord.lane.calls
    assert len(ep['delta_effects']) == 2, ep['delta_effects']
    return True, '跨轮连写同一份文档：旧条目只生效一次，新条目接着刚写的那一份修订写进去'


@case
def a_new_value_for_the_same_key_is_a_new_effect():
    store, scene = world()
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'policy_set': [POLICY_ONE]}, scene, next_stage='recall',
                                           context=context_for(store, scene)))
    ep = decide_delta.apply(coord, episode({'policy_set': [copy.deepcopy(POLICY_TWO)]}, scene, rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    assert len(policy_rows(store)) == 2, '同一个键换了新值，应该是一次新的修改'
    assert ep['delta_results']['policy_set'][-1]['value'] == 2048
    return True, '同一个键改成新值 = 新效果（去重键含值，不只含键名）'


# ── 2) 崩溃重放 / advance 重入 ────────────────────────────────────────────────
@case
def crash_replay_of_the_same_delta_changes_nothing():
    """崩在「副作用已经落了、账还没写回」的任何一点：重放同一份 delta 补齐剩下的，已落的那条不重复。

    账是按字段组一段段落回的（apply 每处理完一组就写回一次），所以崩在不同位置时：已经进账的条目
    被跳过，没进账的条目靠「副作用 id 由语义键导出」在存储层撞回同一条。
    """
    delta = {'pin': [PIN_OLD], 'affect': [AFFECT_ONE], 'policy_set': [POLICY_ONE], 'write_docs': [WRITE_ONE]}
    for crash_after in (0, 1, 2, 3):
        store, scene = world()
        lane = Lane()
        try:
            decide_delta.apply(Coordinator(store, lane, updates_before_crash=crash_after),
                               episode(delta, scene, context=context_for(store, scene)))
        except Crash:
            pass
        else:
            raise AssertionError('crash_after=%d 这一轮没崩成，测不到重放' % crash_after)
        ep = decide_delta.apply(Coordinator(store, lane), episode(delta, scene, context=context_for(store, scene)))
        assert not ep['rejections'], (crash_after, ep['rejections'])
        assert len(affect_rows(store)) == 1, (crash_after, [row['_id'] for row in affect_rows(store)])
        assert len(policy_rows(store)) == 1, (crash_after, [row['mutation_id'] for row in policy_rows(store)])
        assert [row['heading'] for row in sections(store)] == ['答应过的事', '今天的一件小事'], crash_after
        assert memory(store, 'mu-old')['pinned'] is True, crash_after
        assert len(lane.calls) == 1, (crash_after, 'WRITE 阶段不止跑了一次：%s' % lane.calls)
        assert len(ep['delta_effects']) == 4, (crash_after, ep['delta_effects'])
    return True, '崩在第 0/1/2/3 次写回之前都重放一遍：心情/参数/文档各一份、WRITE 只生成一次、账补齐 4 条'


@case
def advance_reentry_after_a_committed_round_is_a_no_op():
    store, scene = world()
    coord = Coordinator(store)
    delta = {'pin': [PIN_OLD], 'affect': [AFFECT_ONE], 'policy_set': [POLICY_ONE], 'write_docs': [WRITE_ONE]}
    ep = decide_delta.apply(coord, episode(delta, scene, context=context_for(store, scene)))
    before = (len(affect_rows(store)), len(policy_rows(store)), len(sections(store)), len(coord.lane.calls),
              ep['delta_effects'])
    again = decide_delta.apply(Coordinator(store, coord.lane), dict(ep))       # 同一份 delta 再进一次 advance
    assert again['rejections'] == [], again['rejections']
    assert (len(affect_rows(store)), len(policy_rows(store)), len(sections(store)), len(coord.lane.calls),
            again['delta_effects']) == before
    return True, '已经应用过的那一轮再进一次 advance：一条都不重做，账不变'


@case
def a_row_without_the_ledger_key_starts_from_an_empty_ledger():
    """开发期不写旧数据兼容：行上没有 delta_effects 这个键就是空账，条目重新尝试、靠副作用 id 撞回同一条。"""
    store, scene = world()
    coord = Coordinator(store)
    delta = {'pin': [PIN_OLD], 'affect': [AFFECT_ONE]}
    ep = decide_delta.apply(coord, episode(delta, scene, context=context_for(store, scene)))
    assert 'delta_applied' not in ep, '还在写那个整份布尔标记'
    row = {k: v for k, v in ep.items() if k != 'delta_effects'}
    again = decide_delta.apply(Coordinator(store, coord.lane), dict(row, context=context_for(store, scene)))
    assert len(affect_rows(store)) == 1, '同一份 delta 重放多记了一条心情（副作用 id 没撞回同一条）'
    assert memory(store, 'mu-old')['pinned'] is True
    assert len(again['delta_effects']) == 2, again['delta_effects']
    return True, '没有账的行走空账语义：重新尝试的条目靠 id 撞回同一条，不写第二份'


# ── 3) attach：图只看最后一次 DECIDE ──────────────────────────────────────────
@case
def later_decide_replaces_the_attached_picture():
    store, scene = world()
    first_pic, second_pic = pictures(store)
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': first_pic['artifact_id'], 'why': '先给他看这张'}]},
                                           scene, next_stage='recall', context=context_for(store, scene)))
    assert not ep['rejections'], ep['rejections']
    assert outbound_media.attachment_for_speak(ep)['artifact_id'] == first_pic['artifact_id']
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': second_pic['artifact_id'], 'why': '还是发那张'}]},
                                           scene, rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    attached = ep['delta_results']['attach']
    assert len(attached) == 1, '一轮至多一张（schema maxItems=1），旧的那张要整份换掉'
    assert attached[0]['artifact_id'] == second_pic['artifact_id'] and attached[0]['round'] == 1
    meta = outbound_media.attachment_for_speak(ep)
    assert meta['artifact_id'] == second_pic['artifact_id'] and meta['sha256'] == second_pic['sha256']
    return True, '最后一次 DECIDE 给了另一张：发那张，行上不留旧图'


@case
def refused_picture_in_the_later_round_leaves_no_stale_picture():
    store, scene = world()
    first_pic, _second = pictures(store)
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': first_pic['artifact_id'], 'why': '给他看这张'}]},
                                           scene, next_stage='recall', context=context_for(store, scene)))
    elsewhere = BlobStore(store).put(base.WEBP, base.DM_SCOPE, 'image', media_type='image/webp')
    offered = offer(store, scene)
    offered['items'] = [item for item in offered['items'] if item['artifact_id'] != elsewhere['artifact_id']]
    ctx = {'ref_index': ['mu-old', 'mu-new'], 'image_artifacts_from_program': offered}
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': elsewhere['artifact_id'], 'why': '换这张'}]},
                                           scene, rounds=1, context=ctx, row=ep))
    codes = [row['code'] for row in ep['rejections']]
    assert codes == ['ATTACH_ARTIFACT_NOT_IN_CONTEXT'], ep['rejections']
    assert outbound_media.attachment_for_speak(ep) is None, '第二轮的图被退回，却把第一轮那张无声发出去'
    return True, '第二轮的图被退回：这条不带图，原因在 rejections 里（不留下旧图冒充）'


@case
def a_later_round_without_attach_sends_no_picture():
    store, scene = world()
    first_pic, _second = pictures(store)
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': first_pic['artifact_id'], 'why': '给他看这张'}]},
                                           scene, next_stage='recall', context=context_for(store, scene)))
    assert outbound_media.attachment_for_speak(ep)['artifact_id'] == first_pic['artifact_id']
    ep = decide_delta.apply(coord, episode({'pin': [copy.deepcopy(PIN_NEW)]}, scene, rounds=1, row=ep))
    assert outbound_media.attachment_for_speak(ep) is None, '最后一次 DECIDE 没写 attach，图却还跟着走'
    assert 'attach' not in ep['delta_results'], ep['delta_results']
    assert memory(store, 'mu-new')['pinned'] is True, '摘图时把这一轮别的效果弄丢了'
    return True, '第二轮没提 attach：不发图，前一次那张不跟着走（发出去的正好是最后那份决策）'


@case
def a_round_with_no_optional_fields_at_all_sends_no_picture():
    store, scene = world()
    first_pic, _second = pictures(store)
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'attach': [{'artifact_id': first_pic['artifact_id'], 'why': '给他看这张'}]},
                                           scene, next_stage='recall', context=context_for(store, scene)))
    assert outbound_media.attachment_for_speak(ep) is not None
    ep = decide_delta.apply(coord, episode({}, scene, rounds=1, row=ep))          # 一个可选字段都没有
    assert outbound_media.attachment_for_speak(ep) is None, '整份决策里没有 attach，图却留在行上'
    return True, '第二轮整份决策里没有可选字段：一样不发图'


# ── 4) read 只验一遍 ──────────────────────────────────────────────────────────
def recall_branch(store, coord, ep):
    """coordinator.py 里 recall 分支那几行的同形复刻：那边也验一次 read、也追加拒收。"""
    reads = [(index, item) for index, item in enumerate((ep.get('decision_delta') or {}).get('read') or [])]
    if not reads:
        return ep
    valid, bad = decide_delta.validate_items({'read': [item for _index, item in reads]})
    documents, denied = decide_delta.read_sections(store, ep, valid.get('read', []),
                                                   ep['manifest'].get('session_class', 'public'))
    ep = dict(ep, documents=documents)
    return coord._update(ep, rejections=[*(ep.get('rejections') or []), *bad, *denied])


@case
def read_rejections_are_recorded_once_per_recall_round():
    store, scene = world()
    coord = Coordinator(store)
    delta = {'read': [{'doc': 'ledger'}, {'doc': 'ledger', 'sid': 'nope'}], 'pin': [PIN_OLD]}
    ep = decide_delta.apply(coord, episode(delta, scene, next_stage='recall', context=context_for(store, scene)))
    ep = recall_branch(store, coord, ep)
    read_rejections = [row for row in ep['rejections'] if row['field'] == 'read']
    assert [row['code'] for row in read_rejections] == ['ITEM_INVALID', 'DOC_SECTION_NOT_FOUND'], ep['rejections']
    assert len([row for row in ep['rejections'] if row['code'] == 'DOC_SECTION_NOT_FOUND']) == 1, ep['rejections']
    return True, 'recall 那一轮 read 只被验一遍：两条各一条拒收，没有重复'


@case
def read_is_still_validated_when_the_round_does_not_recall():
    store, scene = world()
    coord = Coordinator(store)
    ep = decide_delta.apply(coord, episode({'read': [{'doc': 'ledger'}]}, scene, next_stage='speak',
                                           context=context_for(store, scene)))
    assert [row['code'] for row in ep['rejections']] == ['ITEM_INVALID'], ep['rejections']
    return True, 'next=speak 那轮没人处理 read：apply 这边照旧验，不无声丢掉'


@case
def read_validation_handoff_matches_the_recall_branch_guard():
    for rounds, next_stage, expected in [(0, 'recall', True), (1, 'recall', True), (2, 'recall', False),
                                         (0, 'speak', False)]:
        ep = episode({'read': [{'doc': 'ledger', 'sid': 'x'}]}, base.scene_row('dm'),
                             next_stage=next_stage, rounds=rounds)
        assert decide_delta._recall_will_read(ep, ep['decision_delta']) is expected, (rounds, next_stage)
    return True, 'apply 跳过 read 的条件与 recall 分支的 rounds<2 判断一致（0/1 轮 recall 跳过，2 轮与 speak 不跳）'


# ── 5) 结构面：每条 apply 路径都有去重规则，id 都由语义键导出 ──────────────────
@case
def every_optional_field_has_a_dedup_rule():
    import io
    import pathlib
    covered = set(decide_delta.KEY_FIELDS) | set(decide_delta.LAST_ROUND_WINS) | {decide_delta.READ_FIELD}
    missing = [field for field in decide_delta.ORDER if field not in covered]
    assert not missing, '这些 apply 路径还没有去重规则：%s' % missing
    assert set(decide_delta.KEY_FIELDS) <= set(decide_delta.ORDER)
    assert decide_delta.LAST_ROUND_WINS == ('attach',)
    assert 'reason' in decide_delta.KEY_FIELDS['write_docs'], 'WRITE 阶段拿整条 item 当 intent：reason 是身份的一部分'
    assert 'reason' not in decide_delta.KEY_FIELDS['policy_set'], '参数改的是键与值，reason 只是措辞'
    assert 'delta_applied' not in io.open(pathlib.Path(base.ROOT) / 'src' / 'asuna'
                                          / 'decide_delta.py', encoding='utf-8').read().split('def apply(')[1], \
        '又写回那个整份布尔标记了'
    assert decide_delta.DELTA['properties']['attach']['maxItems'] == 1, 'attach 一轮一张是这套语义的前提'
    return True, 'ORDER 里每条路径都有语义键规则（attach 走后一次覆盖），attach 仍是 maxItems=1'


@case
def effect_ids_derive_from_the_item_and_not_the_round_position():
    import io
    import pathlib
    root = pathlib.Path(base.ROOT) / 'src' / 'asuna'
    texts = {name: io.open(root / (name + '.py'), encoding='utf-8').read()
             for name in ('decide_delta', 'affect', 'group_admin')}
    checks = [
        ("sha(canonical([ep['_id'], 'affect', key if key is not None else index, proposal_id]))", texts['affect']),
        ("[ep['_id'], 'affect_ops', key if key is not None else index]", texts['affect']),
        ("group_admin.queue(store, ep, index, item, key=key)", texts['decide_delta']),
        ("'group_action', key if key is not None else index", texts['group_admin']),
        ("'promote', key", texts['decide_delta']),
        ("f\"{ep['_id']}:write:{key}\"", texts['decide_delta']),
        ("f\"{ep['_id']}:policy_set:{key}\"", texts['decide_delta']),
        ("operation=f\"{ep['_id']}:WRITE:{round_no}:{index}\"", texts['decide_delta']),
    ]
    for needle, text in checks:
        assert needle in text, '副作用 id 又回到按轮次位置了：缺 ' + needle
    return True, '心情/修订/排队/记忆/文档那几处 id 都由语义键（或轮次+位置）导出，第二轮不会撞旧 id'


@case
def a_round_that_applied_nothing_does_not_swallow_the_next_round():
    store, scene = world()
    coord = Coordinator(store)
    # 第一轮只给了 read（recall 那一侧处理）：apply 这边什么也没办成，账是空的
    ep = decide_delta.apply(coord, episode({'read': [{'doc': 'ledger', 'sid': 'nope'}]}, scene,
                                           next_stage='recall', context=context_for(store, scene)))
    assert ep['delta_effects'] == [] and 'delta_applied' not in ep, list(ep)
    assert ep['rejections'] == [], ep['rejections']
    ep = decide_delta.apply(coord, episode({'pin': [copy.deepcopy(PIN_NEW)]}, scene, rounds=1, row=ep))
    assert not ep['rejections'], ep['rejections']
    assert memory(store, 'mu-new')['pinned'] is True, '上一轮什么都没办成，这一轮的新条目却被当成已生效'
    assert len(ep['delta_effects']) == 1, ep['delta_effects']
    return True, '空账不等于「都办过了」：下一轮的条目照旧生效（旧行判据看的是有没有这个键）'


@case
def a_refused_item_may_be_tried_again_in_a_later_round():
    store, scene = world()
    coord = Coordinator(store)
    ctx = {'ref_index': ['mu-old'], 'image_artifacts_from_program': offer(store, scene)}    # mu-new 不在可引用清单里
    ep = decide_delta.apply(coord, episode({'pin': [PIN_NEW]}, scene, next_stage='recall', context=ctx))
    assert [row['code'] for row in ep['rejections']] == ['PIN_MEMORY_NOT_IN_CONTEXT'], ep['rejections']
    assert ep['delta_effects'] == [], '被退回的条目不该进账'
    ep = decide_delta.apply(coord, episode({'pin': [copy.deepcopy(PIN_NEW)]}, scene, rounds=1,
                                           context=context_for(store, scene), row=ep))
    refused = [row for row in ep['rejections'] if row['code'] == 'PIN_MEMORY_NOT_IN_CONTEXT']
    assert len(refused) == 1 and refused[0]['index'] == 0, ep['rejections']   # 只剩上一轮那一条拒收
    assert memory(store, 'mu-new')['pinned'] is True, '上一轮被退回的那条，这一轮不能再试'
    assert len(ep['delta_effects']) == 1, ep['delta_effects']
    return True, '只有真办成的条目进账：上一轮被退回的那条，下一轮还可以再试一次'


def run_all():
    results = []
    for fn in CASES:
        try:
            ok, note = fn()
        except Exception as exc:                                  # noqa: BLE001
            import traceback
            ok, note = False, '%s: %s | %s' % (type(exc).__name__, exc,
                                               traceback.format_exc().splitlines()[-3])
        results.append((fn.__name__, ok, note))
    return results


if __name__ == '__main__':
    results = run_all()
    for name, ok, note in results:
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ' — ' + note if note else ''))
    failed = [name for name, ok, _note in results if not ok]
    print('DECIDE 多轮去重离线自检：%d/%d 通过' % (len(results) - len(failed), len(results)))
    if failed:
        print('失败：' + ', '.join(failed))
    sys.exit(1 if failed else 0)
