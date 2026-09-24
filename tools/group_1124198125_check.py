"""群 1124198125 接入自检：配置补丁能不能被真校验器收下，P5 开关是不是真打开。

跑法：

    # adapter 侧（在 integration_test 里跑，那里才读得到 /integration/config.json）
    python3 tools/group_1124198125_check.py --config /integration/config.json --adapter-src /app
    # 宿主侧（路由片段 + P5 开关；用真 prepare_channels／真 route_settings）
    python3 tools/group_1124198125_check.py --src <宿主 src 目录>

两侧都默认跑：缺输入的那一侧会明确 SKIP，不算通过也不算失败。
宿主侧不需要 Mongo／Windows：httpx／pymongo／msvcrt／deepseek_harness 这些只在 import 时碰一下的
模块用假模块顶掉，被检查的 prepare_channels／route_settings 是宿主源码本身。
"""
from __future__ import annotations

import argparse
import copy
import importlib.abc
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    for root in (os.path.dirname(os.path.dirname(HERE)), os.path.dirname(HERE)):
        if os.path.exists(os.path.join(root, 'config', 'group-1124198125.member-snapshot.json')):
            return root
    return os.path.dirname(os.path.dirname(HERE))


REPO = _repo_root()
GROUP = '1124198125'
BOT = '3768713357'
ROUTE_ID = 'group-' + GROUP
SCENE_ID = 'qq:%s:group:%s' % (BOT, GROUP)
OPERATOR = '673225019'
# 今天真实出现在这个群里、被 adapter 以 group_not_allowed 丢掉的发言人（宿主日志）
OBSERVED_SENDERS = ['3074196903', '1052754704', '3404612838', '673225019']
OTHER_CLOSED_GROUP = '227608960'      # 同期在刷、但没授权的群，补丁不该顺手打开它
STUB_ROOTS = {'httpx', 'bson', 'pymongo', 'msvcrt', 'deepseek_harness', '_winapi',
              'win32api', 'win32file', 'pywintypes', 'winreg'}

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok)))
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, (' — ' + detail if detail and not ok else '')))


def skip(name, why):
    print('SKIP %s（%s）' % (name, why))


def install_stubs():
    class Any:
        def __init__(self, name='Any'):
            self._name = name

        def __getattr__(self, item):
            return Any(item)

        def __call__(self, *args, **kwargs):
            return Any()

        def __iter__(self):
            return iter(())

        def __mro_entries__(self, bases):
            return (object,)

    class Dummy(types.ModuleType):
        def __getattr__(self, name):
            value = Any(name)
            setattr(self, name, value)
            return value

    class Loader(importlib.abc.Loader):
        def create_module(self, spec):
            return Dummy(spec.name)

        def exec_module(self, module):
            pass

    class Finder:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in STUB_ROOTS:
                return importlib.util.spec_from_loader(fullname, Loader())
            return None

    if not any(isinstance(finder, Finder) for finder in sys.meta_path):
        sys.meta_path.insert(0, Finder())


