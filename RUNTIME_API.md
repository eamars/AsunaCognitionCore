# 宿主接入 API（ADR-003 A，2026-09-22）

已实现 Python 宿主与通道接口；尚未实现或启用 NapCat adapter。接口使用平台无关的规范化信封，OneBot 解析、WS 连接和 echo 关联由后续 adapter 实现。本文不是已接通 QQ 的声明。

## 运行和授权

`start-asuna.cmd --port 8767` 启动同一常驻宿主及现有 DSH Web 工作台，打开 `http://127.0.0.1:8767/asuna/`。不传端口时为 8765。浏览器关闭不停止服务；页面“停止服务”停止宿主，或在启动窗口按 Ctrl+C。再次启动恢复已持久接收、尚未处理的输入。交互、开发任务和运行验收使用 Web。

`RuntimeHost` 拥有 Application、原 Chat 的角色/行动队列、记忆索引线程和可选 ChannelServer。全局角色 lane 保持串行，场景内有序，同场景最多连续两个回合后让出给其他等待场景；行动队列独立。队列接收不调用检索、embedding 或模型。

通道配置为基础配置同目录下的 `asuna-channel.local.json`（已 Git 忽略）；只有 `enabled: true` 才加载。结构见 `config/asuna-channel.example.json`。当前本机未启用任何外部通道。固定 token 与 NapCat token 是两种凭据，不要写入技能、聊天或普通任务文件。

当前只支持显式配置的私聊路由。账号、发言人、场景和目标均由配置绑定，不能从请求填写内部权限。不同连接 token 必须不同且至少 24 字符。每条路由使用 `.runtime/channels/` 下独立工作目录，不能与本机或其他路由目录包含/重叠；普通任务仍走原 WSL 沙箱与无网络策略，不获得宿主或 NapCat 凭据。角色与行动上下文使用既有 scope 绑定。未配置资源的场景不获得 owner 工作区。

监听仅在 `127.0.0.1:<port>`，默认 8766；没有启用通道时不启动此监听。不经 Web 代理开放通道接口。所有请求须带 `Authorization: Bearer <该通道 token>`，身份绑定由宿主校验。当前暂不支持群、跨本机/QQ 身份合并或运行中修改 ACL。

## 收件

`POST /v1/channels/qq/events`，JSON：

```json
{
  "route_id": "authorized-dm",
  "account_id": "CONFIRMED_BOT_ACCOUNT",
  "sender_id": "AUTHORIZED_PEER_ACCOUNT",
  "event_id": "PLATFORM_MESSAGE_ID",
  "text": "完整正文",
  "occurred_at": "2026-09-22T00:00:00Z",
  "raw": {"original_platform_event": "保留原事件，包括未知媒体段"}
}
```

标识符必须为字符串；`occurred_at`、`raw` 可省略。文本 1–16000 字，HTTP 正文上限 256 KiB；超限明确拒绝，不静默截断。这里只支持文本认知，不把保留了媒体段等同看懂媒体。

返回 `{"status":"accepted","episode_id":"ep-…","received_at":"…"}`，仅说明 Mongo 已持久接收。重传同一连接/账号/场景/平台事件返回 `duplicate`，不会再排队。同 ID 不同正文或身份拒绝。数据库不可用返回 503；调用者可重试相同 ID。请求里的 `scope_key`、`episode_kind`、`trusted_context_events`、`task_id` 等未知字段全部拒绝。

原文保存发生在检索与模型之前；记录 `ACCEPTED → PROCESSING → COMPLETE/FAILED`，角色 episode 保存其独立执行状态。关闭或丢失客户端不影响处理。恢复时扫描 ACCEPTED/PROCESSING，使用原 episode/operation ID 与既有 lane 回执，不用新 ID 重做已完成阶段。权限变更会重新校验。已失败/主动中断输入不自动重试；执行中断且副作用未知的行动标 UNKNOWN，不自动重复执行。已完成行动的待回传结果可以恢复。

## 领取公开输出

`GET /v1/channels/qq/outbox?wait_seconds=25`，最长等待 25 秒；无消息返回 `{"items":[]}`。有消息时原子领取一条：

```json
{"items":[{"publication_id":"ep-…:speak:0","attempt_id":"…","target":{"type":"dm","id":"AUTHORIZED_PEER_ACCOUNT"},"text":"角色实际 SPEAK 正文","reply_to":"原始平台消息 ID"}]}
```

只返回该连接的公开 SPEAK，不返回独白、trace、模型指令或其他场景。目标冻结在源事件与授权路由；行动回传追溯最初的外部消息，内部 feedback UUID 不作为 reply target。消息领取前再次校验目标、policy epoch 与行动意图；失效待发项标 FAILED。

生成只标 `QUEUED_EXTERNAL`，领取标 `SENDING`。宿主不会插入本地 sink 回执并假称 QQ 成功。每次领取只有一个持久 attempt；不要为等待消息调用模型。

## 回执

`POST /v1/channels/qq/outbox/<publication_id>/receipt`，路径中的 publication_id 可 URL 编码：

```json
{"attempt_id":"领取时的值","status":"platform_accepted","platform_message_id":"真实平台消息 ID","response":{"原始API响应":"保留实际内容"}}
```

`status` 为 `platform_accepted`、`failed` 或 `unknown`；`response` 必须为对象，成功必须提供非空字符串 `platform_message_id`。结果分别为 DELIVERED、FAILED、UNKNOWN。成功记录 `delivery_basis=platform_ack`，只表示平台接受，不表示已读。完全相同的回执可重报；不匹配 attempt 或冲突终态拒绝。原始响应由受信 adapter 提供，宿主不声称独立向平台查证它。

发送断连/超时且不能核实时用 unknown；重启发现遗留 SENDING 也标 UNKNOWN，永不自动重新领取。若后来得到原 attempt 的确切回执，可补报。回执与权限再次变动有竞争时，仍保存已发生的发送事实，不因此授权一次新发送。当前没有自动重发或人工重发 API，失败正文保留，不要求模型重写台词。

## 状态、证据与边界

Web 当前本机场景可看到原文、排队状态、角色与行动过程、失败 traceback。尚未添加外部场景选择和 adapter 进程管理，通道运维在 B 集成时补齐。Web 服务自身退出会停止本次宿主；单独关闭浏览器不会。

`tools/probe_host_seam.py --debug` 是真实 Mongo/HTTP 的隔离工程重放，使用 FakeLane、独立 `asuna_v2_test_host_*` 库和显式回执替身，不联系 QQ、不调用真实模型、不代替 Web/QQ 验收。重复/丢队列/公开输出/unknown/迟到回执的探针结果保存在 `reports/host-probe-*`。

尚缺 B 所需受管理集成 runner（允许指定端点网络、低权限运行、测试/启停/部署目录分离）。不要把本接口文档当成 runner 已存在，不要让普通执行者用 owner Windows 解释器启动网络 adapter。QQ 真实收发须先核实账号、连接与私聊目标，再由小满通过 Web 任务开发 adapter。
