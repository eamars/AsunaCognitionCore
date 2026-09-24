# ADR-005 P1-c 宿主集成使用说明（小满提交，随 diff 一起审阅）

按需整理当前授权群里指定时间／主题的讨论。与 P1-b 同一来源、同一授权、同一游标纪律；
不新建总结服务、不新建集合、不调模型、不向 QQ 发送任何东西。

## 改了什么

| 文件 | 内容 |
|---|---|
| `src/asuna/discussion_digest.py` | 新增。整理主干：读原文完全复用 P1-b 的 `history_query.query_history`（三支时间、场景围栏、keyset 游标都不另造），另加一次批量 `messages` 读拿 reply 链与身份块；按主题或按人整理时先沿真实 reply 链把同一讨论流补齐（后续更正几乎不会重复主题词），再按参与者／后续更正／个人意见／未决事项／覆盖范围分开返回。链内后续的范围与时间口径仍走 P1-b 的 `_row_allowed`／`_outbound_time`／`_sink_times`，不另造一套。 |
| `src/asuna/tasks.py` | `digest_authorized_discussion` 注册进 `TOOLS`/`WORKSPACE_TOOLS`；`ToolBroker.call` 增加与历史查询同规则的只读分支：不持 effects 锁执行，执行后重验任务围栏。 |
| `src/asuna/application.py` | 装配：`DiscussionDigestService(self.store, self.retrieval)` 注入 `broker.digest`。复用宿主已有连接与授权对象。 |
| `src/asuna/context.py` | 角色能力说明加一行：整理结果里分类是机械标注、`more=true` 不算完整，措辞与取舍仍归角色。 |
| `tests/discussion_digest_cases.py` | 离线整理用例（假集合真算过滤／排序／分页），18 项；不依赖 Mongo 与 pytest。含 Q2 等价回归（线缆主题 + 不含“线缆”的 reply 更正，交错相机讨论不得冒充结论）、跨页不重不漏、超长链报部分完成并能续读到 m10/m11、person 只限定主题命中项。 |
| `tests/test_discussion_digest.py` | 隔离宿主定向检查：真实 Mongo 读取、续页不重不漏、真实 ToolBroker 调用与围栏、P1-b 回归。 |
| `tools/p1c_offline_check.py` | 离线自检入口（本机已跑）。 |

未动：`peer_context.py`（P1-a）、`history_query.py`（P1-b 主干一行未改，只被导入）、
dsh-plugin/tools.ts（按 spec 泛化注册）、outbox/ingress 语义、生产配置。没有新增公开
Mongo 或 HTTP 接口，没有新集合，没有新端口。

## 正式调用路径

Web/QQ 输入 → 角色 DECIDE delegate → 行动脑调 `digest_authorized_discussion` → ToolBroker
按任务绑定场景执行 → `query_history`（P1-b）读原文 → 批量读 reply 链与身份块 → 分类与
覆盖范围 → 渲染文本 + 结构化字段 → 原角色响应。来源回读沿现有 artifacts/审计视图与
`query_authorized_history`，不建新 UI。

## 参数与语义

- `topic`（别名 `query`；两个都给且不同值→`DIGEST_ARGUMENT_CONFLICT`）：字面主题词，
  正则转义，默认大小写敏感（`case_sensitive:false` 可放开）。空串＝窗口内全部。
  字面没匹配不等于没讨论过，渲染里写死这句。
- `person`：只回答“**主题命中项**只看谁说的”，沿用 P1-b 的人物口径（认已认证 author 与校验过的
  身份块）。同一 reply 链带进来的上下文发言**可能来自别人**（不然就会漏掉“更正：第二格”这类
  不重复主题词的后续）：这些条目标 `person_match=false`，参与者条目带 `outside_person` 计数并在
  渲染里标 `thread_context（非 person 指定）`，`coverage.person_scope="seed"` 与
  `coverage.person_context_rows` 给出可核对的口径。所以“按人整理”不等于“结果里只有那个人说的话”，
  而是“以那个人说的为主题，带上链上的上下文”。
