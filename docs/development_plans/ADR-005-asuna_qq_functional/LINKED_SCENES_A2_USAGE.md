# 跨场景只读联动（A2）· 落法、边界与回滚

日期：2026-09-25。依据：《跨场景上下文同步_方案报告_2026-09-25》A2（读权限由宿主配置授予，
不做 adapter 镜像转发，也不做 B 方案的定向转发）。这一份只写**已经落进代码的那一半**。
状态：已发布并在 2026-09-25T08:41:08Z 激活，真库测试 30 项通过，落地后核实见下面第三节。

## 一句话

本机场景（`local-dm`）可以**只读**她 owner 在 QQ 私聊里说过的原话；两个入口在配置里被认定为
同一个人，所以关系与偏好只维护一份。写、出站、场景成员资格、历史行上的 `author` 一个字都没放宽。

## 开与关（配置是唯一真相）

写在 `config/asuna-channel.local.json` 顶层（`config/local.json` 顶层同样有效，`config.load`
原样带进 `store.config`，不新增校验器）。这两个文件都在发布器的 `PROTECTED` 名单里，
开发侧改不动也带不进发布，**启用这一步只能操作员在已安装那份里加**：

```json
  "context_links": {"local-dm": ["qq:3768713357:dm:673225019"]},
  "canonical_persons": {"qq:673225019": "local-user"}
```

- `context_links` 是**有向边**：左边能读右边，反过来读不到。不做通配（`*` 照实丢掉），
  一条边最多带 8 个场景（`scene_links.MAX_LINKS`），超了照实截断。
  通道路由里也可以写 `read_scenes`，语义等同于给该路由的 `scene_id` 挂同一条边。
- `canonical_persons`：键是别名（历史行里照旧写这个 `person_id`），值是 canonical person_id。
  归一只作用在两处——按人过滤把同一个人的其他入口算进来；关系／偏好状态落在 canonical 那一份。
- **回滚 = 删这两个键**。库里那两个派生投影（`scenes.readable_scenes`、
  `identities.canonical_person_id`／`alias_of`）只是启动时写的一次性副本，为的是让人看得见联动到哪；
  读路径每次现算自配置，所以删键之后就不联动，不会出现「库里还认、配置已经不认」。
  两点口径要说清：配置在启动时加载，**删键要重启才生效**；重启也**不会**把那两个派生键从文档里撤掉
  （自检 c11 钉的就是「投影留在库里、读路径不认它」），想清干净就手工 unset 那一个键。

## 放宽了什么

| 位置 | 行为 |
| --- | --- |
| `context.prepare` 的 `delivered_history` | 联动场景最近若干条按**各自有效时间**归并进同一个窗口；行上带 `scene_id`，另给一条 `linked_scenes_from_program` 说明「那不是这个场景的新输入」 |
| `query_authorized_history` | 范围＝任务场景＋配置给它挂的只读场景；命中行首带各自的场景号；`scope.linked_scenes`／`same_person_ids` 照实报出 |
| `digest_authorized_discussion` | 参与者按 canonical person 归并（同一个人不在一份整理里裂成两个），条目带各自 `scene_id`；reply 链跨那条边时也读得到，`target_in_scope` 不再恒 false |
| 语义召回（`Retrieval.search`） | 联动场景的记忆可与本场景一起被召回；`linked_scopes` 进缓存键，「联动着读」与「只读本场景」不互相顶缓存 |
| 关系／偏好状态 | 落在 canonical 那一份 head；别名场景这一轮可以写那一份，来源仍只许 `global-safe`、目标 scope 或本轮授权联动的 scope（`Store.mutate(..., linked_scopes=...)`） |

## 没放宽什么

- 写权限、出站投递、场景成员资格、`authorize` 的判定：一个字没改。
- 历史消息行的 `author`／`platform`／身份块：不改写、不回填。归一只发生在查询过滤与状态落点上。
- 工具参数换不了范围：`readable` 由任务绑定的场景＋配置算出，游标指纹把它算进去——
  换了联动集合，旧游标会被 `HISTORY_CURSOR_FILTER_MISMATCH` 拒掉，不会借到另一条边上去。
- 全局人格（`persona:*|global-safe`）与别的 scope 的跨场景写：仍然 `SCOPE_PROMOTION_DENIED`。
  只有 `relationship:`／`overlay:`／`scene_affect:` 且 `request_scope` 确实在本轮授权联动集合里才放行。

## 翻页口径（跨场景之后必须知道的一件事）

