# ADR-003 C3：预算阻断修复

2026-09-23。按 ADR-003.1 与架构师最新指示结束咨询专项，保留已通过 N3、QQ 私聊、行动续接与可选咨询。接下来的产品顺序为 C → D。

## 实际错误归类

1. **宿主额外门槛（D6）**：`TokenMeter.check` 在代理提交上游前抛出 `INPUT_BUDGET_EXCEEDED`。失败请求实际计数 74,034，角色配置容量 68,608、输出上限 4,096，宿主另减 4,096，产生 60,416 的硬门槛。见 `reports/ui-32ac9742b3c0/00304-budget.checked.json` 等。这不是 DSH 或模型返回的溢出。
2. **错误接线丢失原因（D1/D6）**：代理将失败变成 HTML 502 `ASUNA_PROVIDER_BOUNDARY_FAILED`，角色阶段又只保存 `INVALID_STAGE_OUTPUT`。原生会话 `s-8b20489ec543f452c5d596957610bf6acced8d49` 第 15 轮收到 `SERVER`，做了五次同请求重试，未进入 overflow 恢复。
3. **错误处置违反连续性要求**：Codex 使用页面“新上下文”继续原目标，绕开了阻断，但没有修复长期运行。历史保留；不将该操作计作 C3 通过，也不继续用重置规避预算问题。
4. **真实模型输出限制**：原行动任务 `task-ep-1aec8ca7d9b7e07a438b8c343777c536` 的 `max-tokens` 是真实单次生成结束，区别于 Asuna 的额外限步/预算拒绝。原代码、工具结果与后续行动会话均保留。
5. **宿主整项时间截止（D5 同类）**：`DshLane` 将本机 `/run` 等待限制为 1,800 秒。该接口直到整个原生行动 idle 才返回；连续多个正常模型/工具调用也会撞到此门槛。当前长行动使这一接线问题直接相关，删除整项 read 截止，不改成更大数字。保留本机 connect 超时、原生模型传输超时和取消。
   - 随后旧运行进程实际在 19:31:58 把已完成 16 步的行动标为 `BLOCKED / ReadTimeout`。宿主正常停止并重载修复；保留所有工具回执和原执行绑定，Web 续接成功。自动续接中断时的原生 projection 关闭错误亦保留，没有伪称那次续接成功。
6. **自然语言条数充当执行资格（D1）**：真实群邀请的两个 DECIDE 均为合法 JSON、`next=speak`，却因 `constraints` 有 9 项、旧 schema 上限 8 项而成为 `FAILED_PROTOCOL / BAD_DECISION_JSON`。删除 `maxItems`，保留必要控制字段校验；向角色修正阶段和错误记录传回真正的解析/校验原因。
7. **Codex 误诊**：此前只看 `service.on_event` 的 key 参数，就称 spool 会因跨群同号而覆盖；复核 journal 后确认文件名还有时间戳和序号，判断不成立。已通过正式 Web 撤回，不能把增加文件名后缀描述为修好了已证实的覆盖故障。`adapter.lock` 的 PID namespace 重用误报则是真实故障，交由原行动会话修复。

## 原生压缩是否有机会运行

安装版 `dsh-compaction-basic` 默认 `auto=true`、`thresholdRatio=0.8`，Asuna 未关闭它；阈值为 54,886。该会话第 14 轮用量为 54,186（含缓存），尚未到阈值；下一轮新反馈使真实请求升至 74,034。DSH 的压力检查在 `agent/pre-step`，新增输入之后的超量本应能够通过 provider 错误触发 `agent/request-error` 的原生 overflow 路径。宿主却在实际提交前拒绝，并错误分类为 `SERVER`。失败会话没有 `compaction/start`。这是计数口径/检查时点及错误接线问题，不是“DSH 不支持压缩”的证据。

## 最小修改

预算计数保留为观测，记录容量、输出预算与计数失败，不再构成生成资格；取消额外 4,096 余量硬拒绝。模型配置容量和输出上限保留，压缩选择、持久替换、重试次数与取消继续归原生 DSH。

代理因本地排队须提前发 SSE admission，无法再修改 HTTP 状态；上游 HTTP 错误因此用 SSE error 帧保留原错误对象，供安装版 SDK 和 DSH 分类。原始上游状态、响应体仍保存。宿主异常保留具体类型/原因，角色阶段也记录原生 diagnostic。没有新增恢复状态机、权限体系、逐句审核或任务终止条件。

既有 Asuna 摘要 hook 对 `error/aborted` 也改为保留原始 message/code；摘要选择与提交仍是原生实现。一次直接 hook 检查验证其错误码不丢失。

## 验证

