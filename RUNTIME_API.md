# 宿主接入 API（ADR-003 A，2026-09-22）

Python 宿主与通道接口使用平台无关的规范化信封；OneBot 解析、WS 连接和 echo 关联属于行动脑开发的 adapter。2026-09-22 已核实一条授权 QQ 私聊的真实入站、角色回复和平台成功回执，用户确认收到；验收范围与待验项见 `docs/ADR0031-CORRECTION-REPORT.md`，不能从进程状态推断其他场景的收发成功。

## 运行和授权

`start-asuna.cmd --port 8767` 启动同一常驻宿主及现有 DSH Web 工作台，打开 `http://127.0.0.1:8767/asuna/`。不传端口时为 8765。浏览器关闭不停止服务；页面“停止服务”停止宿主，或在启动窗口按 Ctrl+C。再次启动恢复已持久接收、尚未处理的输入。交互、开发任务和运行验收使用 Web。

`RuntimeHost` 拥有 Application、原 Chat 的角色/行动队列、记忆索引线程和可选 ChannelServer。全局角色 lane 保持串行，场景内有序，同场景最多连续两个回合后让出给其他等待场景；行动队列独立。队列接收不调用检索、embedding 或模型。

通道配置为基础配置同目录下的 `asuna-channel.local.json`（已 Git 忽略）；只有 `enabled: true` 才加载。结构见 `config/asuna-channel.example.json`。实际已启用的连接与对象以本次 profile 和 CONNECTION_NOTES.md 为准；宿主监听可用不等同 adapter 已接通。固定 token 与 NapCat token 是两种凭据，不要写入技能、聊天或普通任务文件。

宿主支持显式配置的私聊和群路由。账号、发言人、场景和目标均由配置绑定，不能从请求填写内部权限。不同连接 token 必须不同且至少 24 字符。私聊路由及群内各成员使用 `.runtime/channels/` 下独立工作目录，不能与本机或其他资源目录包含/重叠；普通任务仍走原 WSL 沙箱与无网络策略，不获得宿主或 NapCat 凭据。角色与行动上下文使用既有 scope 绑定。未配置资源的场景不获得 owner 工作区。

监听仅在 `127.0.0.1:<port>`，默认 8766；没有启用通道时不启动此监听。不经 Web 代理开放通道接口。所有请求须带 `Authorization: Bearer <该通道 token>`，身份绑定由宿主校验。不支持跨本机/QQ 身份合并或运行中修改 ACL。adapter 是否实现群传输须独立核实，不能从宿主接口可用推断实际收发成功。

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

群信封仍发送到同一 events 接口：`route_id` 使用配置的群路由，`sender_id` 为实际发言者，并增加 `group_id`（字符串）、`mentioned_account_ids`（真实 at segment 中的账号字符串数组）、可选 `reply_to`（真实 reply segment 的平台消息 ID 字符串）。私聊禁止这些群专用字段。宿主检查群 ID 和配置成员，再根据真实提及、已保存的回复链决定唤醒；普通旁听正文持久保存但不必调用模型。不能把文本中的 @昵称 当作真实 at，不能把非空 reply 一概当作回复角色。不同群、私聊必须分别路由；未经配置的群或成员不能提交。纯非文本内容仍不冒充已理解。

本机 owner 可在已配置 `operator_sender_id` 的群场景中通过 Web 请求角色公开发言；该输入标明 `owner_group_prompt`，不是伪造 QQ 来信。群成员不会因此获得本机 owner 权限。

群消息 `text` 应保留原句中真实提及的位置，例如将真实 at 段呈现为 `@2910137276`，不能把“你回复 @2910137276 了吗”压成“你回复  了吗”。这只是正文的可读表示；唤醒仍只使用真实 segment 产生的 `mentioned_account_ids`，普通正文里的 `@` 不升级成平台提及。平台解析仍归 adapter，宿主不解析 OneBot raw。

原文保存发生在检索与模型之前；记录 `ACCEPTED → PROCESSING → COMPLETE/FAILED`，角色 episode 保存其独立执行状态。关闭或丢失客户端不影响处理。恢复时扫描 ACCEPTED/PROCESSING，复用既有 lane 回执；旧版检索失败且尚未创建 episode 的输入可按原身份恢复。可选检索故障会作为诊断交给角色，继续使用当前授权场景的直接历史，不假称已召回记忆。权限变更会重新校验。用户取消不恢复；操作结果未知时不重复该动作，但诊断与已有结果仍可回传。经明确续接的中断角色生成保留原场景、原输入与错误记录；不会重做已保存的工具操作或公开输出。