`scene_seq` 是每个场景自己的序号，跨场景不可比；同一秒两个场景各有一条 `scene_seq=20` 是真的会发生。
所以游标决胜位从 `(时间, scene_seq)` 变成 `(时间, scene_seq, scene_id)` 三位，归并排序同一位序。
只带两位的旧游标照旧能用（不加第三位条件）；少这一位就会在同一秒两条上重一条或漏一条。
这一位**只在联动真正生效时起作用**：单场景下 `(时间, scene_seq)` 本来就是全序，加了也不改行为。

启用现场与地板保护的经过：`ARCHITECT_BLOCKER-2026-09-25-A2-FLOOR.md`。

## 怎么验

```
python3 tools/linked_scenes_offline_check.py     # 11 项，无 Mongo／无 pytest／不联网
python3 tools/p1c_offline_check.py               # 18 项（同一道围栏在单场景下逐字不变）
python3 tools/p3_offline_check.py                # 38 项（夹具带真 scene_links.py 装载真 context）
```

离线那 11 项钉的是：边是有向的、`*` 不当通配、超上限照实截断；跨场景读得到且单向；同一秒两条
跨场景命中翻页不重不漏；按 canonical person 过滤捞得到别名入口的原话且行上 `author` 未改写；
游标绑定发放它的联动集合；整理里参与者归并成一个且覆盖范围报出读了哪几个场景；主题整理能沿
跨场景的 reply 链走完；`context` 里联动行按有效时间归并（出站那条只有按 `sink_receipts` 算时间
才会排在对的位置）；**删掉配置键之后一切回到改动前**；关系记录只有一份且来源越界照实被拒；
启动投影只是可观察副本且删键即回滚。

真 Mongo 那一层（真 CAS、真集合、真 `$vectorSearch`）由操作员跑：

```
python3 -m pytest tests/test_history_query.py tests/test_discussion_digest.py tests/test_understanding.py
```

## 落地后核实（2026-09-25 08:41:08Z 激活之后实测）

- **真库测试 30 项全过**：`test_history_query.py` 13、`test_discussion_digest.py` 15、
  `test_understanding.py` 2 → `30 passed, 170 warnings in 24.79s`（win32 / Python 3.12.10 /
  pytest-9.0.2）。170 条 warning 全来自 `history_query.py:773` 那句既有的 `datetime.utcnow()`
  弃用告警，与本次改动无关，留到下一次连带测试的改动一起换 `datetime.now(datetime.UTC)`。
- 发布回执 `state=ACTIVE`、`activated_at=2026-09-25T08:41:08.214933+00:00`；启动探针 exit 0。
- 启动投影确实写进了真库：`scenes.local-dm.readable_scenes=["qq:3768713357:dm:673225019"]`
  （`revision` 18→19），`identities.qq:673225019` 带 `alias_of`／`canonical_person_id=local-user`，
  `identities.local-user` 带 `canonical_person_id=local-user`；QQ 私聊场景文档**没有**
  `readable_scenes`（边有向，反向没被偷偷打开）。
- 在本机场景用正常工具查「贴贴」能命中 `qq:3768713357:dm:673225019#24`
  （`in-ep-66e41ac0a0d5430c44d97e0fd44451e7`，`author=qq:673225019`，`time_source=messages.occurred_at`），
  `scope.linked_scenes`／`same_person_ids=[local-user, qq:673225019]` 照实报出，行首带来源场景号。
- 那条 QQ 原话在 `messages` 里仍只有一行：A2 不产生镜像行，所以没有重复记录、没有双唤醒。
- 库里仍留着 A2 之前那条 `relationship:qq:673225019|scene:qq:3768713357:dm:673225019` head
  （这次不迁数据）。从现在起同一个人的关系／偏好写 `relationship:local-user|scene:local-dm` 那一份；
  旧 head 当历史，要不要合并是另一个决定。

## 已知边界

- 只做了这一条边：`local-dm ← qq:3768713357:dm:673225019`。群场景没有联动边，也不自动反向。
- 联动读的是**已入库**的原话；QQ 那边新说的话要先进 `messages` 才读得到（不引入第二条同步通道）。
- 一条边带多了场景会直接推高每轮上下文成本，所以有 `MAX_LINKS=8` 的硬上限，不做通配。
- 每轮上下文里联动行实际排在哪，落在 `context_projection_runs`，开发侧读不到那个集合；
  跨场景归并的行为由离线 c8 钉住，运行时表现留一轮自然对话观察。
