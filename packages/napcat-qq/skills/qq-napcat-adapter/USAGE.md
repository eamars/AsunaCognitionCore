# 使用说明（运维向）

## 启动 / 停止 / 看状态

- 启动：`integration_start ["python3","/app/adapter.py","--service"]`（启用的是**已发布**适配器的冻结副本；未发布的候选改动不会在这里上线，宿主重启后恢复当时已发布的版本）
- 停止：`integration_stop`（只停我们这个命名空间，不碰 NapCat 和旧机器人）
- 状态：`integration_status` 看有界日志；`/data/health.json` 看计数器、连接位、`group_routes`、`peers`（身份目录规模）
- 看身份目录：`--peers` 是只读导出、不联网，可用 `integration_test` 试跑（跑的是开发候选的冻结副本，它的 `/data` 与启用服务的数据分开——那里看到的是测试数据目录，不是运行中服务的目录）。运行中服务的目录规模看 `integration_status` 日志里的 `PEERS` 行与它 `/data/health.json` 的 `peers` 段；目录文件在 `/data/peers/peers.json`，变化流水在 `/data/journal/peer_changes.jsonl`
- 宿主 profile（端点或 adapter 配置）改过之后，自动恢复会拒绝并回 `PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START`；这是运维要求，显式 start 一次即可

## 日志行含义

| 行首 | 含义 |
|---|---|
| `WS_UP path=/event gap_seconds=first` | 事件连接建立；`gap_seconds` 是上次断开到重连的空档，正向 WS 不补发这段时间的事件 |
| `CONFIG ... routes=... allowed_groups=... group_members=route:人数` | 生效的路由与群成员快照规模（不含密钥） |
| `IDENTITY {... match=true}` | 只读 `get_login_info` 结果，登录号与配置账号一致才继续 |
| `READY ... ws_event=up ws_api=up` | 真正可收可发；只有 RUNNING 不算 |
| `INBOUND_SPOOLED event_id=... route=... scene=private\|group group=群号 mentions=N at_all=N reply=0/1 media=N media_types=image,face media_only=True/False` | 已授权入站先落盘（此时还没提交）；mentions 只数真实 at 段，at_all 是 `@全体` 段计数，reply 表示带真实引用段，media 是图片/表情/语音等非文本段个数（`media_only=True` 就是 0.3 会被 `no_text` 丢掉的那类）。群正文里的真实 at 会渲染成 `@账号`，所以带提及的消息 `chars` 比旧版大（每个提及多 8-15 字），不是正文变长了那么多话 |
| `INBOUND_ACCEPTED / INBOUND_DUPLICATE` | 宿主已持久接收；duplicate 是重传，正常 |
| `INBOUND_IGNORED reason=...` | 被闸门丢弃，只记元数据：`nonmessage` / `wrong_self` / `self_echo` / `unauthorized_sender` / `unauthorized_group_member` / `group_not_allowed` / `group_route_missing` / `no_text` / `duplicate_local` / `bad_shape` / `unsupported_message_type`。0.4 起 `no_text` 只对应「既没文字也没图/表情/真实引用段」，纯图会落盘 |
| `INBOUND_RETRY / _REJECTED / _FAILED` | 提交失败：可重试 / 宿主拒绝（正文或字段不合规）/ 重试到上限（已进 journal，不静默） |
| `OUTBOX_CLAIMED pub=... target=dm:号\|group:群号` | 领取到一条公开输出 |
| `SEND_RESULT ... target=dm\|group status=platform_accepted retcode=0 platform_message_id=...` | 平台真的收了；`delivery_basis=platform_ack`，不等于已读 |
| `SEND_RESULT ... status=failed retcode=14xx` | 平台明确失败，正文留在宿主 |
| `SEND_RESULT ... status=unknown` | 结果不明（超时/写失败），**不会重发** |
| `ATTACHMENT pub=... attempt=... fetched=<sha 前缀> bytes=N sha256=...` / `reject=<原因>` / `fail=<原因> detail=...` | 私聊出站的图：字节从宿主端点取（不读宿主文件路径）；reject/fail 都发生在**发送之前**，一条也没发出去，回执 `failed`。常见原因：`attachment_target_not_enabled`（群）、`attachment_fetch_sha256_mismatch`、`attachment_fetch_over_limit`、`attachment_not_an_image`、`attachment_fetch_unavailable` |
| `ADMIN_CLAIMED pub=... target=group:群号 kind=mute|unmute|kick|recall` / `ADMIN_RESULT pub=... action=set_group_ban status=... retcode=...` | 宿主排队的群管理动作；只有这三个 action，平台 retcode 就是回执（0 算 platform_accepted），流水在 `journal/admin.jsonl` |
| `RECEIPT_OK / _SPOOLED / _REPLAYED / _REJECT` | 回执上报结果；spool 里的会在下一轮重放 |
| `LATE_ACK pub=...` | 超时后平台响应才到，按同 attempt 补报 |
| `PEERS {"people": N, "scenes": M, "changes": K, "store_reset": null}` | 启动时身份目录快照；`store_reset` 非空表示上次的 `peers.json` 读坏了（已改名成 `peers.json.bad`，身份从头攒起） |
| `PEER person=qq:号 scene=dm\|group:群号 display='..' nick='..' card='..' role=owner\|admin\|member\|unknown source=.. verified=True/False msgs=N changed=-\|card` | 每条已授权入站识别到的人。`display` 是当前该看的名字（有群名片用名片，否则昵称，`display_source` 说明是哪一种）；`source=api` 查过平台、`event_sender` 只是这条消息自带的、`api_error:*` 是没查到（此时 `verified=False`，别当确认过） |
| `PEER_CHANGED person=qq:号 scene=.. field=nickname\|card\|role\|title from='旧' to='新'` | 改名 / 换名片 / 身份变了。`person_id` 不变，所以还是同一个人；旧名字留在 `aliases` 里，换名片只影响那一个群 |
| `PEER_FIELD_DENIED` + `PEER_REPOST event_id=..` | 宿主不收 `raw` 里那块身份，同一条事件已剥掉身份块重投（入站没丢，等价于 0.2.3 的信封） |
| `MEDIA_REPOST event_id=..` | 宿主不收 `raw.asuna_media` 那块，同一条事件已剥掉媒体块重投（入站没丢，占位符正文还在；等价于 `--media-mode off` 的形状） |
| `STATUS ... group_routes=N counters={...}` | 每 60 秒一次心跳摘要（0.3 起 counters 里多 `peer_enriched` / `peer_api_calls` / `peer_api_errors` / `peer_changes` / `peer_field_denied`；0.4 起多 `inbound_media_only` / `media_field_denied`） |
| `SHUTDOWN spool_inbound=N` | 退出时还有 N 条没提交完，下次启动继续 |

