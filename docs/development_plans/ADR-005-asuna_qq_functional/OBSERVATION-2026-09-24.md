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

## 10:44 一次性授权后的 P1-a 宿主接线

- 用户回复“授权”，允许本次 Codex 修改 P1-a 宿主源码并重启。Codex 是 `src/asuna/peer_context.py`、`router.py`、`context.py` 和定向测试的实际作者；身份投射以小满在授权开发目录中的 `host_wiring/peer_context.py` 草稿为基础，按真实宿主字段修正。此授权不扩大到 P1-b 历史查询或 P1-c 群整理。
- 已认证的 QQ 事件进入角色路径时，Router 只保留绑定 `person_id`、发送者账号与群/私聊目标的有限 `asuna_peer` 快照，不把任意 OneBot `raw` 交给角色。ContextBuilder 从落库的当前输入读快照，复核消息作者和目标后，加入单独标明群名片、QQ 昵称、群身份及资料核实时间的 `sender_identity`；缺字段或不匹配时不加身份块。现有无需唤醒的群消息仍只记录，不触发角色。
- 先在真实已落库 QQ 消息上做只读设计探针：接线前 `ContextBuilder.prepare` 的 `context_has_sender_identity=False`，接线后同一来源为 `True`，字段标签和作者绑定均为真。定向测试 `tests/test_peer_context.py` 为 **3 passed**；相关宿主检查为 **35 passed / 1 failed**。唯一失败是旧 `test_E05_delivered_projection_only` 的手造出站消息没有现有查询要求的 `policy_epoch`，与本次新增身份字段无因果关系；原始失败保留。
- Codex 通过现有 Web 的“停止整个服务”停止旧宿主，再用 `start-asuna.cmd --port 8767` 启动新进程。新的 Python 进程与 8767 Web 监听已确认；in-app browser 重新打开 Web，原本机记录与 QQ 群场景均可见。重启后的 adapter `health.json` 显示两路 OneBot WS 均在线。QQ 群最后可见来信仍为 10:20 的旧消息，未观察到重启后唤醒角色的新真实 QQ 事件，因此**尚不能宣称真实 QQ 自然问答已通过**。Web 群输入是本机指令，不冒充 QQ 来信。
- **当前结论与下一步**：P1-a 宿主代码已部署，真实数据至角色上下文的读取路径与 Web 重启可用性有证据；还需一次授权账号的自然 QQ 呼名/私聊问答，查看角色 episode 的身份上下文、答复及平台回执，才能补齐真实平台效果。P1-b、P1-c 保持未接入状态。

## 10:50 真实 DM 使用与身份措辞修正

- 用户在真实 QQ DM 连续问“你还记得我么？”和“你觉得我是一个怎样的人？你对我的印象有多少呢？”。现有 Web 显示小满分别回复并标“已送达”；第二条的宿主出站记录有 `DELIVERED` 和 `receipt_at`。对应两个真实 episode 均为 `COMMITTED`，其持久角色上下文均含经账号、DM 场景核对的 `sender_identity` 和平台核实标记。这补齐了 **P1-a 的真实 DM 入站→角色上下文→QQ 出站回执**证据；仍未见群身份自然问答，也不能由答复未叫昵称推断身份字段无效。
- 小满的回答依据旧消息，认为用户曾重复发送测试消息，并说“我们才刚认识”。当轮上下文实际有 12 条已送达历史、6 条召回材料；关系状态仍是“不预设其他身份或共同经历”。其中身份行把 adapter `first_seen` 错写成“自某日认识”、把 adapter 内计数写成“这个场景里第 2 条”，而宿主已有 11 条该 DM 来信，最早早于 adapter 建档。不能证明这两句必然导致小满的措辞，但它们确实会误导对交往时长的判断。
- Codex 在本次 P1-a 授权内移除了上述两段角色可见措辞，保留稳定账号、昵称、好友关系、平台核实时间等字段。真实 DM 记录的只读 `ContextBuilder.prepare` 复算确认身份仍出现、错误的认识时长/消息序号不再出现；定向测试 **4 passed**、`git diff --check` 通过。通过 Web 停宿主后再用 `start-asuna.cmd --port 8767` 重启，Web 中同一 DM 历史可见，adapter 两路 WS 在线。旧回复和旧 episode 是历史快照，不会被倒改；修正后的新一轮自然 QQ 回复尚未观察。

## 11:09 按 ADR-005 继续测试：Q8 受控路径与 Q1 Web 原话