行动脑可直接以自然语言返回，不要求 `task_status`。`RETURNED` 仅表示原生行动回合已返回，不是目标完成证明；工具事实由宿主附加。继续同一目标时，角色可关联已有任务，宿主仅在相同主体、场景、权限 epoch 和集成授权下续用原行动会话。普通工具错误留在 DSH 执行回路；扩展层逃逸错误保留原始诊断并回传，不把整项任务统一封成 UNKNOWN。平台发送的 UNKNOWN 与禁止盲目重发规则仍按下文执行。

运行中的行动会话不能同时被第二个任务接管，拒绝原因仍交给角色解释。宿主停机撤销旧进程权限后，新的明确续接请求可复用 `host_stop` 任务的原会话；旧任务权限不恢复，用户取消不适用该续接。集成子进程运行期间不持有宿主数据库副作用锁，因而可以回调 outbox 和回执接口。

## 领取公开输出

`GET /v1/channels/qq/outbox?wait_seconds=25`，最长等待 25 秒；无消息返回 `{"items":[]}`。有消息时原子领取一条：

```json
{"items":[{"publication_id":"ep-…:speak:0","attempt_id":"…","target":{"type":"dm","id":"AUTHORIZED_PEER_ACCOUNT"},"text":"角色实际 SPEAK 正文","reply_to":"原始平台消息 ID"}]}
```

只返回该连接的公开 SPEAK，不返回独白、trace、模型指令或其他场景。目标冻结在源事件与授权路由；行动回传追溯最初的外部消息，内部 feedback UUID 不作为 reply target。消息领取前再次校验目标、policy epoch 与行动意图；失效待发项标 FAILED。

群出站的 `target` 为 `{"type":"group","id":"已授权群号"}`；adapter 核对群 allowlist 后使用对应平台群发送操作。公开正文必须来自这条 outbox；不能由 adapter 自行创造测试文字或透传 owner 指令。`reply_to` 可能为空（例如 owner 主动群发言），非空时才附加平台回复 segment。

群内实测还发现角色公开正文中的 `@qq:2910137276` 被当作普通 text 发出，QQ 上不会真正提醒该人。adapter 应将群公开正文中的明确 `@qq:<数字账号>` 标记按原位置编码成 OneBot at segment，保留其余文字和已有 reply segment；`@全体` 及普通 `@昵称` 不因这个标记获得平台提及。私聊传输和宿主 outbox 字段不变，实际发布目标仍由宿主绑定。转换只决定平台消息的表示形式，不增加角色生成或授权步骤。

生成只标 `QUEUED_EXTERNAL`，领取标 `SENDING`。宿主不会插入本地 sink 回执并假称 QQ 成功。每次领取只有一个持久 attempt；不要为等待消息调用模型。

## 回执

`POST /v1/channels/qq/outbox/<publication_id>/receipt`，路径中的 publication_id 可 URL 编码：

```json
{"attempt_id":"领取时的值","status":"platform_accepted","platform_message_id":"真实平台消息 ID","response":{"原始API响应":"保留实际内容"}}
```

`status` 为 `platform_accepted`、`failed` 或 `unknown`；`response` 必须为对象，成功必须提供非空字符串 `platform_message_id`。结果分别为 DELIVERED、FAILED、UNKNOWN。成功记录 `delivery_basis=platform_ack`，只表示平台接受，不表示已读。完全相同的回执可重报；不匹配 attempt 或冲突终态拒绝。原始响应由受信 adapter 提供，宿主不声称独立向平台查证它。

发送断连/超时且不能核实时用 unknown；重启发现遗留 SENDING 也标 UNKNOWN，永不自动重新领取。若后来得到原 attempt 的确切回执，可补报。回执与权限再次变动有竞争时，仍保存已发生的发送事实，不因此授权一次新发送。当前没有自动重发或人工重发 API，失败正文保留，不要求模型重写台词。

## 状态、证据与边界

Web 可选择本机及已配置的外部场景，查看原文、排队状态、角色与行动过程、失败 traceback。外部私聊只读；已配置 operator_sender_id 的群可由本机 owner 提交明确标注的群发言指令。启用集成 profile 后，检查器“集成”显示进程及日志，“停止集成”停止并取消自动恢复。Web 服务自身退出会停止本次宿主；单独关闭浏览器不会。

`tools/probe_host_seam.py --debug` 是真实 Mongo/HTTP 的隔离工程重放，使用 FakeLane、独立 `asuna_v2_test_host_*` 库和显式回执替身，不联系 QQ、不调用真实模型、不代替 Web/QQ 验收。重复/丢队列/公开输出/unknown/迟到回执的探针结果保存在 `reports/host-probe-*`。

## 受管理集成运行器（B 基础设施）

