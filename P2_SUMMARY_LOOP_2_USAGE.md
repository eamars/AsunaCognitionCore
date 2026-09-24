# ADR-005 P2 第二片：触发点自适应 + 归属与更正（使用说明）

补丁 `P2_SUMMARY_LOOP_2.patch`（14 个文件）基于第一片 `P2_SUMMARY_LOOP.patch` 的状态：

```bash
patch -p1 < P2_SUMMARY_LOOP.patch        # 第一片：摘要能被下一轮认出、能登记成关系来源
patch -p1 < P2_SUMMARY_LOOP_2.patch      # 这一片：什么时候整、谁说的、被推翻怎么办
```

两片都要，只打第二片会在 `memory.py` 的上下文行上冲突（第一片已经改过那一行）。
补丁的旧内容取自快照 `/task/p2-pre-slice2`（= P1-c 交付状态 + 第一片 patch 的真实产物，
tests／tools 都在里面），不是回忆拼的；`tools/p2b_make_patch.py` 就是按那份快照生成补丁的。
新增：`src/asuna/summary_trigger.py`、`src/asuna/summary_attribution.py`、
`tools/p2b_probe_loop.py`、`tools/p2b_edge_probe.py`；改：`dialogue_summary.py`、`memory.py`、
`context.py`、`memory_indexer.py`、`host.py` 与 P2 那三份测试／夹具。

## 1. 触发点从哪来（src/asuna/summary_trigger.py）

不再用写死的「≥4 条或安静 120 秒」，改成从**本场景已经落库的行**算两条线：

- 停顿线：对方消息之间的间隔取中位数，加 2×MAD（抗离群），钳在 20 秒～6 小时；
  样本不足 3 个就退回先验值（安静 120 秒或攒 3 条），同部署别的场景已经实测出节奏时
  用 `pooled_prior` 顶掉先验值（只借同一种 kind，不跟自己借）。
- 典型条数：按这条停顿线把历史切成一簇一簇，取簇大小的中位数。

信号只有五个，每个都能回读到具体哪几行：`pause_anomalous`（安静超过停顿线）、
`window_full`（攒够 8 行，结构性上限）、`cluster_complete`（够一簇且这句不像还在说）、
`pending_stale`（最老那条等过线）、`closure_cue`（收尾线索）。除 `window_full` 外都要先过
Settle 闸：最后一条安静到「半条停顿线」以上才算这阵话说完——快群里一问一答三条就整理，
半小时一条的私聊不会为一句「在吗」惊动模型。常数只剩观察预算与兜底上下界，
时间口径复用 `history_query` 那三支（入站 `occurred_at`、出站行内 `receipt_at`、
再退 `sink_receipts.received_at`），线索词复用 `discussion_digest` 那份。

## 2. 归属与更正（src/asuna/summary_attribution.py）

- `participants`／`source_by_speaker`／`speakers` 全部由真实行的 `author` 算出；行上缺 `author`
  就记进 `unknown`，不替角色猜「这句是谁说的」。
- 更正只认结构线索，认定依据照实写：`reply_link`（宿主绑了消息 `_id`）、
  `reply_link_by_platform_id`（只有平台消息 ID）、`same_author_previous_in_batch`（没引用结构、
  但明说「刚才那句」，低置信兜底）、`self_reference_to_self`（引用的是自己这条）、
  `reply_link_unresolved`／`self_reference_unresolved`（引用带在行上但在本场景本纪元落不到行）。
  落不到行时 `corrects` 就是 `null`：只记「有人更正了」，不替角色指哪句被推翻，也不跨场景乱认。
- 更正指向的原文若已被更早那条摘要盖住，那条摘要**只追加** `corrected_by`／`corrected_at`，
  正文一个字不改；同一批里的更正由这条摘要自己承担（`in_batch=true`，不回标）；
  已 tombstone 的条目不回标；CAS 冲突就跳过（下一批还会再标），不打断本轮。