- 先运行实际 `ProviderProxy` + 回环 HTTP fixture + 安装版 OpenAI SDK：大于旧门槛的请求实际抵达上游；原始溢出 error 对象到达调用者，安装版 pi-ai 的溢出识别函数确认能识别。不是模型采样或裸 DSH 对照。
- 预算计数端点错误不会再阻止生成；错误仍在证据内。
- `test_engineering_m12.py`、`test_engineering_m11.py`、`test_model_settings.py`、`test_consultation.py`：18 passed。
- 角色诊断修改后，`test_consultation.py`、`test_host.py`、`test_chat.py`、`test_engineering_m4.py`：28 passed。
- 删除约束条数门槛后，`test_host.py`、`test_chat.py`：16 passed，包含 9 条自然语言约束仍只发布一次、不创建行动的回归。

## 重载后的真实 Web 结果

证据根目录 `reports/ui-be5e20e65bdc`。角色会话仍为 `s-bfae7340c85335c3a12b3eb13d188a57af7101c1`，本机 `character_context` 与重载前相同；行动 `task-ep-06ca4f5b722d1b75c2263a9958f88450` 沿最初 `task-ep-1aec8ca7d9b7e07a438b8c343777c536` 的执行绑定继续并返回。不是恢复模型 KV 的声明。

本机 Web 记忆输入「晴页923／待核对」已得到角色确认、原文持久化与 READY 索引，截图为 `web-memory-confirmed.png`。

随后真实任务反馈达到 **79,971 token**，上游返回 HTTP 400 `exceed_context_size_error`（`00780-provider.response.json`）。这次错误被原生识别；原生 compaction `0c5de9c9-9a1c-4f59-a51a-5a6a7643ae2b` 自动开始并结束，压缩原日志 seq 5–99。摘要请求 53,413 token，摘要用量包含 756 输出 token；摘要保留测试记忆与 spool 误诊纠正。原请求继续运行，反馈 episode `ep-a70b2750809c265a918822dc8089769a` COMMITTED。**这验证了真实 overflow → 原生压缩 → 原调用继续，没有点击新上下文、手动 compact 或更换会话。**

20:03 正常重启后，20:04 的 Web 提问未包含答案，episode `ep-285c1fc3a1172bf6ff5f03a7c24459bb` 正确回答「代号『晴页923』，在『待核对』栏」。新证据根为 `reports/ui-2c4e372acddf`。检索 manifest 为 `server_vector_rrf / vector_verified=true`，新原文 vector rank 1、独白 rank 2，相关独白进入 selected/context；本机角色会话与重启前相同。证明重启后召回与连续性，不声称答案只来自 RAG。

已检查四个实际群会话的 34 个序列化角色请求，无「晴页923」本机 canary；详见 `c3-group-scope-check.json`。它证明本次请求中的隔离，不冒充所有权限情形覆盖。

四条邀请均由 Web 的对应群场景提交并已实际送达，平台 message ID 分别为：54369546 → 1920554487；638473184 → 1476305072；1002866238 → 484822576；905393941 → 1260262355。后两条原失败邀请通过一次性维护脚本验证保存决策仅违反旧 maxItems 限制、无已发输出和任务后，回到既有 DECISION_ACCEPTED 阶段，由正常启动队列完成；没有重复另外两群，也没有新建通用恢复框架。

小满的最小锁修复行动 `task-ep-c4b57111de63dfba8ddc844bc707f2d0` 已返回：删除 TTL/heartbeat/PID namespace 检查，改为内核 flock 持有 fd；85 项离线 selftest 通过，重启后真实入站继续。Codex 没有代写 adapter。

## C 当前发现的回复归属缺口

群 638473184 的原始消息 `in-ep-bc00ffec1ead478f53ff78368fac020d` 包含两个真实 at 段及其位置，规范化后正文却成了“你刚刚回复  了么？”。账号列表仍在，但不足以保存句子结构。同时宿主历史只投影正文和 author，省掉出站实际 platform_reply_to，角色无法直接区分此前回复了谁。真实回执显示深海设备那条实际回复的是 673225019，不能当作回复了被问及的 2910137276。

Codex 为宿主上下文补当前 scene/epoch 内的回复目标和来源人物；同平台 ID 的其他场景不进入查询结果。实际原记录的只读重投影保存在 `c-group-reply-projection.json`，它不是新的模型验收。`test_host.py`、`test_consultation.py` 共 19 passed，包括跨场景同号不串入回复前文的回归。

适配器的真实 at 位置保留已通过正式 Web 交给小满沿原行动会话开发；使用已有 text 和 mentioned_account_ids，不扩展协议或权限。`task-ep-abad6156c6cc399f7aec79d8f0fb0ab8` 16 步后 RETURNED，离线 selftest 88 pass / 0 fail，停止旧适配器、启动修复版并核对 READY。新版本收到真实群 1002866238 的 `in-ep-b9886b1fb7d5f5549c015ab3813a80c4`：raw 为真实 at 3404612838 + 正文，宿主 `text` 为 `@3404612838 对于NSFW的提示词，你有什么建议？`，提及 ID 来自 raw segment。另一个 `in-ep-c503d2815acf400d82ea2bd42d830efb` 同样保留开头位置与 reply segment，未触发 bot 唤醒；具体源身份不扩大。这验证了在线新版入站表示，不将离线自测当 QQ 验收。