- `since`/`until`（`YYYY-MM-DD[Thh:mm:ssZ]`）或 `window_days`（默认 7，≤90）；
  `limit` 是**本次整理读多少条主题匹配原文**，默认 50、上限 200；`cursor` 续页。
  同一 reply 链的后续不计进 `limit`，另在 `coverage.matched`／`coverage.thread_extra` 分开报。
- 游标信封带 `kind='digest'` 与筛选指纹：换 topic/人/时间窗复用报
  `DIGEST_CURSOR_FILTER_MISMATCH`；拿 P1-b 的游标或乱写的游标来报 `DIGEST_CURSOR_INVALID`
  ——不给“看似连续”的错页。渲染行里呈现的 `cursor=` 与结构化 `next_cursor` 同值。
- 授权绑定：场景来自任务记录；参数里出现 `scene_id` 之类直接 `DIGEST_ARGUMENT_DENIED`；
  场景记录与任务 scope/epoch 不同步 → `DIGEST_SCENE_FENCE_MISMATCH` 拒查；任务取消后
  调用 → `STALE_TASK_FENCE`。同 call_id 幂等回放。
- 三种状态分开：没查到（`coverage.read=0`、`degraded=false`）、没接上（`degraded=true`+
  `why`）、语义检索失败（`semantic.ok=false`，字面照读）。

## 分类依据（机械标注，不猜）

- **参与者**：已校验身份按 `person_id` 归并（改名不拆人），带群身份、条数、首末时间、
  「对方说／我说」；身份块缺失或没通过校验的退回已认证 `author` 并标 `identity:author`，
  `coverage.identity_fallback` 给出条数。
- **后续更正**：命中更正线索才标。依据分四级写进 `basis`/`confidence`：
  `reply_link`（high，真实 reply 链指向本次读到的一行）、`reply_link_out_of_scope`
  （medium，链指向本次没读到的一行，照实说对象不在范围内）、`self_reference`
  （medium，文本自称「上面那条…」）、`cue_only`（low，只有更正措辞，不指明对象）。
  另有 `self_correction`（更正自己）与 `later_than_target`（确实更晚）。
- **个人意见**：`subtype` = `dissent`/`preference`/`opinion`，每条带命中的 `cue`。
  标注只说明“这句像主观表态”，不说明它对不对；引用哪条由角色看原文决定。
- **未决事项**：提问与「待定」类表述。只有**同一批读到的行里**有真实 reply 链指回它才进
  `resolved`（并标回复里是否带确认措辞）；没有 reply 链的后续表态不自动当答案，仍留在
  `open_items` 里并写明原因。跨页时链的另一端不在本页 → 不猜，照实留在未决。
- **实际覆盖范围**（`coverage.matched` 主题匹配条数、`coverage.thread_extra` 链内后续条数、
  `coverage.thread` 带 `extra`／`out_of_window`／`rounds`／`truncated`／`why`／`skipped_seed_eligible`／
  `skipped_carried`／`carry_truncated`／`pending`／`pending_wanted`／`pending_truncated`／`resumed`，
  `coverage.person_scope`／`person_context_rows` 标 person 口径，参与者条目带 `outside_person`，
  整理项条目带 `person_match`）：`coverage` 里请求窗口≠`covered_from`/`covered_to`（真正读到的跨度）；
  时间来源分布（入站／平台回执／本机送达回执）、`undated`、`excluded`（未送达出站、
  非 SPEAK 出站）、`dropped`、`identity_fallback`、`semantic_candidates`、`more`、
  `complete`。`more=true` 有两种：**还有未读原文**，或**同一 reply 链的讨论流没走完**（表头分别写
  「部分覆盖（还有未读）」／「部分覆盖（讨论流没走完）」）。两种都带 `cursor`，`more=true` 时
  `complete` 一定 false，说“整段讨论整理完了”就是越界。