日志摘要：`python3 decode_log.py <日志>`（分场景统计入站、按 `target` 分发送结果，并把可疑行列出来）。

## 常见情况

- **STATUS 显示 ws_event=down**：NapCat 重启或网络抖动，退避重连（1/2/5/10/20/30s 封顶）；断连窗口内的事件会漏，adapter 不猜内容。
- **spool_inbound 一直不清**：宿主没在收（503/断连），看 `INBOUND_RETRY`；超过 10 次进 `journal/inbound_failed.jsonl`。
- **改了代码没生效**：代码只经 `development_publish`（`project: "napcat-qq"`）生效，`integration_start` 只运行已发布版本——未发布的候选重启多少次也不会上线。发布后 `integration_stop` → `integration_start` 才换新版本。
- **起不来报 `another adapter process is holding /data/adapter.lock`**：另一个活进程正持有这把 flock（通常是上一个服务还没停干净）。持有者一退出内核就释放，遗留的文件本身不挡重启，所以不需要删 `/data` 里的任何东西；也没有 TTL、心跳或 30 秒等待可等。
- **群消息没进来**：按 `INBOUND_IGNORED reason=` 分辨——`group_not_allowed`（群不在 allowlist）、`group_route_missing`（在 allowlist 但没路由）、`unauthorized_group_member`（发言人不在该群成员快照；名单是快照，新人要等配置更新）、`no_text`（0.4 起只剩真的什么都没有的：单独一个 @别人、单独一个 @全体；纯图/表情现在会落盘，正文是 `[图片（未解析）]` 这类占位符）。
- **群目标发送回执 failed `target_not_authorized`**：outbox 给的群号不在 `allowed_group_ids` 或没有对应路由，adapter 没有发出任何东西。
- **`PEER` 行里 `source=api_error:ApiNotConnected`**：那条入站提交时 `/api` 连接正好没起来，身份只用了这条消息自带的 `sender` 块（`verified=False`）。下一条同一个人的消息会重新查；不影响这条消息进宿主。
- **`peer_api_calls` 涨得比入站快**：不可能，同一个 (人, 场景) 30 秒内只查一次；真出现了先看是不是有人在多个群同时说话（每个群是独立场景）。
- **角色说「看不到你发的图」**：0.4 起图确实进来了，但正文只有 `[图片（未解析）]` 这个占位符——adapter 不下载图片，宿主目前也只把 `event.text` 投进上下文。要看内容得宿主接视觉步骤（`raw.asuna_media.items[].url` 是平台临时地址，带 `rkey` 会过期）。
- **表情刷屏把入站刷爆**：`--media-mode annotate`（纯图仍丢、有字的补占位符）或 `off`（逐字回到 0.3.0），不用改代码。
- **确认没在 @全体**：出站消息段只可能是 `text` 和（群且宿主给了 reply_to 时）`reply`；正文里的“@全体”只是文本。