- 来源登记多一道复核（memory.py `_understanding_sources`）：摘要只有在 `participants` 覆盖当前
  说话人时才算这个人的证据，结果里 `auto_source_skipped` 带原因；被更正过的记进
  `auto_stale_source_ids`。旧条目没有 participants 的回读 `source_event_ids` 的作者，读不到就
  照实说 `sources_unreadable`，不默认放行。
- 展示腿（context.py）把 `participants`／`source_by_speaker`／`attribution`／`corrected_by` 一并给出，
  `memory_source_rules` 与 understanding route 写清读法：转述只在盖到本人时才算这个人的证据，
  `corrected_by` 非空时以后来的原话为准。

## 3. 群场景接线

- `DialogueSummarizer` 支持多场景（`scene_ids`，保留 `scene_id` 兼容），`initialize()`／`tick(scene_id)`
  逐场景；每个场景独立失败退避（30 秒起指数，上限 900 秒——这是错误处理，不是触发条件）。
- `MemoryIndexer` 收 `summary_scenes`，轮转到哪个场景就判断哪个场景；`host.py` 传
  `[本机场景, *全部已授权群场景]`。旧参数 `summary_scene` 仍能用。
- 落库条目新增 `participants`／`source_by_speaker`／`attribution`／`trigger`；崩溃恢复、
  来源标记与 `summary_start_seq` 口径不变。
- 送进模型的顺句标签取身份表 `display_name`，**两个 person_id 同名时标签各自追加 person_id**
  （`小舟（qq:B1）`／`小舟（qq:C1）`）：宿主身份表按 (platform, account_id) 唯一，同名是常态，
  标签撞车会让模型把两个人顺成一个。身份表没这个人就退回 person_id，不编显示名。

## 4. 怎么跑

```bash
python3 tools/p2_offline_check.py            # 当前工作树：24/24
python3 tools/p2_offline_check.py --baseline # 换回第一片基线：16/24（8 条真失败）
python3 tools/p2_offline_check.py --baseline p1c   # 换回 P1C 基线：8/24
python3 tools/p2b_probe_loop.py              # 小探针：闭环每一步的中间量（21 项）
python3 tools/p2b_edge_probe.py              # 边界自测：六组极端现场（42 项）
```

三者都是纯离线（假集合真算，不需要 pymongo／pytest／网络／模型）。

操作员那侧（真 Mongo、不调模型、不发 QQ）：

```bash
ASUNA_P2_CONFIG=config/local.json pytest -q tests/test_p2_summary_loop.py   # 13 条
```

固定授权库 `asuna_v2_test_p2_host_20260924`（可用 `ASUNA_P2_DATABASE` 换同等受限的库）；
夹具在用例前后清空本套件写的集合（这轮起把 `identities` 也列入清理，群夹具会写它）。
真库用例覆盖：群场景整链、真行上的节奏画像、慢私聊不被抢话、只盖别人的摘要不算本人证据、
更正回标与 stale 登记、索引线程把每个场景都交给摘要器，外加这轮补的两条边界——
出站行内缺 `receipt_at` 时经 `sink_receipts` 算成「说过的话」（`SENT` 那条不算）、
身份表两行同名在真唯一索引下仍是两个 person_id。

## 5. 反证在哪里

- 基线反证：`--baseline` 把 memory／context／dialogue_summary／memory_indexer 换回第一片那份，
  8 条新用例真失败（`WINDOW_ROWS`／`clock`／`summary_scenes` 不存在、`auto_source_skipped` 缺字段、
  同名标签去重无处可跑）。触发那三条（t1／t2／t4）在基线上也能过，因为 `summary_trigger` 本身
  是新模块，没得对比——它们的反证写在用例里：把上一版写死的口径（≥4 条，或 ≥2 条且最早一条
  安静 ≥120 秒）原样搬来当对照，逐条断言旧口径在这些现场上的结论跟新策略相反。
- 旧口径会抢话：半小时一条的私聊，两条刚安静 120 秒它就要整理（t2）。
- 旧口径会迟到：快群里一问一答三条、安静 55 秒（本场景停顿线 25 秒）它还在等第 4 条（t1）。
- 旧口径会打断：凑够四条就动手，人还在 5 秒一条连着发也照整理（t6）。
- 只盖了 B 的摘要照样给 A 看，但不算 A 的证据：那一轮就是 `NOT_COMMITTED` +
  `NO_NEW_SOURCE_EVENTS`，不硬凑一个来源（a1）。
