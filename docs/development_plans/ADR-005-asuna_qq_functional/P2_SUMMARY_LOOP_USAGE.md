# ADR-005 P2 第一片：私聊摘要接进下一轮与关系理解（小满提交，随 diff 一起审阅）

把已经存在的"自动触发→来源→保存"接到"下轮使用"上：后台摘要下一轮能被角色认出来是什么，
也能被程序登记成这次关系理解的来源。不新增集合、不新增状态服务、不多调一次模型、不碰 QQ。

## 先记录复核到的真实链路（改动前）

| 位置 | 实际行为 |
|---|---|
| `dialogue_summary.py` | 只绑一个 dm scene；`initialize` 记 `summary_start_seq` 不补历史；`_pending` 取 `scene_seq>` 起点、未进过批次、入站或已送达出站，`limit=8`；崩溃留下的"摘要已存但来源没标"先补标记再选新批；触发＝待处理 ≥4 条，或 ≥2 条且最早一条安静 ≥120s；lane 锁 + 成功后 `next_attempt=+60s`；产出 `kind='dialogue_summary'`、`epistemic_type='derived_summary'`、带 `source_event_ids`/`source_window`/`generated_at` 的 memory_unit。 |
| `memory_indexer.py` | 每 2s 轮转 scene_ids：先 `MemoryService.chunk` 再 `retrieval.index_pending(scope,epoch)`（摘要 `embedding_status='PENDING'` 就是被这一步捞走，下一轮才可向量召回），只有游标落在 summarizer 那个 scene 时才 `tick()`。 |
| `retrieval.py` | `search` 里非 monologue 条目若 `source_event_ids` 与最近尾巴相交 → `source_in_recent_tail` 先排除；embedding 没好的走 `pending_backread`。所以摘要在它盖的原文还留在最近 12 条里时不会重复出现，滑出尾巴才可召回——这是去重不是漏。 |
| `context.py` | 读 `relationship:<person>` head 进 `context['relationship']`；`memories` 走 `facts` 投影（原来没有 `kind`/`source_window`/`generated_at`）；`memory_source_rules` 只解释 reported_speech／public_statement／character_interpretation，**没有 derived_summary 这一条**；workspace 模式给 `understanding_update_from_program`。 |
| `memory.py` | `commit_understanding` 只写 `relationship:<episode.person_id>`；来源只允许 `episode['monologue_refs']` 且要求 `episode_id==本 episode`；base 取 `manifest.relationship_revision`；`Store.mutate` 走 CAS、来源根遍历、`NO_NEW_SOURCE_EVENTS`。后台摘要没有 `episode_id` → **永远进不了来源**。 |
| `coordinator.py`／`chat.py` | `reflect_understanding=true` → REFLECT → `commit_understanding`；`advance` 只捕 `ProtocolFailure`，`Denied`/`Conflict` 逃到 chat worker → 整轮 `FAILED_RUNTIME`、公开那句不说。 |

结论：链路断在两处——摘要写出来了但下一轮认不出它是什么，以及它永远不能当关系理解的来源；
顺带一个真缺陷：`mutate` 的预期冲突会把整轮打死。

## 这次改了什么（两处，共 40 行）

| 文件 | 内容 |
|---|---|
| `src/asuna/memory.py` | `commit_understanding` 的来源改走新增 `_understanding_sources`：本 episode 独白（原检查原样保留）+ 本轮 `manifest.selected` 里出现过、且**现在重读**仍是当前 scope/纪元 active、`kind` 在 `UNDERSTANDING_AUTO_SOURCES=('dialogue_summary',)` 白名单里的条目。`mutate` 的 `Conflict` 不再外逃，降级成审计过的 `{'state':'NOT_COMMITTED','reason':…,'body':…}`。 |
| `src/asuna/context.py` | `facts` 投影加 `kind`/`source_window`/`generated_at`；排序表把 `derived_summary` 显式写在 public_statement 同层（行为同旧默认值，只是不再靠默认）；`memory_source_rules` 补一句 derived_summary 的读法（转述不是新经历、不等于谁确认过、与本人较新陈述冲突以陈述为准、要细节回读来源）；`understanding_update_from_program.route` 补来源口径。 |

未动：`dialogue_summary.py`、`memory_indexer.py`、`retrieval.py`、`state.py`、`coordinator.py`、
提示词、生产配置。没有新集合、新端口、新公开接口，也没多一次模型调用。

## 正式路径（没换入口）

后台：indexer 轮转 → `summarizer.tick()` → 摘要落 `memory_units` → 下一轮 indexer 把它 embed。
读取：`ContextBuilder.prepare` → `memories` 里那条带 `kind='dialogue_summary'`、`source_window`、
`generated_at`、`source_event_ids`，旁边就是程序写的读法说明。
写入：角色 DECIDE `reflect_understanding=true` → REFLECT 正文 → `commit_understanding` →
`relationship:<当前说话人>` 新版本，`source_ids=[独白, 摘要]`，`processed_source_ids` 落到真实
`messages` 行；`auto_source_ids` 与结果一起进 `understanding.result` 审计，也随
`程序已提交的结果` 进 SPEAK 阶段。

## 语义与边界