def merge_patch(base, patch):
    """RFC 7386 最小实现：对象逐层合并，数组整份替换（正好是这份补丁需要的语义）。"""
    if not isinstance(patch, dict):
        return patch
    out = dict(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        out[key] = merge_patch(out.get(key), value) if isinstance(value, dict) else copy.deepcopy(value)
    return out


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


# ── adapter 侧：真 qqadapter 校验器 ─────────────────────────────
def check_adapter(config_path, adapter_src, snapshot):
    if not os.path.exists(config_path):
        return skip('adapter.*', '读不到 %s：这一侧要在 integration_test／integration_start 里跑' % config_path)
    if adapter_src and os.path.isdir(os.path.join(adapter_src, 'qqadapter')):
        sys.path.insert(0, adapter_src)
    try:
        from qqadapter import config as adapter_config
    except Exception as exc:
        return skip('adapter.*', '导不到 qqadapter（--adapter-src 指到 adapter 开发目录）：%s' % exc)

    raw = load_json(config_path)
    before = adapter_config.Config(raw, config_path)
    check('adapter_closed_before_patch',
          before.route_for_group(GROUP) is None and GROUP not in before.allowed_groups,
          '没打补丁时这个群就该是关着的')

    patch = load_json(os.environ.get('P5B_ADAPTER_PATCH'))['adapter']
    merged = merge_patch(raw, {'adapter': patch})
    try:
        after = adapter_config.Config(merged, config_path)
    except Exception as exc:
        check('adapter_patch_is_valid_config', False, str(exc))
        return
    check('adapter_patch_is_valid_config', True)

    expected_senders = [row['user_id'] for row in snapshot['members'] if row['user_id'] != BOT]
    route = after.route_for_group(GROUP)
    check('adapter_route_opened', route is not None and route.route_id == ROUTE_ID, str(route))
    if route is None:
        return
    check('adapter_route_shape', route.message_type == 'group' and route.target_type == 'group'
          and route.target_id == GROUP and route.sender_id is None)
    check('adapter_members_are_snapshot', sorted(route.allowed_senders) == sorted(expected_senders)
          and route.member_count == snapshot['allowed_sender_count'],
          '路由成员与真群快照不一致：%d vs %d' % (route.member_count, snapshot['allowed_sender_count']))
    check('adapter_self_not_a_sender', BOT not in route.allowed_senders)
    check('adapter_observed_senders_accepted',
          all(after.is_group_member(GROUP, sender) for sender in OBSERVED_SENDERS),
          '今天真发过言的人里有不在快照的')
    check('adapter_only_this_group_opened',
          set(after.allowed_groups) == set(before.allowed_groups) | {GROUP}, str(after.allowed_groups))
    untouched = [rid for rid in before.routes if rid != ROUTE_ID]
    check('adapter_other_routes_untouched',
          all(after.routes[rid].allowed_senders == before.routes[rid].allowed_senders
              and (after.routes[rid].target_type, after.routes[rid].target_id) ==
              (before.routes[rid].target_type, before.routes[rid].target_id) for rid in untouched),
          '原有路由被改了')
    check('adapter_other_group_still_closed', after.route_for_group(OTHER_CLOSED_GROUP) is None)
    described = after.describe()
    check('adapter_describe_lists_five_groups',
          ROUTE_ID in described and described.count(',') >= 4 and GROUP in described, described)


# ── 宿主侧：真 prepare_channels + 真 route_settings ───────────────
class FakeCollection:
    def __init__(self):
        self.rows = {}

    def find_one(self, query, projection=None):
        return copy.deepcopy(self.rows.get(query.get('_id')))

    def insert(self, doc):
        self.rows[doc['_id']] = copy.deepcopy(doc)


class FakeDb:
    def __init__(self):
        self.identities = FakeCollection()
        self.scenes = FakeCollection()


class FakeStore:
    def __init__(self, config):
        self.config = config
        self.db = FakeDb()
        self.heads = {}
        self.puts = []

    def put(self, collection, doc, expected=None, stream=''):
        self.puts.append((collection, doc['_id']))
        getattr(self.db, collection).insert(doc)
        return doc

    def init_head(self, entity, scope, content, sources):
        self.heads[entity + '|' + scope] = content
        return {'_id': entity}


def check_host(src_dir, fragment_path, snapshot):
    if not os.path.isdir(src_dir):
        return skip('host.*', '找不到宿主 src 目录 %s' % src_dir)
    install_stubs()
    sys.path.insert(0, src_dir)
    try:
        from asuna import host, proactive
    except Exception as exc:
        return skip('host.*', '导不到宿主模块（假模块没顶住）：%s' % exc)
    # 宿主以仓库根为工作目录启动，相对 workspace 才按同样方式 resolve；
    # 自检里可以把它换到一个可写副本（--src /data/host/src），检查逻辑本身没改。
    host_root = os.path.dirname(os.path.abspath(src_dir))
    fragment = load_json(fragment_path)
    route = {key: value for key, value in fragment.items() if not key.startswith('_')}
    expected_senders = [row['user_id'] for row in snapshot['members'] if row['user_id'] != BOT]

    check('host_route_keys_are_known',
          set(route) <= {'scene_id', 'target', 'operator_sender_id', 'members', 'proactive'},
          str(sorted(route)))
    check('host_scene_id_matches_group', route.get('scene_id') == SCENE_ID
          and route['target'] == {'type': 'group', 'id': GROUP})
    check('host_members_are_snapshot', sorted(route['members']) == sorted(expected_senders),
          '宿主 members 与真群快照不一致')
    check('host_person_ids_bound_to_sender',
          all(grant['person_id'] == 'qq:' + sender for sender, grant in route['members'].items()))
    check('host_operator_is_a_member', route.get('operator_sender_id') in route['members'])

    local_workspace = os.path.join(host_root, '.runtime', 'local-chat')
    config = {'chat': {'scene_id': 'local-chat', 'workspace': local_workspace},
              'channels': {'qq': {'token': 'x' * 32, 'account_id': BOT,
                                  'routes': {ROUTE_ID: route}}}}
    store = FakeStore(config)
    previous_cwd = os.getcwd()
    os.chdir(host_root)
    try:
        scenes = host.prepare_channels(store)
        error = ''
    except Exception as exc:
        scenes, error = None, '%s: %s' % (type(exc).__name__, exc)
    finally:
        os.chdir(previous_cwd)
    check('host_prepare_channels_accepts_route', scenes == {SCENE_ID}, error or str(scenes))
    if scenes:
        scene = store.db.scenes.rows.get(SCENE_ID)
        check('host_scene_record_created',
              scene and scene['kind'] == 'group' and scene['channel_id'] == 'qq'
              and sorted(scene['members']) == sorted('qq:' + s for s in expected_senders), str(scene))
        check('host_identities_created',
              len(store.db.identities.rows) == len(expected_senders)
              and all(row['account_id'] in expected_senders for row in store.db.identities.rows.values()))

    # P5 触发开关：用宿主自己的 route_settings 读一遍，不自己解释配置
    scene_doc = {'_id': SCENE_ID, 'kind': 'group', 'channel_id': 'qq', 'policy_epoch': 1}
    limits = proactive.route_settings(config, scene_doc)
    check('p5_switch_is_on', limits.get('enabled') is True and limits.get('why') == 'enrolled', str(limits))
    check('p5_switch_values_are_read',
          limits.get('probe_interval_seconds') == route['proactive']['probe_interval_seconds']
          and limits.get('min_interval_seconds') == route['proactive']['min_interval_seconds']
          and limits.get('max_per_hour') == route['proactive']['max_per_hour']
          and limits.get('dense_max_gap') == route['proactive']['dense_max_gap_seconds']
          and limits.get('merge_window_seconds') == route['proactive']['merge_window_seconds']
          and limits.get('utc_offset_minutes') == route['proactive']['utc_offset_minutes']
          # route_settings 把钟点换算成本地分钟：23:00→1380、08:00→480
          and limits.get('quiet_windows') == [(23 * 60, 8 * 60)], str(limits))
    unenrolled = proactive.route_settings(
        {'channels': {'qq': {'routes': {ROUTE_ID: {k: v for k, v in route.items() if k != 'proactive'}}}}},
        scene_doc)
    check('p5_rollback_is_deleting_the_block',
          unenrolled.get('enabled') is False and unenrolled.get('why') == 'not_enrolled', str(unenrolled))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/integration/config.json')
    parser.add_argument('--adapter-src', default=os.environ.get('P5B_ADAPTER_SRC', ''))
    parser.add_argument('--src', default=os.environ.get('P5B_HOST_SRC') or os.path.join(REPO, 'src'))
    parser.add_argument('--fragment', default=os.path.join(REPO, 'config', 'group-1124198125.host-route.fragment.json'))
    parser.add_argument('--snapshot', default=os.path.join(REPO, 'config', 'group-1124198125.member-snapshot.json'))
    args = parser.parse_args()
    os.environ.setdefault('P5B_ADAPTER_PATCH',
                          os.path.join(REPO, 'config', 'group-1124198125.integration-adapter.patch.json'))
    snapshot = load_json(args.snapshot)
    check('snapshot_matches_platform',
          snapshot['group_id'] == GROUP and snapshot['member_count'] == len(snapshot['members'])
          and snapshot['allowed_sender_count'] == snapshot['member_count'] - 1
          and BOT not in [row['user_id'] for row in snapshot['members']
                          if row['user_id'] != BOT], str(snapshot.get('member_count')))
    check_adapter(args.config, args.adapter_src, snapshot)
    check_host(args.src, args.fragment, snapshot)
    passed = sum(1 for _, ok in RESULTS if ok)
    print('\n%d/%d 通过（群 %s，%d 名成员）' % (passed, len(RESULTS), GROUP, snapshot['allowed_sender_count']))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