- 传输预算 48 KiB：先压片段再丢片段，`source_ids` 与计数全留，不静默消费。

## 按主题整理时的讨论流补齐（本轮修正）

复现出的缺陷：`topic=雾灯` 时只读到首句，`reply_to` 指向它的那条“更正一下：不是明天，是周三”
因为不含“雾灯”被字面筛选丢掉，`corrections` 空、`coverage.complete=true` —— 覆盖范围对一条
真实存在的后续更正撒了谎（DECISIONS §3 / ACCEPTANCE Q2 不允许）。

规则（最小实现）：给了 `topic` 或 `person` 时，先以本页命中为种子，沿**真实 reply 链**双向走
闭包——命中项的回复、被命中项回复的那条、以及它们后续的链；窗口外的环节也继续往下走一轮，
免得链被一个窗口外环节断掉后报出来的“窗口外”条数只是下界。闭包里的每一行仍要过 P1-b 的同一
套范围规则（同场景、同策略周期、同一时间窗、入站 `occurred_at`、已送达出站 `receipt_at`／
`sink_receipts.received_at`、没时间戳不进覆盖范围）。每轮一条查询（`$or`：找谁的回复＋按 `_id`
找被回复的那条），不按行轮询。

只认 reply 链，不按时间邻近拉行：交错在中间、没跟命中项连成链的别的话题不会被拉进来，不会
冒充这条主题的结论（回归用例里相机讨论就是干这个的）。链内后续在渲染行末标
〔线程内后续，不含主题词〕，条目上带 `thread: true`，`readback.thread_source_ids` 单独列出。

两条跳页规则（DECISIONS §3 要求不重不漏）：

- **本身就会被字面筛选读到的行不当链内后续送**（`_seed_eligible`：主题词按同一套大小写规则看，
  按人筛选复用 P1-b 的 `person_clause`）。这样一行要么作为命中项被它所在那一页送（keyset 游标
  保证不重不漏），要么作为链内后续被链到它的那一页送，两边不会都送；计数在
  `coverage.thread.skipped_seed_eligible`。
- **上一页送过的链内后续随游标带下来跳过**：`kind='digest'` 信封多带一个 `d` 列表（上限 64 条，
  超了写 `carry_truncated` 并照实提醒可能重送），计数在 `skipped_carried`。

上限与续读（DECISIONS §3「部分结果并继续已有目标」）：链最多走 60 条／8 轮。到了上限还有
下一环（或命中条数封顶）时，`coverage.thread.truncated` 为 true、`why` 写
`thread_rounds_exhausted`／`thread_row_cap`，**待走环节随游标带下去**（`pending`／`pending_wanted`），
`more` 也为 true、`next_cursor` 非空，`coverage.complete` 随之为 false，表头写
「部分覆盖（讨论流没走完）」，notes 写「讨论流没完全展开……带 cursor 续页会沿同一筛选接着读
剩下的环节」。带着这个 cursor 再调一次就是上一页的继续：同一筛选（指纹不符照旧拒），字面那一支
已读完时**不重跑字面查询**（否则会把第一页的命中项再送一遍），只沿 reply 链接着走，时间窗沿用
发放游标那一页（`coverage.thread.resumed=true`，notes 里写明）。待走环节本身也有上限
（`MAX_THREAD_PENDING=64`）：装不下时写 `pending_truncated`，丢掉的分支照实算部分完成，不假装走完。
游标参数有 1024 字上限，装不下时先削跨页去重集合（宁可重送一条也不丢续页入口，
`carry_truncated` 会跟着报出来）。

来源回读也跟着修：`readback.example_args` 不再无条件带 `topic`。这条更正本身不含主题词，
带上 topic 会让 `query_authorized_history` 又把它筛掉，回读就退回本次整理漏掉它的那个口径；
现在按 `person` + 该条前后两秒回读，只有这条本身确实含主题词时才把 `query` 带进参数，
`topic_omitted` 会标明这次为什么不带。回归用例里真拿这份参数去跑了一次 P1-b 查询。

