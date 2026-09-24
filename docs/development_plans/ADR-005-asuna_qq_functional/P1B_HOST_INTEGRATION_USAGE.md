# ADR-005 P1-b 宿主集成使用说明（小满提交，随 diff 一起审阅）

## 改了什么

| 文件 | 内容 |
|---|---|
| `src/asuna/history_query.py` | 新增。查询主干原样收编自 `/task/host_wiring/history_query.py`（回执时间优先级与三支 keyset 分页未动），末尾追加 `HistoryQueryService` 与 `HISTORY_TOOL` 工具声明：场景/纪元/范围键只从任务绑定记录读，参数只收领域字段。 |
| `src/asuna/tasks.py` | `query_authorized_history` 注册进 `TOOLS`/`WORKSPACE_TOOLS`（原生插件行 `asuna-controlled-tools` 自动带上）；`ToolBroker.call` 增加只读分发分支：不持 effects 锁执行（取消/续租不排在 Mongo 读后面），执行后重验任务围栏。 |
| `src/asuna/application.py` | 装配：`HistoryQueryService(self.store, self.retrieval)` 注入 `broker.history`。复用宿主已有连接与授权对象，无新服务、无新端口。 |
| `src/asuna/context.py` | 角色能力说明加一行：可委托行动脑查完整原话；语义候选≠全部原话；引用以查询结果为准。 |
| `tests/test_history_query.py` | 定向测试（见下）。 |

未动：`src/asuna/peer_context.py`（P1-a 只读复用，查询模块顶层直接导入它的三个公开函数）、dsh-plugin/tools.ts（按 spec 泛化注册，无需改）、outbox/ingress 语义、生产配置。没有新增公开 Mongo 或历史 HTTP 接口。

## 正式调用路径

Web/QQ 输入 → 角色 DECIDE delegate → 行动脑（workspace 工具集）调 `query_authorized_history` → ToolBroker 按任务绑定场景执行 `history_query.query_history` → messages + 必要 sink_receipts → 原文/作者/时间来源/场景/定位/游标 → 原角色响应。来源回读沿现有 artifacts/审计视图，不建新 UI。

## 参数与语义

- `query` 字面子串（正则转义，默认大小写敏感，`case_sensitive:false` 可放开）；空串=窗口内全部。
- `person` 只回答“查谁说的话”：认已认证 `author`，也认校验通过的身份块（名片/昵称/显示名/曾用名）；不把该人物变成授权主体。
- `since`/`until`（`YYYY-MM-DD[Thh:mm:ssZ]`）或 `window_days`（默认 7，≤90）；`limit` 默认 50、上限 200；`cursor` 续页（游标绑定发放它的筛选：换词/换人/换时间窗必须重新查询，复用旧游标报 `HISTORY_CURSOR_FILTER_MISMATCH`，非本服务发放的游标报 `HISTORY_CURSOR_INVALID`）。渲染行里呈现的 `cursor=` 与结构化 `next_cursor` 同值（同一个指纹信封），行动脑照文字续查与照字段续查等价。
- `include_semantic:false` 可关语义候选。语义命中带 `via:'semantic'`，与 `via:'literal'` 可区分；语义失败只记 `semantic.why`，字面照返。
- 时间来源逐条标注：`messages.occurred_at` / `messages.receipt_at`（QQ 平台回执）/ `sink_receipts.received_at`（本机送达回执，`time_ref` 指向回执行；渲染行首带⟨本机送达回执⟩，不伪称原始发送时刻）。行内 `receipt_at` 优先于关联回执，两支游标同步推进。
- 分页：三支各自 keyset；`more=true` 必带 `next_cursor`。第三支单页预算只拦工作量，`fallback.exhausted=false` 时一定 `more=true`——没有“扫满即完”。
- 三种状态分开：没查到（hits 空、degraded=false）、没接上（degraded=true+why，如 `no_scope`）、语义检索失败（semantic.ok=false）。`hits_trimmed` 表示传输预算裁掉了页尾最旧命中：裁剪时一定 `more=true`，游标回退到最后一条已交付命中，续页原样重发被裁命中的完整原文（不静默消费）；`dropped` 透传筛选器实际滤掉的计数（如 wrong_person）。
- 授权绑定：场景来自任务记录；参数里出现 `scene_id` 之类直接 `HISTORY_ARGUMENT_DENIED`；场景记录与任务 scope/epoch 不同步 → `HISTORY_SCENE_FENCE_MISMATCH` 拒查；伪造游标只能移动时间位，换不了范围；任务取消后调用 → `STALE_TASK_FENCE`。同 call_id 幂等回放。

## 隔离测试（操作员在隔离宿主跑）

```bash
cd <隔离宿主副本根目录>
ASUNA_P1B_CONFIG=<操作员提供的配置路径> python -m pytest tests/test_history_query.py -v
```

- 配置入口与现有 conftest 相同（默认 `config/local.json`，可用 `ASUNA_P1B_CONFIG` 指到操作员放在副本外的测试配置）；文件缺失即 fail closed。
- 测试只用固定授权库 `asuna_v2_test_p1b_host_20260924`（操作员账号仅此库 readWrite；可用 `ASUNA_P1B_DATABASE` 指向另一个同等受限库），每个用例开头与结束都清空本套件写的集合以保持隔离（结束清理不给同库 Web 重启留 READY 合成任务）；不 seed ADR-001 夹具，不碰生产库，不要求建库或全库权限（同宿主写入链的行形状在测试内构造，含缺 `receipt_at` 的历史结构）。
- 预期观察：11 个用例全绿；其中 `test_fallback_keeps_more_until_truly_exhausted` 应看到首页 `fallback.exhausted=false` 且 `more=true`、翻页后 205 条不重不漏；`test_broker_*` 两条证明真实 ToolBroker 进程内调用、能力围栏与取消围栏。任何失败请回传完整 stdout/stderr/traceback。
- 既有离线 116 项与生产只读探针保留，不在本轮重跑；`tests/test_peer_context.py` 未动，P1-a 路径只核对未被覆盖。

## 首轮 Web 验收对接

补丁机械应用并重载后，在当前 Web 本机场景按 ADR §6.1 的自然提问走真实链路：角色应 delegate，行动脑实际调用 `query_authorized_history`，结果里的原文/作者/时间来源/场景定位可在现有视图回读；带 `more` 的页必须续查后才允许说“查完”。QQ 场景沿同一实现、各自原场景授权，不拿 Web 复测冒充 REAL_QQ。
