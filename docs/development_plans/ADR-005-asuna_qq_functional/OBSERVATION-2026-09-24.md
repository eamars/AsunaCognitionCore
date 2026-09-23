# ADR-005 启动观察（2026-09-24）

- **当前使用入口**：本机 `http://127.0.0.1:8767/asuna/` 已通过 Playwright 实际打开。2026-09-24 00:10（Auckland），Codex 按用户要求在现有会话转交一次 `XIAOMAN_START.md` 的任务原文，勾选本条集成开发授权。Web 返回 `accepted`，页面显示任务已入队，随后显示角色脑 `MONOLOGUE` 运行中。没有重复发送。
- **作者与运行**：本轮 Codex 只读审阅并通过 Web 转交委托，未改产品代码、运行配置或测试，未启停宿主。小满在授权集成开发目录写出 `qqadapter/peers.py`、接入 `service.py` / `adapter.py`、扩充 `selftest.py` 并编写 `PEER_IDENTITY.md`；运行快照已是 adapter `0.3.0`，Web 集成检查器显示 `RUNNING`。仓库产品源码没有本轮改动。
- **磁盘源码观察**：`src/asuna/channels.py` 的 `Channels.receive` 允许字段中没有昵称、群名片或成员角色，当前事件只保留 `sender_id`；`src/asuna/router.py` 构建的认知输入没有投射这些资料，`src/asuna/context.py` 的近期历史也未投射相关快照，`src/asuna/ui.py` 对频道来信仅用 `sender_id` 作发言标签。它们是 P1-a 的具体接线线索，不代表运行进程已加载的版本。
- **当前部署范围**：`src/asuna/config.py` 从独立的 `config/asuna-channel.local.json` 加载当前一个 QQ channel、五条 route。运行中服务的 `health.json` 显示 WS 两路在线、`peer_enriched=4`、`peer_api_calls=3`、资料目录 3 人 / 3 场景。本轮只读数据库核对找到 4 条已保存的 `raw.asuna_peer` 入站，全部为 `RECORDED_NO_WAKE`，没有角色 episode；因此不能据此宣称她已经在对话里读到资料。本轮 Codex 未读取或记录凭据，也未主动触发真实 QQ。
- **探针结果**：真实 `get_group_member_info` 调用返回 `retcode=0`，回执具有 `user_id`、`group_id`、`nickname`、`card`、`role` 等字段；这是平台读取能力证据，不是资料进入角色上下文的证据。小满的 `probe_peer.py`、`probe_host_fields.py` 试运行中，额外资料信封字段均得到 403 `CHANNEL_ENVELOPE_FIELD_DENIED`；带同一旧事件 ID 的原文变体得到 403 `INPUT_IDENTITY_OR_CONTENT_CONFLICT`。未观察到人工消息被宿主接收。
- **检查与原始错误**：Web 工具记录显示离线自检先为 166 pass / 3 fail（改名刷新、跨群名片、查询失败保留字段），修正后分别为 169 / 0 和 170 / 0；真实 NapCat 群/私聊资料查询通过。另一个被 UI 标红的 `integration_stop` 回执是停止旧服务的退出码 -15，新版随后启动为 `RUNNING`。这些检查由小满运行，Codex 没有代跑。磁盘宿主会保存原始 `raw`，但 `ContextBuilder.prepare` 当前未投射 `raw.asuna_peer` 给角色。
- **未验证与唯一下一步**：Web 中小满称第一阶段完成，也承认资料能否进入角色上下文未核实；尚无自然问答验证，改名和身份变更的真实平台路径也未验证。磁盘 `Router.receive` 丢弃 `raw`，`ContextBuilder.prepare` 未投射资料。P1-b 历史查询未开始，她为此征求同意，而原任务已明确授权“接着完成”。Codex 的具体审阅意见是：宿主应把已授权发送者的必要资料字段绑定到稳定账号并投射给角色，保留来源和时间，不能把任意完整 `raw` 当作可信上下文。接下来的实现或确切授权缺口由小满自己给出；Codex 不发送新的“继续”任务。

## 01:47 进展补记