- 摘要能不能当来源，不看谁写的，看**本轮真给角色看过没有**（`manifest.selected`）+ 现在重读
  仍 active/同 scope/同纪元 + kind 在白名单。角色自己能写的条目（body/familiarity/…）不在这个口子。
- 三种不提交都留下原因：`NO_CHANGE`（不更新或同文）、`NOT_COMMITTED: NO_NEW_SOURCE_EVENTS`
  （这批原文已进过这条关系）、`NOT_COMMITTED: BASE_REVISION_STALE`（头版本被推前）。
  后两种不抛异常、不动头版本、正文进审计，本轮照常说活。
- `UNDERSTANDING_SOURCE_NOT_CURRENT`／`EMPTY_UNDERSTANDING`／scope-纪元变更仍是 `Denied`。
- 多主体：这一片仍只写当前说话人的关系（见下"没做"）。

## 检查证据（本机已跑，代码与用例都是小满写的）

```
$ python3 tools/p2_offline_check.py            # 当前工作树
P2 离线自检：12/12 通过
$ python3 tools/p2_offline_check.py --baseline # 换回 P1C 基线的 memory/context 再跑
P2 离线自检：4/12 通过
```

基线那 4 条过的就是回归护栏（`w4` 独白不是本 episode 仍拒、`w7` 不更新／同文／空正文、
`r3` 排序、`r4` 关系读取口径）；其余 8 条在基线上是**真失败**：

- `w1` 基线 `source_ids` 只有独白 → 摘要进不了关系版本；
- `w5`／`w6` 基线直接抛 `Conflict: NO_NEW_SOURCE_EVENTS`／`BASE_REVISION_STALE`（就是会打死整轮那两个）；
- `w8` 基线 `processed_source_ids` 里没有摘要盖的两条原文；
- `r1` 基线 `context['memories']` 里没有 `kind`；`r2` 基线 `memory_source_rules` 不认 derived_summary。

离线那份假集合真算过滤／投影（含排除式投影）／排序／CAS／来源根遍历；被假掉的只有
import 期的第三方（`bson`／`pymongo`／`httpx`／`jsonschema`／`msvcrt`+`_winapi`，只在装不上时才假）。
`Store.put`／`audit`／`head`／`mutate`、`MemoryService.commit_understanding`、`ContextBuilder.prepare`
跑的都是仓库里那份真代码。

## 操作员那侧的定向检查（本开发沙箱跑不了：无 Mongo、无 config/local.json、无 pytest）

```
pytest tests/test_p2_summary_loop.py -q        # ASUNA_P2_CONFIG 默认 config/local.json，缺失即报错
```

固定库 `asuna_v2_test_p2_host_20260924`（`ASUNA_P2_DATABASE` 可换同等受限库），不依赖 ADR-001
seed 夹具。预期：5 条全过，其中 `test_offline_cases_all_pass` 会把假集合那 12 条再跑一遍。
部署面：`src/asuna/memory.py`、`src/asuna/context.py` 两个文件；其余都是新增测试／工具／说明。

## 没做（有意留在 P2 后面，不是遗漏）

- **多主体映射**：摘要里提到的第三方仍只写进当前说话人的关系正文。要做的是把 REFLECT 输出
  拆成按 person 的有界条目再分别 `mutate`，那是提示词＋封套的改动，不该塞进这一片。
- 五档关系档位（familiarity/trust/closeness/tension）仍不由这条路径自动动；`proposal` 那条老路没碰。
- 群场景摘要：`DialogueSummarizer` 仍只绑一个 dm scene；`memory_indexer` 的 scene 轮转与
  `scene_id == summarizer.scene_id` 这个门槛没动。
- 摘要 embedding 仍依赖 indexer 下一轮（≈2s）才完成；没加同步 embed。
- 本开发副本没有 `config/prompts/` 与 `fixtures/world.json`，所以 REFLECT 阶段实际提示词
  （`stage_reflect.md`）长什么样没核实——来源登记是程序做的，不依赖提示词，但宿主上如果那份
  提示词写了"只能引用独白"之类，需要同步一句。这是环境缺口，不是本片代码问题。

## 两个小口径，写清楚免得日后当 bug 提

- `next=recall` 那一轮召回来的条目不会进 `manifest.selected`（那是首轮 manifest），所以只有
  首轮真展示过的摘要会被自动登记成来源。偏保守：宁可少登记，不替角色猜它看过什么。
- `tools/p2_apply_patch.py` 是一次性落地器：现在再跑会报 `FAIL …（原文命中 0 次）`，那就是
  "已经应用过"的意思，不是坏了。`tools/p2_make_patch.py` 重新生成审阅用的
  `/task/P2_SUMMARY_LOOP.patch`（8 个文件、11 处 hunk，可 `patch -p1`）。

## 本片交付清单

| 类型 | 文件 |
|---|---|
| 改（要部署） | `src/asuna/memory.py`、`src/asuna/context.py` |
| 新增检查 | `tests/p2_summary_loop_cases.py`（12 条，本机 12/12）、`tests/test_p2_summary_loop.py`（5 条，待操作员跑） |
| 新增工具 | `tools/p2_offline_check.py`（含 `--baseline` 反证）、`tools/p2_apply_patch.py`、`tools/p2_make_patch.py` |
| 说明 | 本文；审阅用 diff：`/task/P2_SUMMARY_LOOP.patch` |