基础配置同目录的 `integration.local.json` 控制唯一 owner profile，示例见 `config/integration.example.json`。`enabled` 必须为 true，`scene_id/person_id` 必须与本机 owner 配置一致。文件和运行目录均 Git 忽略。示例 profile 没有端点；实际集成任务仅使用 owner 已核实并明确配置的端点和目标，见 CONNECTION_NOTES.md。

在 Web 发送消息前勾选“本条授权集成开发”，该授权写入持久输入、实际委托和任务回传；发送后勾选自动清除。聊天文字不能授予权限；外部通道不能提交该标记。普通任务仍只能使用原工作区与无网络沙箱。任务修订按新输入重新核定权限。停止已启用服务使用独立“停止集成”，普通任务取消不等同撤销此前的持久启用。

| 工具 | 实际能力 |
|---|---|
| `integration_dev(argv)` | 无网络 WSL sandbox；`/task` 对应 `.runtime/integration/owner/development`，与普通工作区分开；30 秒上限。可读写自己的代码、依赖文件与 SKILL.md；启动时放入本文，供开发读取 |
| `integration_test(argv, timeout=30)` | 冻结开发目录为只读 `/app`，运行 1–60 秒；独立可写 `/data`；返回真实 exit_code、stdout/stderr 日志及 timed_out |
| `integration_start(argv)` | 显式启用冻结副本，长期运行；已有运行进程时拒绝替换，需先停止。后续开发文件不会自动部署 |
| `integration_status()` | 当前进程状态与有界日志；RUNNING 只说明进程存在 |
| `integration_stop()` | 停止整个命名空间并取消自动恢复，保留源文件、副本和日志 |

argv 直接进入隔离进程，不经过宿主 shell。默认 Python 为 WSL 的 `python3`；配置通过只读 `/integration/config.json`（环境变量 `ASUNA_INTEGRATION_CONFIG`）提供，内容为 `{"endpoints": {"名称": {"host":"127.0.0.1","port":内部端口}}, "adapter": adapter_config}`。adapter_config 是 owner 显式填写的平台连接资料；不得向普通任务、聊天或技能文件复制凭据。工具结果和 Web 隐藏 token/password/secret/key 字段对应值，完整有界日志仅保存在本机忽略目录。

网络配置 `endpoints` 最多 8 项，每项为 `{"name":"host","host":"已核实的本机或LAN IP","target_port":实际端口,"port":隔离进程内端口}`。名称和内部端口须唯一，两种端口范围均为 1024–65535。连接地址必须是字面 IP；配置不会推测或扫描 NapCat 端口。宿主的可信 WSL supervisor 仅向这些固定 TCP 目标转发；隔离进程在自己的网络命名空间中通过 localhost 内部端口使用 HTTP/WS 等协议。没有 DNS、默认路由、任意 CONNECT 或外部入站监听；目前支持主动连接的传输，不支持 NapCat 向该命名空间发起反向连接。依赖需在现有 `/usr` 中或自行放入开发目录；不默认开放包仓库或互联网。

部署路径为现有 Ubuntu WSL + bubblewrap `--unshare-all --cap-drop ALL`，实测 UID 1000；只读系统 `/usr`、程序 `/app`、本次配置和固定目标 Unix relay，可写范围仅 `/data`、私有 `/tmp`。不挂载 Windows owner 目录、普通工作区、技能库或 Mongo 凭据。每进程地址空间 512 MiB、单文件 8 MiB、打开文件 128；每次运行单输出流累计超过 8 MiB 时终止，保留最后约 256 KiB 日志。快照限制 2000 个文件/64 MiB，拒绝软链接、junction 和特殊文件。

启用清单保存在 `.runtime/integration/owner/enabled.json`。宿主正常停止时关闭子进程、保留清单；重新启动恢复同一冻结副本，开发目录半写文件不会上线。profile 有变化则暂停恢复，要求 owner 重新明确启动；不会自动循环重启崩溃服务。跨进程锁避免两个宿主同时管理同一目录。父宿主异常退出时 stdin EOF 通知 supervisor 停止命名空间；停止未确认会报错，不假称已停止。

停止和超时终止整个命名空间；`exit_code` 是被监督的 bubblewrap 退出码。正常完成时沿用子命令退出结果，强制停止的 `-15` 不证明脚本自己的信号处理器执行完毕。Web 当前展示进程和日志，不提供 `/data` 文件浏览器；只有首行日志也不证明发生截断，脚本可能只输出了一行。

QQ 私聊已按现有授权接通；新增群范围仍须核实账号、成员和 adapter 对应能力，再从 Web 发起并核对真实平台回执。运行器不实现 OneBot 协议，也不把进程启动当平台回执。