- Codex 在现有 Web 当前会话两次提交有来源的代码审阅反馈，第二次指出草稿与实际 `ContextBuilder.prepare`、`Retrieval.search`、`messages` 结构不符；两次均是对原 ADR-005 目标的具体纠错，勾选该条集成开发授权。未修改产品源码或运行配置，未启停宿主或 QQ adapter。浏览器插件的 JavaScript 控制工具在本会话不可调用，故通过本机 Chromium 页面操作并检查可见消息与工具详情。
- 小满/行动脑在其授权开发目录新增 `host_wiring/peer_context.py`、`history_query.py`、`test_host_wiring.py` 和 `HOST_WIRING.md`，并更新技能说明。Web 工具结果显示离线检查先暴露时间窗、参数及假存储错误，修正后为 **45 pass / 0 fail**；检查使用 `FakeMessages` 和 `FakeRetrieval`，未接上宿主真实数据库或角色上下文。
- 当前宿主 `src/asuna` 未加载上述草稿。小满在 Web 最终回复中已更正前次“P1-b 已就绪”的说法，明确 P1-a 角色问答、P1-b 真实历史查询均尚未就绪。静态复核仍见草稿把 `policy_epoch` 查询成 `epoch`，把 `Retrieval.search` 的首参当场景列表，且查询尚未落实 ADR-005 的默认七天、默认 50/最多 200 条、大小写敏感字面匹配及公开消息过滤；草稿不能直接复制部署。
- **下一步**：先把小满草稿按宿主真实字段和授权场景收窄为可应用改动，再在获准的宿主写入/重启范围内启用 P1-a，以 Web/适用 QQ 真实问答验收。宿主写入权限已向用户单独确认中；未获确认前只做审阅，不宣称功能可用。

## 02:06 第三轮草稿复核

- Web 的第三条审阅反馈已触发行动脑；其开发目录 `host_wiring/history_query.py` 于 02:00 更新，改为 `policy_epoch`、`scope_key`、`source_event_ids`，并补默认近七天、每页 50/最多 200 与大小写敏感字面匹配。`peer_context.py` 于 02:01 增加身份匹配校验。Web 截至 02:06 仍显示该条行动处理中，`HOST_WIRING.md` 未随草稿更新。
- 静态核对还有确切契约差异：`src/asuna/coordinator.py` 写出的公开消息是 `phase='SPEAK'`、初始 `delivery_state='READY'`，`src/asuna/channels.py` 的平台回执才把状态改为 `DELIVERED`。草稿却按不存在的 `kind='SPEAK'`、`publication in ('published','confirmed')` 过滤，因此会漏掉已发布消息。出站消息当前没有 `occurred_at`，七天窗口和排序要有真实时间字段策略。
- `src/asuna/ingress.py` 的 `author` 已是授权后的 `person_id`（例如 `qq:<账号>`）；草稿 `verify_peer` 再拼一次 `qq:`，会把合法消息错判为不匹配。真实群场景 ID 是 `qq:<机器人账号>:group:<群号>`，草稿按 `group:<群号>` 解析也取不到群号。宿主 `event['channel']['sender_id']` 和 `event['channel']['target']` 才是通过 route/member 检查后的对应来源，接线必须明确用它们绑定身份块。
- 以上均是读取宿主源码与草稿得到的审阅结论，尚未运行宿主探针或 Web/QQ 身份问答；不能把草稿更新记作 P1-a/P1-b 验收通过。

## 02:47 第五轮草稿状态

- Codex 又通过现有 Web 提交两条具体审阅反馈，指出真实公开字段 `phase='SPEAK'` / `delivery_state='DELIVERED'`、宿主 `author` 的 `qq:` 前缀、`event.channel.target` 的 `{type,id}` 字典形状，以及入站 `occurred_at` 与已送达出站 `receipt_at` 的双时间字段。反馈均在页面被接受，并触发小满/行动脑在其开发目录修订。没有由 Codex 改动产品源码或启停服务。
- 当前开发目录的 `host_wiring/peer_context.py` 已从认证后的 `event.channel.target.type/id` 取群号，`history_query.py` 已分两支按各自时间字段查询并归并，`test_host_wiring.py` 已加入真实形状的群目标、双时间字段和分页样本。`HOST_WIRING.md` 于 02:44 更新。第五轮 Web 最终公开回复称功能仍未启用；其工具详情中实际出现 **70 pass / 0 fail** 及后续 `syntax ok`（均由小满运行，Codex 未代跑）。中间有一次 `integration_dev` 工具调用 `exit_code=1`，其 stdout 同时显示 70 pass / 0 fail；随后同类调用 `exit_code=0`、再次输出 70 pass / 0 fail 和 `syntax ok`。原始一次错误保留，不将其抹成全程无错。
- 静态复核的当前结论：草稿比前一轮更接近宿主契约，但 `HOST_WIRING.md` 把 `event.channel.sender_id` 直接称作 `person_id` 不准确；`Channels.receive` 实际先用 `sender_id` 查 route member，再把 `member['person_id']` 写成事件 `person_id`。文档给的 `scope_key=scene_id` 只是示例，不应当成通用规则。宿主接线片段仍是示意，不是可逐字应用的补丁。
- **运行状态不变**：`src/asuna` 尚未纳入上述两个模块，`Router.receive` 仍丢 `raw`，`ContextBuilder.prepare` 仍未投射身份。真实 QQ 平台取资料的能力已有证据；角色问答、全量历史查询、群总结均未在当前宿主完成 Web/QQ 验收。ADR-005 `CODEX_START.md` 第 3 节要求 Codex 不默认编辑/部署宿主；一次性宿主写入与重启的具体授权已向用户询问，仍待答复。