## 自检

`python3 /app/adapter.py --selftest --offline --data-dir /data/selftest` 是日常那条：**不需要配置文件**，行为断言全跑内置占位夹具（`qqadapter/fixtures.py`，账号/群/成员/端点都是 `9000000xx` 占位号），所以任何一台机器、任何一份授权下跑出来的数字应当一样。0.5.1 实测（含强制时区那组之后）：干净候选无配置文件 `--offline` **279 pass / 0 fail / 3 skip**（exit 0）；加 `--config <现网配置>` 再多 9 条 `live_config_*` 交叉核对 → **288 pass / 0 fail / 2 skip**。同一候选在 `TZ=UTC`、`TZ=Etc/GMT-9`（UTC+9）、`TZ=Etc/GMT+4`（UTC-4）下数字一样——身份时间戳的读法以前会随机器时区变（`peers.epoch()` 把 UTC 串当本地时间读），现在有 `peer_epoch_utc_*` / `peer_cache_window_*` / `peer_rename_forces_lookup_*` 在强制时区下钉住，换机器跑不该再出现「这边绿那边红」。`--config` 只是**可选**的现网配置形状与越界核对（不参与行为断言）；没给就一条 `live_config_cross_check SKIP`；命令行点名的配置读不出来直接 `CONFIG_ERROR` + 退出 2。`--offline` 现在把两条 WS、身份匹配、真实身份读取和领取真实 outbox 一起跳过（各一条 SKIP）——0.4 及之前它只跳过 outbox 领取，那句「照旧会跑 WS」已经过期。不加 `--offline` 的 live 段在没有平台的沙箱里会如实报 FAIL，别拿它的数字当回归基线。

覆盖：配置脱敏与路由/群越界、夹具自身形状（`fixture_*`）、私聊闸门回归、explicit 与 automatic 准入分开（`admission_*` 23 条：名单外的人/群、成员快照、派生路由 `auto-dm-`/`auto-group-`、黑名单在两种模式下都拒、出站该发/不该发）、四群入站规范化（at/reply/文本污染/跨群成员/重复）、媒体段三种 media_mode 与上限、出站参数（action、群号、reply 段、allowlist 外不发、retcode≠0、超时 unknown 不重发）、出站读回核实、附件取字节与失败即不发、身份目录、spool 重启存活与场景化 key、单实例锁的跨 namespace 语义；live 段才是两条 WS、身份匹配、宿主鉴权与 outbox 可读。

合成事件只走本地过滤函数，不提交宿主；平台与宿主在参数测试里是替身（`StubOneBot` / `StubHost`），所以自检既不真发 QQ，也不伪造真实入站。唯一会碰真实状态的是 live 段那一次 `wait_seconds=0` 领取：真有待发项时按 `unknown` 如实回报、不重发，所以群里正聊到一半时用 `--offline`。锁的检查是隔离的（自建临时目录 + 一个子进程持锁），不碰服务数据目录。