- 用户明确要求继续测试。重启后截至本轮查看，生产 QQ DM/群均无更新来信；没有冒充 QQ 发送者，也没有向生产群发测试消息。Codex 在独立数据库 `asuna_v2_test_ADR005_Q8_f7402b37aa05` 以受控资料信封走 `Channels.receive → Router.receive → ContextBuilder.prepare`，不调用模型或真实 QQ 发布。**9 项确定性检查通过**：同一账号两群名片隔离、同昵称不同账号不合并、旧快照不被改名倒写、下一条资料中的身份变化、资料缺失仍可接收、错群资料不进入角色身份、未授权发送者被拒绝、无唤醒仍保留记录，以及唤醒消息身份进入上下文。管理员撤销是下一条受控消息的资料变化，未模拟平台通知；这些结果不算真实模型问答或 QQ 平台回执。
- 小满 P1-b 独立草稿仍未接入 `src/asuna`。在上述隔离库中，其 `query_history` 对同一群 6 条消息分页三页能逐条读回，字面“名片”命中一条；但 `search_messages(query="", window=None)` 因查询时间字段为 `{}` 返回 0。`query_history(person="qq:77", limit=1)` 首屏 0 条、`more=True`，`render` 却说“没有匹配”；同数据用数据库级 `author="qq:77"` 可命中，原因是人物名过滤发生在分页之后。按目标宿主模块名导入草稿还因依赖当前 `peer_context.py` 不提供的 `_group_token` 而失败。这些是未部署草稿的真实兼容性/分页缺口，不能算 P1-b 已可用。
- Codex 在现有 Web 本机场景仅发一次自然问句：“我之前在本机聊天里亲口说过关于‘雾灯’的什么？请找出包含‘雾灯’的完整原话、时间和出处；如果找不全，直接说明覆盖范围。”Web 11:09 的实际角色答复已送达，却引用了**小满自己的**同一句话，称对应序列 81、83，未给精确时间。宿主原始消息核对：81、83 均为 `author=xiaoman`；在此轮之前，`author=local-user` 且含“雾灯”的原话实际有 4 条（序列 46、80、82、84，均有 `occurred_at`）。该轮角色上下文只选到两条相关 `public_statement`（81、83），未选到那 4 条用户原话。故 **Q1 当前 Web 原话/说话人/时间验收未通过**；现有六条 RAG 召回不等于完整历史查询。没有为了凑输出反复追问或改提示词。
- **下一步**：P1-b 草稿先修宿主导入和人物过滤/空窗查询，再接到授权场景的现有角色/工具路径；随后用同一自然问题复测原话、时间和来源。P1-a 修正后的自然 QQ 问答仍待真实来信；P1-c 与平台通知仍未验收。

## 11:47 继续执行：P1-b 草稿修错与宿主接入阻碍

- 用户要求继续执行 ADR-005，并要求真实阻碍写给无代码访问权的架构师、不由 Codex 私自改架构。Codex 在现有 Web 原会话提交一次带真实样本的 P1-b 审阅反馈，勾选本条集成开发授权；后续对 `_group_token` 宿主组合导入、避免新增依赖协议、以及口头答复尚未落盘分别给出窄范围纠错。没有由 Codex 修改产品源码、宿主配置或启停服务。
- 小满/行动脑在独立 `integration_dev` 目录修改了 `host_wiring/history_query.py`，把无窗口时错误的空对象时间条件移除、把人物条件下沉到分页前、在命中与显示中明确时间及“我说/对方说”和真实 `author`；补了假存储行为及相应用例。Web 工具回执 stdout 为 `host_wiring: 81 pass / 0 fail`，测试仍是独立目录内的离线样本；她还写了模拟 11:08 失败形状的脚本，不是对真库的复测。
- 小满通过受管环境只读探查确认：现有宿主转发端点的历史相关 GET 均为 400，该环境没有 Mongo 转发，也没有 `src/asuna` 宿主源码挂载。修好的草稿不能由这一环境加载到当前宿主或用真实 `messages` 验证。Codex 已把用户可见错误、技术/授权边界、需裁定的写入和验收责任写入 [架构师阻碍文档](ARCHITECT_BLOCKER-2026-09-24-P1B.md)。这是 P1-b 端到端交付的真实阻碍，不影响继续修草稿。
- 11:46 的磁盘复核仍见草稿顶层导入当前宿主 `peer_context.py` 缺少的 `_group_token` 和 `_norm_person`。小满此前仅验证自己的两份草稿互相导入，随后在 Web 承认两者不同，并已接收实际修改与宿主组合导入复核要求；截至此记录该轮行动仍在处理。P1-b 未部署，11:08 的 Q1 Web 失败尚未复测，P1-a 真实 QQ 修正后问答也没有新事件。