- 补丁链反证（这轮重跑过，之前只比过 `src/`，这轮把 tests／tools 也纳进来）：
  第二片单独打在 `/task/p2-pre-slice2` 上，14 个文件逐字节等于当前工作树；
  从 `/task/p1c-baseline` 起按顺序打两片，17 个文件里只有 `src/asuna/context.py` 差 6 行——
  那是更早一轮写的 `group_discussion` 能力说明，两片补丁都不含它，本片三个 hunk 锚在 75／88／128 行
  也不碰它，所以宿主上有没有那一块都能打（没有就是少一句能力说明，不影响本片任何闸门）。
  之前那处「第二片把 `tools/p2_offline_check.py` 当新文件」的错也在这轮暴露并修掉了：
  它是第一片建的，现在按修改给 diff。
- 边界自测的反证是「撞不撞得动」：`tools/p2b_edge_probe.py` 六组 42 项——
  A 节奏（全等间隔 MAD=0、双峰、隔夜离群、上界 6h、下界 20s、Settle 阈值两侧、未来时间戳、
  四种时间戳格式混杂、只有出站、积压超出观察窗口、空场景、`SENT` 出站被排除）；
  B 冷启动（一条不动手、两条能动、`pooled_prior` 顶掉先验且不跟自己借、非 dm/group 不看、
  没起点线不整理）；C 归属（同名两人、缺 author、身份缺行、单说话人、引用落不到行、
  只有平台 ID、更正的是角色自己、两条更正同一句、跨场景引用、引用自己、无引用兜底）；
  D 跨批次（晚两批回标、同批不回标、tombstone、CAS 撞车、重跑幂等、崩在标记前）；
  E 来源隔离（跨场景／跨人／跨纪元／tombstone／非摘要 kind、旧条目回读作者、更正过的算来源
  但记 stale）；F 失败隔离（模型挂、输出截断、来源被别人先标走、前台忙、暂停、恢复后补上）。
  这轮撞出两处真修正：同名标签会撞车（已按 person_id 分开，并补进回归套件 a3）、
  引用落不到行时依据被写成 `reply_link`（看着像已认定，现改 `reply_link_unresolved`）。

## 6. 已知边界与下一步

- 停顿线要样本：新场景前几条用先验值，宁可少整理也不抢话；`pooled_prior` 只在同一部署内借用，
  不跨部署、不跨场景类型硬套（群与私聊节奏本来就不同，各自算各自的）。
- 更正线索词沿用 `discussion_digest` 那份：它误报只会多一条 `corrections` 记录，不会改写正文；
  漏报则下一批原文还在，角色自己会看见。要更准得让入站侧带平台原生引用结构，那是入站侧的活。
  宿主事实核对过：群入站里顶层 `reply_to` 全缺席，回复结构只在 `event.group_context`（500 条里
  71 条带 `reply_message_id`、82 条带 `reply_to`），所以「引用落不到行」不是假设，是常态之一。
- 窗口上限 8 行是硬约束（单轮 prompt 体积），快群里靠 `window_full` 切批，不靠调停顿线。
- 边界自测仍是离线证据：模型只由假 lane 代表（真 lane 的超时、限流、内容安全拒绝没测）；
  并发只由单进程内的假撞车代表（两个宿主进程同时整理没测）；节奏常数从没在真流量上看过。
  这三样要在隔离真库＋真 lane 上跑一轮才算数。
- REFLECT 阶段的提示词（`config/prompts/stage_reflect.md`）这轮**没改**：它写明「程序负责来源
  关联和提交」，而上面这些闸门全在程序侧，不依赖模型注意到新字段；提示词里同步一句读法
  是可选的润色，不是这片的前提。该文件属宿主配置，不在补丁内。
- 这片不做：跨场景合并摘要、摘要过期与重算、把摘要当证据参与 REFLECT 之外的写入路径。