用户在真实群又指出出站 `@qq:账号` 只作为文字，不能真正提醒该人；现有 adapter 的群 outbox 只编码 reply/text 两类 segment，源码可定位。已沿 Web 交给小满继续原适配器路径修此具体问题，宿主 API 不增加字段，目标及发布继续原绑定。该项与宿主上下文修复加载后的端到端复查仍待完成。C/N4–N6 不宣称全部通过，D 尚未接线或验收；不把咨询、timer 到期或保存文字冒充成长。

第一次出站修复行动 `task-ep-35ef1dd7c79bb453a74d99d9cd738120` 做了 12 个工具步骤后遇到真实 `max-tokens`，被记录为 BLOCKED，未谎报完成；角色反馈 episode `ep-5e3fa8b0ba2c2e3a5b2040dc6ace221a` 已关联原行动会话创建续接任务。QQ 在线旧发送器继续运行，直至修复版实际启用。此项不更改模型上限或增设任务终止门槛。

该续接在 0 个工具步骤后再次遇到真实 `max-tokens`。对应上游 HTTP 200 `finish=length`、8191 completion tokens，正文仅留下「继续。先把出站编码改进 outbound.py」，大部分输出为 23291 字符内部推演；不是 `INPUT_BUDGET_EXCEEDED` 或工具失败。经 Web 向原角色提供具体诊断后，下一续接 `task-ep-22a07d5cd4d941ba6e8851346ce958ed` 直接改动 `qqadapter/outbound.py` 与离线测试，随后启用快照 `7d5279de00294cc0b3025a45c891a1a2`。不改模型配置或新增限步。

授权群 638473184 的单条 Web 场景测试 episode `ep-3e6182ef218e2112ce8abec261c95e72` 由角色公开澄清，正文带 `@qq:2910137276`；实际 outbox 平台回执 `DELIVERED`，message ID `1145102496`。启用快照的 `outbound.py` 与开发目录 SHA-256 一致；适配器持久发送日志同一 publication/attempt/message ID 记录 `segments:["at","text"]`、`retcode:0`、`platform_accepted`。这证明经 Web→角色 SPEAK→outbox→OneBot at+text→平台接受的链路，不从文字外观推断平台提及。续接任务在此记录时尚未返回，宿主 context.py 的回复归属补丁也尚未重载。

该续接随后 20 步 RETURNED，离线 selftest **99 pass / 0 fail**；真实回执如上。角色行动报告也明确：平台接受含 at 段仍不足以证明 QQ 客户端已显示提醒；当前既有 API 白名单没有 `get_msg`，没有擅自增加新接口。由于一次诊断消息在旧续接任务尚未返回时已经入队，角色又启动一项同目标行动 `task-ep-dbc728dc4e73c4e745becb0c21198419`，属于 Codex 交接造成的重复工作；检查其实际步骤，不把它当新需求或再发群邀请。

重复任务只做 2 个只读状态核对步骤，发现前项已完成，没有修改文件、领取 outbox 或重发邀请，随后 RETURNED。检查无运行中的任务与角色阶段后通过 Web 正常停止并重启宿主。Web 页面重新连接且原场景仍可浏览。重启后授权群 638473184 的 Web owner 提问 episode `ep-8ab4d29ddcb329aa5a3e9a467565f7d1` 的保存上下文，`delivered_history` 有同场景的 `reply_to`、`reply_to_message.author`，可区分此前答给 owner 和答给 2910137276 的消息；角色回答「那段回复实际是回给你的，我后来向清尘璃落澄清了这一点并询问他是否愿意继续聊」，平台回执 `DELIVERED`、message ID `1927644098`。此轮正确答案也受已经保存的本群对话影响，不把它独占归因于新字段。

到此本轮已知入站 @ 位置、出站真实 at、回复归属的宿主缺口均有对应修复和实测。QQ 客户端是否显示提醒仍需客户端可见证据；本报告只称平台接受含 at 段。N4–N6 的全部场景和 D 自主成长仍分别验收，不因这三项通过而自动判全阶段通过。

本机 Web 普通聊天又提交一段 **465 字 / 1,390 UTF-8 字节**的长笔记，末尾新细节为「归航923／复核备忘」。原文 `in-ep-99137f3fe8f8dc7e121009318af356a6` 完整持久化且 ingress COMPLETE；原文末尾位于第 2/2 个分块 `chunk-ec530a6e959dd89ad876ded9abb892206cf2e9a2e48bcb946d0516682732616e`，embedding_status READY，角色独白也单独 READY。证明本次输入没有旧 400 字/900 字节截断；细节离开近期尾部后的自然召回还未做，不把保存成功写成完整 N6 通过。