## 12:05 宿主组合复核与接线文档纠错

- 小满在独立开发目录进一步移除两个缺失私有 helper 的导入，局部工具回执报告 **95 pass / 0 fail**，包含用模拟“当前宿主形状”的包导入检查。Codex 随后用**磁盘上的当前 `src/asuna/peer_context.py` 原件**与新 `history_query.py` 做只读组合导入，得到 `import=OK`、`identity_complete=True`、`identity_source=peer_context`；没有写入宿主或运行真实 Mongo 查询。
- 当前草稿还增添 `configure_identity`/惰性身份采纳协议；它只在独立目录，未获架构裁定，也未部署。小满的 `HOST_WIRING.md` 仍称为了获得昵称、名片和身份需覆盖宿主身份模块，与上述真实组合结果不符，并可能回退已上线的 P1-a 修正。Codex 已在现有 Web 提交实测证据，要求小满修正文档并把依赖收敛到现有三函数直接导入及本地字符串 helper；该纠错任务已入队，完成以文件和工具回执为准。
- P1-b 的授权宿主接入与真库/Web 验收仍未完成；独立草稿的导入成功不能替代它。架构师待决边界见前述阻碍文档。

## 12:17 真实消息只读探针

- Codex 只读加载小满当时的 `history_query.py`，与当前宿主 `peer_context.py` 组合，查询实际 Mongo `messages`，不调用模型、不写库、不发送消息。在 `local-dm`、11:08 问句之前的明确时间窗内，字面“雾灯”加 `person=local-user` 返回用户四条原话，场景序列 84、82、80、46；`limit=1` 连续四页顺序相同，无重复或漏页。此处证明入站字面/人物/分页在这个真实样本上工作，不等于完整 P1-b Web 功能。
- 去掉人物条件后，草稿仍只返回四条用户来信，遗漏已送达的角色公开发言 81、83。真实消息行中两条均为 `direction=outbound`、`phase=SPEAK`、`delivery_state=DELIVERED`，但没有 `receipt_at`/`occurred_at`；`receipt` 所指的 `sink_receipts.received_at` 分别为 `2026-09-20T05:50:29.183624+00:00` 和 `2026-09-20T05:52:28.841376+00:00`。这是独立草稿的普通时间回退缺陷。Codex 已通过现有 Web 把精确真实形状和修复要求交给小满，页面显示行动处理中；架构师文档也补了这项事实。查询草稿仍未部署，Web Q1 失败未复测。

## 12:23 独立草稿继续修订

- 小满在独立开发目录把 `history_query.py` 的身份接线收回为当前宿主已有的三个函数直接导入，移除了 `configure_identity` 与 `use_peer_context_identity` 两个额外入口。Codex 对这版草稿再次与当前宿主身份模块只读组合导入，结果 `import=OK`、`identity=True/peer_context`、两个额外入口均不存在。
- 这一轮行动工具先实际写入了代码，但随后因行动模型 `max-tokens` 返回 `BLOCKED`，接线文档和测试尚未完成。小满的下一项行动已开始处理真实 Web 已送达出站的时间回退；不能把正在运行的任务或口头计划记作完成。
- 12:28 这项时间回退行动也因 `max-tokens` 中断，未写入 `history_query.py`；当前草稿仍会漏掉 81、83。Web 角色脑已收到诊断并继续创建下一项行动。两次 `max-tokens` 是执行侧可恢复错误，不改变架构师文档所述的宿主接入边界，也不算功能验收。
- 用户问是否因为 Asuna 未继承 DSH 的 compaction threshold ratio。源码核对 `src/asuna/dsh_lane.py` 已把 `0.8` 同时交给 `asuna-compaction.thresholdRatio` 和 `asuna-runtime.pressureThresholdRatio`；执行模型配置为 `context_window=262144`、`max_tokens=8192`，对应压缩压力阈值约 209715 tokens。两次失败的真实 provider 最后请求分别用 `69113` / `38372` prompt tokens，回执均为 `8191` completion tokens、`finish_reason=length`，DSH 记为 `max-tokens`，无本任务压缩事件。这证明本轮是**单次生成输出触顶**，不是未配置压缩阈值或输入上下文达到压缩线；中断后仍可在原目标下收窄行动继续，不以此请求架构改动。
- 随后又一轮相同目标的行动仍以 `max-tokens` 中断，时间回退代码依旧未落盘。Codex 已在现有 Web 把 provider 证据和**只做一次最小文件修改、后续再单独测试**的收窄反馈交给小满；Web 显示“已入队”。这避免把输出触顶误判为缺 compaction 设置，也避免为此擅改模型配置或宿主架构。
- 再核对连续四次中断的最后 provider 回执：prompt tokens 依次为 `69113/38372/80636/40191`，completion 均为 `8191`，`finish_reason=length`；第四轮没有工具步骤。架构师文档已补运行阻碍及需明确的运行设置责任，和宿主接入边界分开。当前后续行动仍在运行，`history_query.py` 截至此记录最后改动仍为 12:19 的身份导入简化，尚无时间回退修改或 Web 复测。
- 还读取了正在使用的 executor DSH `lane.patch.yml` 配置快照：`asuna-compaction.thresholdRatio=0.8`、`asuna-runtime.pressureThresholdRatio=0.8`、`contextWindow=262144`、`maxTokens=8192`，与源码和模型设置一致；因此不是只看源码推测阈值已经传递。