## 隔离测试（操作员在隔离宿主跑）

```bash
cd <隔离宿主副本根目录>
python3 tools/p1c_offline_check.py            # 离线 18 项，不需要 Mongo
ASUNA_P1C_CONFIG=<操作员提供的配置路径> python -m pytest tests/test_discussion_digest.py -v
```

- 配置入口与既有测试相同（默认 `config/local.json`，可用 `ASUNA_P1C_CONFIG` 指到副本外的
  测试配置）；文件缺失即 fail closed。
- 只用固定授权库 `asuna_v2_test_p1c_host_20260924`（可用 `ASUNA_P1C_DATABASE` 指向另一个
  同等受限库）；每个用例开头与结束清空本套件写的集合；不 seed ADR-001 夹具，不碰生产库。
- 预期观察：15 个用例全绿。其中
  `test_seed_and_continuation_are_not_delivered_twice_on_real_mongo` 应看到逐页 `source_ids`
  合起来正好是 `s1,s2,x` 且不重复、末页 `complete=true`、`thread.skipped_carried=1`；
  `test_long_thread_reports_partial_then_continues_on_real_mongo` 应看到第一页 `m1…m9`、
  `more=true`、`thread.pending=["m9"]`、`complete=false`、表头「部分覆盖（讨论流没走完）」，
  带 cursor 的**第二页正好是 `m10,m11`**、`more=false`、`complete=true`、`thread.resumed=true`、
  两页时间窗一致；`test_person_scope_labels_thread_context_on_real_mongo` 应看到
  `source_ids=[a1,b1]`、`person_context_rows=1`、`b1` 条目 `person_match=false`、参与者
  `路人甲.outside_person=1`、渲染里出现「非 person 指定」。另外
  `test_topic_filter_keeps_thread_continuation_on_real_mongo` 应看到 `source_ids` 为
  `c1,c2,c3,o1`（`cam1/cam2` 不在内）、`coverage.read=4`、`matched=1`、`thread_extra=3`，
  并且拿 `readback.example_args`（不含 `query`）去跑 P1-b 查询能把 `c2` 要回来；
  `test_thread_rows_outside_the_window_are_counted_not_invented` 应看到 `thread.out_of_window=2`
  而不是假装读到了；链被上限断掉时也不得报完整。另外 `test_digest_pagination_no_loss_no_repeat` 应看到逐页
  `bool(next_cursor)==more`、`complete is (not more)`、8 条不重不漏；
  `test_partial_coverage_blocks_completion_claim` 应看到跨页的更正链被标成
  `reply_link_out_of_scope` 而不是被猜出来；`test_p1b_history_path_is_untouched` 是 P1-b
  回归。任何失败请回传完整 stdout/stderr/traceback。
- 全程只读：不领取 outbox、不调 NapCat、不向真实群发测试消息。

## 首轮 Web 验收对接

补丁机械应用并重载后，在当前 Web 本机场景按 DELIVERY_PLAN P1-c 的自然提问走真实链路
（例：「整理一下今天群里关于 X 的讨论」）。应看到：角色 delegate → 行动脑实际调用
`digest_authorized_discussion` → 结果里参与者／更正／意见／未决／覆盖范围分开、每条带
`message_id` 与时间来源；带主题的提问要看到不含主题词的后续更正出现在更正栏并标〔线程内后续〕，
交错的别的话题不被当成这条主题的结论 → 角色引用时以查询结果为准。带 `more` 的页必须续查后才允许说
“整理完整”。QQ 群场景沿同一实现、各自原场景授权；本轮不主动向真实群发送任何消息，
QQ 侧的真实体验等下一次自然对话，不拿 Web 复测冒充 REAL_QQ。

## 这一片故意不做的事

不自动总结、不建主题索引、不每条消息跑模型（那是 P2）；不新建第二套时间口径、
不做“话题相似度”；不替角色决定要不要在群里说话。完成 DELIVERY_PLAN P1-c 定义的
能力即停。