## 13:00 同模型 DSH 配置对比与运行修正

- 用户指出另一台 `192.168.2.10` DSH 使用同一 Qwen 模型而未发生输出截断。Codex 找到该部署文档记载的只读 PRC 设置路径，实查该模型所属 provider 的 `defaultMaxTokens=32768`，无更低的模型单独覆盖；本机实际模型服务启动参数允许 `--max-output-tokens 65536`。故此前把 Asuna 的 8192 视作模型极限是不正确的：它是本机配置的请求上限。四次 `8191`、`finish_reason=length` 的原因应表述为**本机输出上限触顶**。压缩阈值确为 0.8，但输入还未达到阈值，这与上限差异是两项独立核查结果。
- Codex 备份本机模型覆盖配置，通过现有模型设置校验与持久化路径，只把行动模型 `max_tokens` 从 `8192` 改为 `32768`，角色模型保持 `4096`，模型、服务地址与推理设置不变。通过 Web 停止并重启宿主后，活动 executor DSH 两处 `maxTokens` 均为 `32768`，Web 模型设置显示 `32768`。一条经 Web 授权的 P1-b 窄任务已入队，真实 `provider.request` 携带 `max_tokens=32768`；是否最终修改草稿、是否避免再次中断须看工具与最终回执。对应示例配置及一次性初始化脚本的同模型默认值也同步为 `32768`，避免新部署重现 8192。
- 输出配额问题已在本机配置层处理，架构师文档只保留宿主接入与验收授权这一真实边界。P1-b 时间回退草稿截至本补记仍未更新，也未装入宿主；Web Q1 尚未复测通过。

## 13:17 P1-b 草稿落盘及只读复测

- 小满/行动脑在受管 `/task/host_wiring/history_query.py` 分块写入了本机 Web 已送达出站从 `receipt` 关联现有 `sink_receipts.received_at` 的回退逻辑；一次过长的 `integration_dev` 参数被拒后改用分块，文件现已写完整。此前离线套件含过期身份注入协议断言，回执为 91 pass、1 fail，随后因访问已移除的 `_identity` 崩溃；这份旧套件不能记作新版本通过。行动任务仍在运行。
- Codex 没有修改草稿或宿主，只读加载草稿与当前宿主身份模块组合，在真实 Mongo 本机 `local-dm` 以“雾灯”和明确时间窗查询，得到 9 条：原先漏掉的角色已送达出站序列 81、83 回来，标记 `time_source=sink_receipts.received_at`。`limit=1` 连续 9 页未见重漏；QQ 私聊 10 条、群聊 6 条已有出站仍标 `messages.receipt_at`。这些只证明所查样本和 QQ 既有时间路径，不等于 Web 角色已获得历史工具。
- 审阅发现回退分支固定最多扫描 400 条按场景序列倒排的候选。Codex 用隔离内存 401 条样本实际分页，前两页各 200 条后 `more=false`、最早一条未返回，尽管结果含 `fallback.truncated=true`。这是普通查询完整性缺陷，待向小满反馈并修复，不请求架构师改变存储或权限。`HOST_WIRING.md` 仍错误建议覆盖运行中的 P1-a 身份模块，也须由小满修正文档。P1-b 仍未接入宿主，Q1 Web 自然提问未复测通过。
