---
name: qq-napcat-adapter
description: 用 NapCat / OneBot v11 正向 WebSocket 接通宿主 QQ 通道（私聊 + 四个授权群）：入站事件先落盘再进宿主，公开出站只来自宿主 outbox，发送结果按平台真实响应回报执（unknown 不重发），发送后还会用 `get_msg` 把自己那条读回来核对段序列（仅观测）；会读清对方是谁（昵称、当前群名片、群身份）并且改名换名片后仍认得是同一个人；私聊出站可带一张宿主指定的图（字节只从宿主通道 API 取，群图未开）；含授权闸门（explicit 显式名单与 automatic 自动准入分开）、群成员快照与 at/reply 规范化、共用账号约束与日志读法；离线自检跑在内置占位夹具上（9000000xx 占位号），不依赖本机私有配置文件。
---

# qq-napcat-adapter

## 用途

把 NapCat（OneBot v11，正向 WebSocket）接到宿主的通道 API，让真实 QQ 成为角色的一条输入/输出通道：

- 入站：`/event` 推来的消息事件 → 授权闸门 → 磁盘 spool → `POST /v1/channels/qq/events`
- 出站：`GET /v1/channels/qq/outbox` 领取 → `/api` 按 target 调 `send_private_msg` / `send_group_msg` → `POST /v1/channels/qq/outbox/<id>/receipt`
- adapter 自己不生成任何文本，不做回显；正文只来自宿主 outbox

## 代码在哪

权威副本在 **napcat-qq 通道包候选的 `integration/` 目录**：代码、技能、文档都只用 `development_*`（带 `project: "napcat-qq"`）修改，经 `development_publish` 生效——`integration_test` 把候选的 `integration/` 冻结成只读 `/app` 试跑（实测：cwd 是 `/app`，往 `/app` 写报 `OSError` 只读文件系统；`/data` 是可写区，与启用服务的数据分开），`integration_start` 只运行**已发布**的版本，未发布的候选不会当管理服务跑起来。目录布局（相对 `integration/`）：

```
adapter.py                     入口：--service | --selftest
qqadapter/config.py            读 /integration/config.json，端点/私聊与群路由/授权校验，describe() 不含密钥
qqadapter/inbound.py           事件 → 信封 + 私聊/群两道闸门 + at/reply 规范化 + 非文本段占位符与元数据 + 按路由去重 LRU
qqadapter/journal.py           磁盘 spool（就是入站队列）、journal、计数器、flock 单实例锁
qqadapter/onebot.py            两条 WS 连接、echo 关联、迟到响应、重连退避
qqadapter/hostapi.py           宿主 HTTP（stdlib urllib），结果分类 ok/duplicate/retry/reject
qqadapter/outbound.py          领取 → 按 target 选 action 发送 → 读回核实（只观测）→ 回执；回执可重报，unknown 不重发；
                               宿主排队的群管理动作（禁言/解禁/踢人/撤回）→ set_group_ban / set_group_kick / delete_msg，平台 retcode 即回执
qqadapter/selfrole.py          自己在每个群的身份（群主/管理员/成员）：get_group_member_info 查本号，缓存十分钟，随群事件放进 raw.asuna_self
qqadapter/service.py           线程装配、身份校验、STATUS/health、入站前注入对方身份
qqadapter/peers.py             对方身份目录：昵称/群名片/群身份 + 改名换名片仍是同一人（ADR-005 一阶段）
qqadapter/selftest.py          离线 + 在线自检（行为断言全跑内置占位夹具，发送用替身；给了 --config 才交叉核对现网配置）
qqadapter/fixtures.py          自检用的内置占位夹具：本号/群/成员/端点全是 9000000xx 占位号，过同一套 Config 校验
vendor/websocket/              websocket-client 1.9.2（随通道包 `integration/` 发布，sys.path 注入）
```

本技能目录只放说明和离线小工具（`decode_log.py`、`USAGE.md`）。集成沙箱不挂载技能库，代码不在这里跑。

## 入口

```bash
python3 /app/adapter.py --selftest --offline --data-dir /data/selftest   # 只读自检：不发送、不伪造入站、不碰平台
python3 /app/adapter.py --selftest --data-dir /data/selftest             # 同上，外加会碰真平台与真实 outbox 的 live 段
python3 /app/adapter.py --service                              # 常驻（integration_start 用这条）
python3 /app/adapter.py --peers --data-dir /data                # 导出对方身份目录（只读，不联网）
```

自检口径（0.5.1 起）：

- 行为断言全部跑在**内置占位夹具** `qqadapter/fixtures.py` 上（本号 `900000000`、四群 `900000001-900000004`、私聊对象 `900000010`、成员 `9000001xx`、名单外的人/群 `900000013` / `900000012` / `900000199`），过的是同一套 `Config` 校验。所以干净候选里没有 `/integration/config.json` 也能跑完，结果不随本机被授权了哪些群而变；本机那份带真实群号的私有路由快照不再是任何检查的输入。
- `--config` 是**可选的现网配置交叉核对**：给了才跑（`live_config_*` 那组，只看形状与越界，不接管行为断言），没给就一条 `live_config_cross_check SKIP`。命令行显式点名的配置读不出来 → `CONFIG_ERROR` 退出 2，不静默退回夹具（坏配置不能藏在绿灯后面）。
- `--offline` 跳过**所有会碰平台的检查**：两条 WS、身份匹配、真实身份读取、领取真实 outbox，各打一条 SKIP；不加 `--offline` 才真连。
- 退出码 0 = 没有 FAIL。SKIP 既不算通过也不算失败，最后一行是 `SELFTEST_SUMMARY pass=… fail=… skip=…`。

可选参数：`--config`（默认 `$ASUNA_INTEGRATION_CONFIG` 或 `/integration/config.json`）、`--data-dir`（默认 `/data`）、`--claim-wait`（outbox 长轮询秒数，上限 25）、`--ack-timeout`（等平台响应秒数，默认 15）、`--no-verify`（关掉发送后的读回核实，纯观测开关）、`--verify-delay`（读回前等多久，默认 0.8 秒）、`--peer-mode full|store|off`（默认 `full`：`full` 记身份目录并把身份块随 `raw` 送出，`store` 只记目录和日志不碰信封，`off` 完全关闭等于 0.2.3 的入站形状）、`--media-mode full|annotate|off` （默认 `full`：图片/表情/语音等非文本段在正文里按原位置留占位符并把元数据送进 `raw.asuna_media`；`annotate` 只在有文字的消息里补占位符，纯图仍按 0.3.0 丢弃；`off` 逐字等于 0.3.0。也可写在配置 `adapter.media_mode`，非法值直接报错）。

## 配置形状（授权只来自配置文件）

```jsonc
"media_mode": "full",                       // 可选：full（默认）| annotate | off，非法值报错
"allowed_private_user_ids": ["900000010"],
"allowed_group_ids": ["900000001", "900000002", "900000003", "900000004"],
"routes": {
  "owner-dm":       {"message_type": "private", "sender_id": "900000010",
                     "target": {"type": "dm", "id": "900000010"}},
  "group-900000001": {"message_type": "group", "target": {"type": "group", "id": "900000001"},
                     "allowed_sender_ids": ["...真实群成员快照，当前 73 人..."]}
}
```

- **本文出现的 `9000000xx` 九位号一律是占位夹具号**（和自检夹具 `qqadapter/fixtures.py` 同一套），不是任何真实账号、群号或成员号；试用记录里的六位 `91xxxx` 是当时的平台消息 ID，也不是号。真实号只存在于部署配置与日志里。
- 群路由必须 `target.type=group`、`target.id` 为群号数字串、`allowed_sender_ids` 非空且全数字；不得带 `sender_id`。
- 群路由的群号必须出现在 `allowed_group_ids`，否则配置直接报错；同一个群被两条路由绑定也报错。
- 在 `allowed_group_ids` 里但没有对应路由 = 该群仍然关闭（入站 `group_route_missing`，出站 `failed`）。
- 私聊路由不接受群字段；私聊路由/目标必须同时是 `allowed_private_user_ids` 成员。
- `adapter.admission`：`explicit`（默认）＝授权面就是配好的名单，名单外一律拒；`automatic`＝按主人的准入策略放行没见过的人/群/成员，adapter 给他们派生 `auto-dm-<账号>` / `auto-group-<群号>` 路由 ID，已配置的目标仍走自己的路由。两种模式**分开断言**（`admission_explicit_*` / `admission_automatic_*`）：一条「这里会拒」的结论只在它被证明的那个模式下成立。
- `adapter.blocked_senders` / `adapter.blocked_groups`：黑名单在准入之前生效，两种 admission 下都拒（入站 `unauthorized_sender` / `unauthorized_group_member`，被黑名单的群没有路由 → `group_route_missing`；出站 `target_not_authorized`）。
- 名单、admission 与黑名单都由核心的 `channels.qq` 派生（`python/napcat_qq/adapter_config`），不是手写的第二套授权。

## 权限与边界

- 只调用 `get_login_info`、`get_version_info`、`send_private_msg`、`send_group_msg`，外加 0.2.3 的 `get_msg`：只查「本次发送自己拿回的那个 platform_message_id」，参数固定 `{"message_id": <整数>}`，不查入站事件里的 id、不查 `reply_to` 的 id、不拉历史。实测过按任意 id 查能读到被闸门丢掉的未授权群正文，所以这条限制是实质性的，不是形式。写类 action 只有宿主排队的群管理动作：`set_group_ban`（mute/unmute，时长 60 秒～30 天，unmute 记 0）、`set_group_kick`（`reject_add_request=false`）、`delete_msg`（撤回，按平台 message_id），群必须已经在授权路由里，平台 retcode 就是回执；除此之外不碰 `mark_msg`、`set_restart`、`clean_cache` 等任何写类 action，也不改 NapCat 配置或进程——账号 900000000 与旧机器人共用，我们只是多挂一个 WS 客户端。
- 0.3.0 起多两个**只读**身份 action：`get_group_member_info`（群场景）与 `get_stranger_info`（私聊）。只对已通过本场景授权闸门的发言人调用；同一个 (人, 场景) 30 秒内不重复查，正常走平台缓存（实测 ~10ms），只有这条消息自带的 `sender` 块和记录不一致时才 `no_cache=true` 去确认（实测 ~450ms）。`get_stranger_info` 会回一大坨个人资料（住址、生日、兴趣、邮箱），代码只取 `user_id`/`nickname`，其余丢弃不落盘；平台替别人回答（返回的 `user_id` 对不上）整包不采信。不查别人的资料、不拉群成员列表、消息正文不进身份目录。
- 入站丢弃顺序（私聊，与 0.1.0 相同）：非 message → self_id 不符 → 自己发的（防回环）→ 发言人未授权 → 什么都没有（`no_text`）→ 本地重复。0.4 起「什么都没有」指既没文字也没图片/表情等非文本段：单独一张图现在会落盘，正文是 `[图片（未解析）]`（平台带 `summary` 的动态表情写成 `[图片:动画表情（未解析）]`）。
- 入站丢弃顺序（群）：非 message → self_id 不符 → 群号缺失 → 群不在 allowlist（`group_not_allowed`）/ 无路由（`group_route_missing`）→ 自己发的 → 发言人不在该群成员快照（`unauthorized_group_member`，在别的群是成员不算）→ 什么都没有（`no_text`）→ 本地重复。0.4 起这道闸门只放宽「有没有内容」的判定、不改位置：有字 / 有非文本段 / 带真实 reply 段 / at 了本账号 → 接受；单独一个 @别人或单独一个 @全体仍是 `no_text`（不会被渲染出的提及蒙混过关）；只有 reply 段的消息用 `[回复消息（无文字）]` 兜底。宿主再根据真实 at / 回复链决定是否唤醒；adapter 只如实上报。
- 群信封额外字段：`group_id`（字符串）、`mentioned_account_ids`（真实 at 段里的账号字符串数组，去重保序；`at,qq=all` 不进数组，只在 meta 计数）、可选 `reply_to`（真实 reply 段的平台消息 ID 字符串）。群正文里每个真实 at 段按原位置渲染成 `@账号`（`@全体` 对应 at all），所以“at 示例角色 + 你刚刚回复 + at 900000101 + 了么？”交出去是 `@900000000你刚刚回复 @900000101了么？`，不会被压成“你刚刚回复  了么？”。这只是可读表示：唤醒仍只看 `mentioned_account_ids`，正文里手打的 `@` 不升级成提及；reply 段不进正文。私聊正文与 0.1.0 完全一致（at 段不进正文），私聊信封也永远不带这三个字段。
- 非文本段（0.4.0）：图片/动态表情/语音/视频/文件/地点/戳一戳/合并转发/json/xml 卡片不再被当作「没内容」。正文里按原位置插一个有界占位符（`[图片（未解析）]`、`[语音（未解析）]`、`[文件:报告.pdf（未解析）]`、`[卡片消息:标题（未解析）]`、认不出的类型 `[mystery消息（未解析）]`），元数据（类型、平台 url≤420 字、文件名≤120 字、大小、`sub_type`）走 `raw.asuna_media`，最多 8 项但 `count` 照实报总数并带 `truncated`。**不下载图片、不新增网络目标、不新增 OneBot action**：占位符只说明「这里有一张图」，不是内容；平台 url 带 `rkey` 会过期，不能当永久地址。宿主想看图得自己接视觉步骤，而它目前只把 `event.text` 与历史正文投进上下文、不投射 `raw`，所以占位符是「现在就能被看见」的唯一路径。私聊信封仍不带群字段，媒体信息只能像 `asuna_peer` 那样往 `raw` 里放；宿主拒收（任何 4xx）则剥掉身份块与媒体块一次性重投，入站不丢。
- 群出站会把角色正文里明确的 `@qq:<数字账号>` 按原位置编码成真实 `at` 段（0.2.2 起）：标记本身从文字里消失，其余文字和已有的 `reply` 段原位保留，所以被点到的人真的被提醒。`@昵称`、`@全体`、`@qq:all`、`asuna@qq:12345` 这种邮箱形状、以及 20 位以上的数字串照旧是 text，不会被提升；私聊出站仍是 0.1.0 的单 text 段形状，标记原样发出。adapter 从不自己造 at-all 段。
- 出站可以带一张图（私聊 0.5.0，群 0.5.2）：outbox 条目带 `attachment`，**只有元数据**（`artifact_id`、`media_type`、`sha256`、可选 `size`）；字节由 adapter 用 `GET /v1/channels/qq/outbox/<publication>/attachment?attempt_id=…&artifact_id=…` 向宿主取（带 Bearer，只按这次的 publication+attempt 取这一份），边读边卡 8 MiB 上限。sha256 对不上、字节不是支持的图片魔数、媒体类型不支持、超限、描述不合法——一律 `failed` 回执且**一个字节都不发**：发一条只带文字的 `platform_accepted` 等于谎报一张对方没收到的图。取到才发：私聊 `[image, text]`，群 `[reply?, image, text/at…]`（`image` 段用 `base64://`），角色正文一个字不丢。「这张在群里谁能看见」由宿主回答（群里只给她自己做的图，宿主在字节端点上再核一次）；adapter 只负责带过去，不认识的目标类型才是 `attachment_target_not_enabled`。领取时声明 `supports=image`，宿主据此决定是否排图；回执 `response.attachment` 带实际发出的 sha256 / 字节数 / `sha256_verified`。**不读宿主文件路径、不新增网络目标**。
- token 不进日志、技能或聊天。

## 语义保证

- 已授权入站先写 `/data/spool/inbound/`，再由独立线程提交；队列积压、宿主 503、进程退出都不会静默丢。文件名是毫秒时间戳+序号，本来就唯一；`route_id` 只是后缀，方便人眼分辨同一个平台 message_id 的不同场景（不是修过什么覆盖故障）。真正防误丢的是本地去重键带路由，提交仍按 `event_id` 幂等，`duplicate` 视为成功；彻底失败进 `journal/inbound_failed.jsonl` 并留原因。
- 本地去重键带路由（`private:<route>:<id>` / `group:<route>:<id>`）：同一个 message_id 在私聊和群里（或在两个群里）是两条事件，不会被误判成重复而丢弃。
- 对方身份（0.3.0）：身份键是账号 `person_id = qq:<QQ号>`，昵称和群名片是挂在身份上的历史。改名或换名片记进 `changes` / `journal/peer_changes.jsonl` 并打 `PEER_CHANGED`，`person_id` 不变，旧名字留在 `aliases` 里，所以换名片不会被当成新来的人。名片按群分开存（同一个人在 A 群的名片不影响 B 群），昵称按人存。查不到平台就照实标 `verified: false` + `source: api_error:*`，不猜。身份块放在 `raw.asuna_peer`（宿主信封是严格白名单，顶层加字段会被 403 `CHANNEL_ENVELOPE_FIELD_DENIED`），信封顶层字段一个没多；任何 4xx 拒绝都会剥掉身份块按原形状重投一次，观测不会吃掉入站。
- 一条 publication 一个 attempt：`retcode==0` 且有 `data.message_id` → `platform_accepted`；`retcode!=0` → `failed`；写失败/超时 → `unknown` 且**绝不重发**。
- 发送被接受后（默认隔 0.8 秒）adapter 用 `get_msg` 把那条消息读回来，核对平台真正存下的段序列与落点会话（0.2.3）。这一步只产出观测：`verified` / `segment_mismatch` / `target_mismatch` / `not_found` / `unavailable` 都不改 `platform_accepted`、不触发重发、不进宿主的状态判定（宿主仍记 `delivery_basis=platform_ack`）；结果附在回执 `response.verification` 里由宿主原样保留，并打一条 `VERIFY` 日志。`not_found` 只重试一次。它证明的是「平台按我们提交的段序列存了这条、落在这个会话、是我们账号发的」，**不证明** QQ 客户端渲染了提醒或对方看到了。
- 回执可重报（同 `attempt_id` 同 payload），失败回执先退避重试再落 `/data/spool/receipts/` 重放。
- 超时后 300 秒内到达的平台响应按同 attempt 补报，不会因此再发一条。
- 单实例锁：对 `adapter.lock` 做一次非阻塞 `flock`，这就是全部机制。活着的进程持有它时第二个进程直接拒绝启动；持有者退出（含被 kill）由内核释放，所以上一次运行留下的文件从不阻塞重启。没有 TTL、没有心跳、没有过期接管，也不需要清空数据目录。宿主 IntegrationRunner 本身已经用 owner.lock 管着单个服务，这把锁只是同数据目录的兜底互斥。

## 观察

- `/data/health.json`（5 秒刷新，含 `group_routes`、`spool_inbound`、`spool_receipts`）、`/data/journal/*.jsonl`、stdout 的 `READY` / `STATUS` / `SEND_RESULT` / `VERIFY` / `RECEIPT_*`；0.3.0 起 health 多一个 `peers` 段（人数/场景数/变化数/目录是否被重置），身份目录在 `/data/peers/peers.json`
- 进程 RUNNING 不等于已接通：看 `IDENTITY ... match=true` 和 `READY ws_event=up ws_api=up`，`CONFIG` 行的 `group_members=` 是各群成员快照人数
- `INBOUND_SPOOLED` 带 `scene=` / `group=` / `mentions=` / `at_all=` / `reply=` / `media=`（非文本段个数）/ `media_types=` / `media_only=`（这条消息一个字都没有，0.3 会丢掉的那类）；`SEND_RESULT` 带 `target=dm|group` 和 `segments=`（真正发到平台的段序列，如 `reply,at,text`）；自己发的群消息若被平台回推会打 `SELF_ECHO ... segments= at_targets=`（NapCat 4.18.0 实测不回推 API 发出的消息，所以这条一般不出现）；`VERIFY` 带 `pmid=` / `result=` / `sent=` / `stored=` / `target_ok=` / `self_sent=`，非 verified 时带 `detail=`。计数里新增 `verify_verified` / `verify_mismatch` / `verify_not_found` / `verify_unavailable`——它们只说明读回对不对得上，不参与发送成败
- 0.3.0 新增身份行：`PEERS`（启动时目录快照）、`PEER person= scene= group= display= nick= card= role= source= verified= msgs= changed=`（每条已授权入站识别到的人）、`PEER_CHANGED person= scene= field= from= to=`（改名/换名片，同一个人）、`PEER_FIELD_DENIED` + `PEER_REPOST`（宿主还不收这块，已去块重投，入站没丢）、`PEER_ERROR`。0.4 起同类的媒体行是 `MEDIA_REPOST`（去掉 `raw.asuna_media` 重投，占位符正文保留），计数多 `inbound_media_only`（纯图/纯表情落盘数）与 `media_field_denied`。`source=api` 是查过平台的，`event_sender` 是这条消息自带的，`api_error:*` 是没查到——不要把未核实的当成确认过的事实
- 日志读法：`python3 decode_log.py <日志文件>`（离线，把日志行翻成状态摘要；0.3 起认得身份行）

## 重新部署

适配器代码、技能、文档都只通过 `development_publish`（带 `project: "napcat-qq"`）生效：冻结候选、过启动探针、激活快照。`integration_start` 只运行**已发布**的适配器（冻结成 `/app`），未发布的候选改动不会在这里上线，宿主重启后恢复的也是当时已发布的版本。所以换新版本的顺序是：`development_publish` → `integration_stop` → `integration_start ["python3","/app/adapter.py","--service"]`。宿主 profile（端点/adapter 配置）变化后，恢复会被要求显式启动一次，返回 `PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START` 时按运维流程重新 start。

## 版本

- 0.1.0（2026-09-21）：NapCat 4.18.0 / OneBot v11，正向 WS，单账号 + `owner-dm` 私聊路由（真实号只在部署配置里，技能不记）
- 0.2.0（2026-09-23）：四群收发（群路由/成员快照/群 allowlist）、at 与 reply 规范化、出站按 target 选 action、本地去重键带路由、单实例锁收敛成一条 flock
- 0.2.1（2026-09-23）：群正文保留真实 at 的位置（渲染成 `@账号`），私聊路径不变
- 0.2.2（2026-09-23）：群出站 `@qq:<数字账号>` → 真实 at 段（按原位置，其余文字与 reply 段不动）；`SEND_RESULT` 多带 `segments=`；新增 `SELF_ECHO` 观测行。私聊形状、宿主 outbox 字段与权限不变
- 0.2.3（2026-09-23）：出站读回核实。发送被接受后按自己拿回的 message_id 调一次 `get_msg`，核对平台存下的段序列与落点会话（群比 `group_id`+`message_type=group`，私聊比 `user_id`+`message_type=private`）。只读观测：不改 `platform_accepted/failed/unknown`、不重发、不扩读面（只查自己那条，`not_found` 重试一次）；新增 `VERIFY` 日志行、`verify_*` 计数、`--no-verify`/`--verify-delay`，回执 `response` 多一个 `verification` 对象（宿主 schema 未变）。出站段形状、入站路径与迟到回执路径不变
- 0.3.0（2026-09-23）：对方身份层（ADR-005 第一阶段）。新增 `qqadapter/peers.py`：按账号存身份，读昵称/当前群名片/群身份/头衔/入群时间，改名与换名片记变化但 `person_id` 不变；身份块走 `raw.asuna_peer`，宿主拒绝则去块重投；新增 `--peer-mode`、`--peers`、`PEER*` 日志行、`peer_*` 计数与 health `peers` 段。入站闸门、出站形状、回执与读回核实不变
- 0.4.0（2026-09-24）：非文本段不再被 `no_text` 吃掉。图片/动态表情/语音/视频/文件/地点/卡片在正文按原位置留有界占位符，元数据走 `raw.asuna_media`；群里只带真实 reply 段或 at 本账号的消息也不再被当成空消息；新增 `--media-mode` / `adapter.media_mode`、`INBOUND_SPOOLED` 的 `media=`/`media_types=`/`media_only=`、`MEDIA_REPOST` 与 `inbound_media_only`/`media_field_denied` 计数。信封顶层字段一个没多、私聊不带群字段、唤醒判定不变（唤醒仍由宿主看真实 at / 回复链）；没有下载媒体、没有新增 action 或网络目标。另修一处只影响观测的读回判定：私聊读回不再把 `user_id`（实际是发送者＝自己）当对方 id 来比，改成「私聊 + 本账号发的」并标 `peer_bound=false`。
- 0.5.0（2026-10-04）：① 私聊出站图片（上一条边界条目）：`supports=image` 声明、宿主字节端点、`[image, text]`、失败即不发、回执带附件证据；② 群管理动作（mute/unmute/kick/recall → `set_group_ban`/`set_group_kick`/`delete_msg`，平台 retcode 即回执，日志 `ADMIN_CLAIMED`/`ADMIN_RESULT`）与自己在每个群的身份（`get_group_member_info` 查本号，随群事件走 `raw.asuna_self`）写进契约。（这一版已发布并激活。）
- 0.5.1（2026-10-04）：① 自检口径改成内置占位夹具（见「入口」）：去掉对本机私有群路由快照的硬依赖，DM 断言不再读 `cfg.allowed_private[0]`，现网配置交叉核对变成可选（没给就 SKIP），`--offline` 把 WS 与身份检查一起跳过，explicit 与 automatic 准入分开断言并修掉只在显式模式下才成立的过时 denied 期望；`adapter.py` 在默认路径没有配置文件时按夹具跑自检（命令行点名的配置读不出来仍报 `CONFIG_ERROR` 退出 2）。② 修 `peers.epoch()` 把 `iso()` 写下的 UTC 串当**本地时间**读回（`time.mktime`）：以东偏早 → 刚查过的人被读成 9 小时前、越过 TTL、改名不再要求跳缓存；以西偏晚 → 读成未来、身份缓存永远算新鲜；UTC 机器上完全看不出来。现在按 UTC 读回，并新增强制时区用例（`Etc/GMT-9` / `Etc/GMT+4` 两侧各钉住「固定瞬间原样读回」「10 秒前仍是 10 秒、10 天前仍是 10 天」「改名仍要求跳缓存」，跑完恢复原 TZ），换机器跑不再出现这边绿那边红。（已发布并重启：包 `asuna-napcat-qq-0.2.0-4530a244f2bb`，真机不带 `--offline` 的自检 297 过 0 红 0 跳。）

## 试用记录

- 22:47 首轮 selftest：25 pass / 2 fail（一条用例把丢弃顺序假设错了；一条是宿主 outbox 长轮询被数据库锁卡住）
- 23:01 selftest：27 pass / 0 fail；23:01:55 start 后 `IDENTITY match=true`、`READY ws_event=up ws_api=up`；随后 owner 从 900000010 的真实私聊往返已验收（平台回执 platform_accepted）
- 07:20 selftest（群支持 + 替身发送）：94 pass / 0 fail。覆盖预览配置解析、群越界（群号不在 allowlist、成员快照为空/非数字、target 类型错、同群重复绑定）、四群入站规范化（at 去重、`at,qq=all` 不进 ID、reply 段、文本不被污染）、跨群成员隔离、出站参数（`send_group_msg` + group_id、reply 段、allowlist 外不发、retcode≠0 → failed、超时/写失败 → unknown 且只调一次）、私聊原形状回归、锁与 spool key
- 07:42 `integration_stop`（返回 PROFILE_CHANGED…，已 STOPPED）→ `integration_start`：`CONFIG routes=group-900000003,group-900000001,group-900000002,group-900000004,owner-dm allowed_groups=四群 group_members=…`、`IDENTITY match=true user_id=900000000`、`READY pid=5 ws_event=up ws_api=up spool_inbound=0`、`STATUS group_routes=4`。旧数据目录里 0.1.0 留下的 `adapter.lock`（pid=5）被按陈旧锁接管，未删任何数据
- 07:43-07:47 真实群流量（不是合成）：群出站 5 条全部（截至 07:47:42） `SEND_RESULT target=group status=platform_accepted`，带真实 platform_message_id（910001 / 910002 / 910003 / 910004 / 910005），回执 `RECEIPT_OK http=200`；宿主没给 reply_to 的两条没带引用段，给了的两条带。群入站 6 条 `INBOUND_SPOOLED scene=group` 全部 `INBOUND_ACCEPTED`（900000002 一条 mentions=1 reply=1；900000003 三条，其中 mentions=0 的旁听消息照实提交、由宿主决定不唤醒）。owner 在 900000002 发的一条非文本被闸门丢弃：`INBOUND_IGNORED reason=no_text`。`spool_inbound` 始终 0，无 retry/unknown/failed。
- 仍未验证：群 900000001 与 900000004 尚无真实流量；真实流量里还没出现过 unknown/迟到回执路径（离线替身覆盖过）
- 07:52-07:58 收窄锁机制：删掉 LOCK_STALE_SECONDS、/proc 身份探测、touch_lock 心跳和过期接管，`acquire_lock` 只剩一次 `fcntl.flock(LOCK_EX|LOCK_NB)`（journal.py 从 8987 字节回到 5816）。`--selftest --offline`（新增：跳过会领取真实 outbox 的 live 段）85 pass / 0 fail，其中隔离锁检查 4 条：自己持有可写 pid、同进程第二个持有者被拒、另一个进程持有 flock 时被拒、持有者被 SIGKILL 后遗留文件不挡重启。`integration_stop`（SIGTERM，停止前 spool_inbound=0）后 `integration_start`：`READY pid=5 ws_event=up ws_api=up spool_inbound=0`、`STATUS group_routes=4`，上一轮留下的 adapter.lock 没有挡住启动。此前 07:42 那条记录里的“心跳/接管”描述属于已被替换的实现，只作历史保留
- 同期真实流量补充：群 900000002 继续多轮往返（`SEND_RESULT target=group status=platform_accepted`，如 910006 / 910007 / 910008 / 910009 / 910010 / 910011 / 910012），未授权的群（900000012、900000014）按 `INBOUND_IGNORED reason=group_not_allowed` 丢弃，纯表情按 `no_text` 丢弃
- 08:19-08:22 修群正文丢位置：`parse_message` 增加 `text_with_at`（真实 at 段按原位置渲染 `@账号` / `@全体`），群信封提交这个版本，`no_text` 闸门仍按纯 segment 文本判断；`mentioned_account_ids` 生成方式不变，私聊仍用不含 at 的正文。`--selftest --offline` 88 pass / 0 fail，其中 `group_at_position_preserved` 断言真实案例得到 `@900000000你刚刚回复 @900000101了么？`，`group_at_text_is_not_mention` 断言手打 `@全体成员` 不产生提及，`filter_private_text_unchanged_by_at` 断言私聊正文不含渲染文字，`group_bare_at_still_no_text` 断言单独 @ 仍丢弃。`integration_stop`（停止时 spool_inbound=0，无积压）→ `integration_start`：`READY pid=5 ws_event=up ws_api=up spool_inbound=0`、`CONFIG` 五路由四群、`IDENTITY match=true`、`STATUS group_routes=4`，随后已有真实群入站 `INBOUND_ACCEPTED`
- 仍未直接核实：真实群消息渲染后的正文本身（日志只带 `chars=`/`mentions=` 元数据，服务 `/data` 不在开发沙箱里）；要确认可在 Web 检查器看该条原文

- 08:44-08:47 部署 0.2.2 并等真实对话：`--selftest --offline` 99 pass / 0 fail，其中新增 12 条出站编码用例（提升、位置、多标记、纯标记、@昵称与@全体不提升、邮箱形状、超长数字、私聊不提升、段白名单、at 目标必须是数字）。`integration_stop`（停止时 spool_inbound=0）→ `integration_start`：`READY pid=5 ws_event=up ws_api=up spool_inbound=0`、`IDENTITY match=true`、`STATUS group_routes=4`。08:47:33 群 900000002 一条自然发言（来自宿主 outbox，chars=69，reply_to=None）：`SEND_RESULT target=group status=platform_accepted retcode=0 platform_message_id=910013 segments=at,text`，随后 `RECEIPT_OK http=200` —— 第一次有真实回执支撑“群出站确实带 at 段”这一层。仍未独立核实：平台是否把该段渲染成提醒（retcode=0 只说明接受了这个段序列，渲染要在群里眼看）；NapCat 不回推 API 发出的消息，`SELF_ECHO` 与 `inbound_self_echo` 至今 0 次。

- 09:39-09:45 部署 0.2.3（出站读回核实）。`--selftest --offline` 126 pass / 0 fail（原 99 条全保留，新增 27 条 `verify_*` 用例：verified / not_found / 一次重试上限 / 三种 API 异常都不改 platform_accepted 且不重发 / target_mismatch / segment_mismatch / 意外形状算 unavailable / 私聊按 user_id 绑 / 失败与 unknown 的发送根本不调 get_msg / `--no-verify` 不调 / 非数字 id 不调 / 迟到回执路径不变 / 被查的 id 恒等于自己那条 / 请求面 ⊆ {send_group_msg, get_msg}）。`integration_stop`（停止时 spool_inbound=0、spool_receipts=0）→ `integration_start`：`READY pid=5 ws_event=up ws_api=up spool_inbound=0`、`IDENTITY match=true`、`STATUS group_routes=4`。
- 同期把生产代码本身（不是替身）接到真实 NapCat 上跑了一遍 `verify_send`，只查我们自己发过的那几条：910013 → `verified`（存的就是 `at,text`，at 900000101 在）、910006 → `verified`（`reply,text`，reply 910014 在）、910001 → `verified`（`text`）；故意把路由写成 900000001 → `target_mismatch`；故意把提交段写成 `text` → `segment_mismatch`；不存在的 id → `not_found`，且 `api_calls_sent=7` 证明只重试一次。计数 `verify_verified=3 / verify_mismatch=2 / verify_not_found=1`。这一步没有发任何消息、没有读未授权群。
- `decode_log.py` 认得 `VERIFY` 了（合成日志实测：`读回核实（仅观测，不影响发送状态）: {'verified': 1, 'not_found': 1}`，非 verified 的行单独列出）。
- 本次窗口内还没出现的第一条真实 `VERIFY`：09:40 重启后授权群一直安静（只有 900000012 / 900000015 / 900000014 这些未授权群在刷 `group_not_allowed`），宿主没有出站，所以读回在真实发送上的第一次落地、以及“发送后 0.8 秒够不够平台索引”仍待下一条真实出站验证；不够的话 `--verify-delay` 可调，不影响发送状态。同样仍未在真实流量上验证的：at 非群成员时段序列会不会被平台降级存储、私聊出站的读回、Web 检查器是否展示 `response.verification`。

- 12:36-12:46 部署 0.3.0 身份层。先探清边界：`get_group_member_info` 可用（缓存 7-330ms、`no_cache` 420-540ms，返回 nickname/card/role/title/join_time）；`get_stranger_info` 可用但回一大坨个人资料（实测含住址、生日、兴趣、邮箱），所以只取 `user_id`/`nickname`。宿主信封逐个试了 13 个候选字段名（`sender_profile`/`peer`/`meta`/`context`/`display_name`…）全部 403 `CHANNEL_ENVELOPE_FIELD_DENIED`，而 `raw` 内部塞 `asuna_peer` 能过字段校验（返回的是 `INPUT_IDENTITY_OR_CONTENT_CONFLICT`）——身份块因此走 `raw`。探针全部复用已接受过的 event id，没有伪造入站、没有产生 episode。
- `--selftest --offline` 170 pass / 0 fail（原 126 条全保留，新增 41 条 `peer_*` + 3 条在线 `peer_live_*`）。首轮跑出 3 个真 bug：① 是否查平台是在合并 `sender` 块**之后**判断的，自己跟自己比永远一致，改名不会触发复核 → 改成先判断；② 场景记录没存昵称，没设群名片的人在该群 display 为空 → 补上；③ 一条用例期望写错（sender 块里 role 是 admin）。`integration_stop`（停止时 spool_inbound=0，此前群 900000001 已收 8 条全部 INBOUND_ACCEPTED）→ `integration_start --peer-mode full`：`IDENTITY match=true`、`PEERS {"people": 0}`、`READY ws_event=up ws_api=up spool_inbound=0`、`STATUS group_routes=4`。
- 12:45-12:47 真实入站上的第一批 `PEER` 行（群 900000004，不是合成）：三条已授权入站各自带出一条身份识别，全部 `source=api verified=True`，其中一条 `card` 与昵称不同、`display` 取的是群名片，一条没设群名片、`display` 回落到昵称（`display_source` 两种都出现过）；计数 `peer_api_calls=3 / peer_enriched=3 / inbound_accepted=3`，一人一次查询没有重复。**关键一条：三条都跟着 `INBOUND_ACCEPTED http=200`，没有 `PEER_FIELD_DENIED`/`PEER_REPOST`——带 `raw.asuna_peer` 的信封真实宿主照收。**`PEER` 行在 `INBOUND_ACCEPTED` 之前，因为身份是在提交前算好的。
- 仍未核实：`raw.asuna_peer` 会不会被宿主渲染进角色上下文、Web 检查器是否展示这一段（宿主侧，不在获准目录内，见开发目录 `PEER_IDENTITY.md`）；改名/换名片的 `PEER_CHANGED` 只在自检里验过，真实流量上还没等到（要等某个人真的改）。
- 13:15-13:30 P1-a 收尾（宿主接线）与 P1-b 起步。Codex 核对成立：`Router.receive` 的 trusted 白名单没有 `raw`、`ContextBuilder.prepare` 没投射 `raw.asuna_peer`，所以「adapter 读到了」还不等于「角色能答」。开发目录新增 `host_wiring/`：`peer_context.py`（`project_peer(raw)` → 一行「对方是谁」，没身份块返回 `None`）、`history_query.py`（P1-b 查询层：注入现有检索后端与来源回读，不碰平台，按人过滤认旧名字）、`test_host_wiring.py`（29 pass / 0 fail，其中 `keys_match_producer` 拿真 `PeerDirectory` 生成身份块再投射，adapter 改字段名而宿主没跟上会先红）。改动清单、需要的写入和验收问法见开发目录 `HOST_WIRING.md`。
- 真身份块过投射器的实际输出（群 900000004 那位管理员，不是手写样例）：`[对方身份] 示例群名片；本群群名片；QQ 昵称 示例昵称；本群身份 管理员；自 2026-09-23 认识（qq:900000105）`。第一版把显示名和群名片念了两遍、`曾用名` 又跟昵称重复，已去重。
- 仍未核实（不变）：宿主落盘前，角色不能据 `raw` 回答昵称/名片/身份；`PEER_CHANGED` 真实流量还没等到。宿主仓库在我两个沙箱里都没挂载，所以这两处只能形成文件，落盘与宿主重启在获准目录之外。
- 13:35-13:45 按 Codex 给的真实宿主接口把上一条那版草稿纠正了（草稿有两处不能直接落盘，别照它抄）：
  - 身份块路径是 `event['raw']['asuna_peer']`，落库后是 `message['event']['raw']['asuna_peer']`，**不是** `message['raw']`；投射器入口相应改成 `peer_from_event/peer_from_message/project_event/project_message/apply_peer_context`，`project_peer` 收的是身份块本身。
  - `ContextBuilder.prepare` 里没有 `current_input`/`context_lines`，真实形态是 `source = store.db.messages.find_one(...)` + `context` 字典，所以接线是一行 `apply_peer_context(context, source)`（写 `context["sender_identity"]`）。
  - `Retrieval.search(scope, epoch, query, *, exclude_sources=(), require_vector=False)` 只挑 memory_units 候选、不覆盖完整 messages，所以 P1-b 的主干是字面那一趟 `store.db.messages.find`（覆盖完整 messages、原文整条不截、keyset 续页），语义候选只是附加；空 `scope` 直接拒查不退化成无范围扫描。
  - 离线自检 45 pass / 0 fail（假对象按宿主真实签名做，`FakeMessages` 真实现 `$in/$gte/$lte/$lt/$regex/$and/$or` 与多键排序）。测试抓到我自己写的 4 个问题：`dict(("\$gte", v))` 会抛 ValueError、按人过滤留了 `if False else` 残骸、`query_history` 没转发 `author`、归属行把显示名念两遍。
  - **P1-b 仍未就绪**：要落盘 + 5 处字段名确认（正文字段名、候选指回源消息的字段名、`Retrieval.search` 返回形态、`context` 渲染点、`epoch` 来源）。准确落点与缺口见开发目录 `HOST_WIRING.md`。adapter 侧不用改：它注入的位置就是 `event['raw']['asuna_peer']`。
- 14:05-14:20 按 Codex 核实的字段名把两处接线改成真契约（细节在开发目录 `HOST_WIRING.md`）：正文 `text`、纪元 `policy_epoch`；`Retrieval.search(scope_key字符串, policy_epoch整数, query, *, exclude_sources, require_vector)` → `(selected, manifest)`，源消息 ID 在 memory unit 的 `source_event_ids`；字面查询只纳入当前场景的 inbound 与已确认发布的 SPEAK outbound，默认近 7 天 / 每页 50 / 最多 200 / 大小写敏感，原文逐字回读保留用户空白。身份块进角色前加了一道 `verify_peer`：`person_id` 必须等于 `"qq:"+认证 sender`，群场景还要 `scene`/`group_id` 跟路由一致——**raw 里自称的身份单独不算数**（通道是可信源但不是免检源）。离线自检 55 pass / 0 fail；测试抓到 `query_history` 把已解析的 parts 当原始 scene 传下去，`policy_epoch` 丢在中间会让字面查询静默空结果。仍未落盘，所以角色还是答不出昵称/名片/身份；唯一没核实的名字是「已确认发布」在 messages 里怎么标（四个常量集中在模块顶部，改一行）。
- 14:40-15:00 Codex 第四轮静态审阅又挑出三处真契约错，已改（细节见开发目录 `HOST_WIRING.md`）：① 出站判定不是 `kind`/`publication`，而是 `phase='SPEAK'` + `delivery_state='DELIVERED'`（`coordinator` 先写 `READY`，平台回执后 `channels` 改 `DELIVERED`）——用错字段会静默漏查所有自己说过的话；② 真实 `scene_id` 是 `qq:<bot>:group:<群号>`，群号得解析出来，不能按 `group:<群号>` 前缀取；③ `ingress` 写的 `author` 已带 `qq:` 前缀，校验时再拼一次就变 `qq:qq:...`，把合法历史行全判成不匹配——现在两边都过 `_norm_person()` 归一。身份校验源改成已认证 `event['channel']['sender_id']` / `['target']`（落库后 `message['event']['channel']`），不再从 raw 自称推导；adapter 的 `scene` 叫 `group:<群号>` 而宿主 `target` 叫 `qq:<bot>:group:<群号>`，所以群号是两边各自解析后再比，直接比字符串会错杀。另外发现宿主时间字段名不能假定是 `occurred_at`（出站写入就没有它），改成 `probe_time_field()` 从真文档探、探不到就拒查而不是猜一个。离线自检 65 pass / 0 fail；仍未落盘，角色还是答不出昵称/名片/身份。教训：**观测字段名要拿真实写入链核对，不能按语义猜**——猜错的字段不会报错，只会静默少查。
- 15:20-15:45 第五轮契约纠错（细节见开发目录 `HOST_WIRING.md`）：① **时间不是一个字段**——入站行是 `occurred_at`（ingress），已送达出站是 `receipt_at`（channels 回执），coordinator 刚写出时两个都没有。之前那个 `probe_time_field()` 从一条入站样本选中 `occurred_at`，会把整批 `DELIVERED` 出站静默漏掉；现在改成两支各带自己的时间条件 + 按各自时间戳归并排序 + 两支各一份 keyset 游标（一次调用两次查询）。② `event['channel']['target']` 是 `route['target']` **字典** `{'type':'group','id':'<群号>'}`，不是 `qq:<bot>:group:<群号>` 字符串；把字典丢给字符串解析会得到空群号，**合法群资料反被拒**（错杀比误信更难发现）。现在用 `_target_group()` 按字典取，`type != 'group'` 就当没群。③ `direction` 字段名已确认（ingress/coordinator 都写）。离线自检 70 pass / 0 fail：入站行只带 `occurred_at`、已送达出站只带 `receipt_at` 的真实形状下，`delivered_outbound_not_dropped` 与跨支归并顺序都绿；target 字典校验合法样本 6/6 通过、不该过的 0/6 误过。仍未落盘启用。教训补一条：**校验错杀比误信更难发现**——误信会在回答里露出怪名字，错杀只是“什么都没查到”。
- 16:05-16:35 P1-b 隔离复核纠错（细节见开发目录 `HOST_WIRING.md`）。三处真 bug：① 两支查询都无条件带 `{"occurred_at": {}}`，而**空字典在 Mongo 里是等值条件**，只匹字段真等于 `{}` 的文档 → `window=None` 直接 0 条；现在没窗口就不加时间键。② **人物过滤在分页后**，`person=…, limit=1` 首页被无关行占满（0 命中却 more=True）；现在 `person_clause()` 下沉进两支查询，认 `author` 也认 `event.raw.asuna_peer.{person_id,card,nickname,display,aliases}` 点号键，分页后那层只当安全网。③ 身份块不可信时只说“不引用名字”不够——Web 那次就把我自己 81/83 当成用户原话；现在每条固定带 `at`/`time_field`/`speaker`(=author)/`side`(对方说｜我说)，校验不过就退回已认证 author 报“记录作者 qq:…”。假对象补了 Mongo 语义（空字典等值、点号键、数组等值）并抽成 `fakes.py`，81 pass / 0 fail；`demo_web_case.py` 按那次提问形状跑出带时间、分得清“我说/对方说”、能续页的结果。另记两条环境事实：宿主 18766 **只有入站**（GET /messages、/history 等全 400），也没有 Mongo 转发 → “用真库跑 query_history”这步在集成沙箱里做不了，只能宿主侧执行；config 里 routes 的 `target` 确实是 `{"type":"group","id":"…"}` 字典。教训：**假对象的条件语义必须跟真库一致**，否则假对象会把真 bug 掩盖成“全绿”。
- 16:40-17:05 导入依赖专项（P1-b）。勘误收下：上次验的是**同目录两份新文件互导**，而宿主 `src/asuna/peer_context.py` 是旧版（没有 `_group_token`），`src.asuna.history_query` 一加载就 ImportError，整个查询模块带崩。消除：① 纯字符串解析（群号、person_id）在 `history_query.py` 自带本地实现，零依赖，用交叉比对测试防与 `peer_context` 同名函数漂移；② 身份块三函数（`peer_from_message`/`verify_peer`/`channel_of`）改成**接口约定 + 惰性容错获取**：`IDENTITY_CONTRACT` 写签名、`use_peer_context_identity()` 缺哪个记哪个绝不抛、`configure_identity(**fns)` 允许宿主注入任何实现、`identity_status()` 把降级摊开（结果带 `identity`，render 头部提示）；③ 取不到解析器就退回记录 `author` 报“记录作者 qq:…”，不崩不猜。subprocess 起干净解释器实测三种组合：只有 history_query → 可用但降级；**当前宿主形状**（有身份三函数、无 `_group_token`）→ 包导入成功、查询可用、群号走本地实现；新版 peer_context 同目录 → 完整身份行。结论：`history_query.py` 可单独落盘，身份行要等 peer_context 一起更新。peer_context 晚于 history_query 导入也能在第一次使用时采纳；93 pass / 0 fail。教训：**验证组合必须等于真实运行组合**——“我这边两份新文件互相导得通”不等于“放进宿主那个已有旧文件的包里也导得通”。

- 23:08 / 23:50 真实证据（触发点）：owner 在私聊发的两张图被 0.3.0 丢掉——`INBOUND_IGNORED reason=no_text message_type=private user_id=900000010 message_id=910015`（23:08:22）与 `910016`（23:50:52），计数 `inbound_no_text` 从 0 涨到 2。拦截点在 `inbound.py` 的 `if not text.strip(): return None, "no_text"`：非文本段只进 `other_segments` 计数，不进正文。
- 23:20-23:35 取证（不新增权限）：真库两条已接受事件的 `event.raw` 里完整保存 OneBot 事件并合并了 `asuna_peer`（in-ep-57a84e2f… / in-ep-443810f7…）→ 往 `raw` 里加块能落库；宿主 `channels.py` 要求 `text` 1–16000 且信封是严格白名单（私聊带群字段就 `DM_GROUP_FIELDS_DENIED`）→ 纯媒体事件必须带非空文本表示，媒体信息只能走 `raw`；宿主 `context.prepare` 只投射 `event.text` 与历史正文、不投射 `raw` → 占位符是当下唯一「能被看见」的路径。唤醒口径也查实属宿主：真库里已有 `wake_reason=reply_to_character` 且 `mentioned_account_ids=[]` 的行，所以非 @ 的**有文字**回复本来就可见，缺口只是无文字的那批。
- 23:36-23:54 实现 0.4.0：`inbound.py` 重写（`text_with_media` / `media` / `media_extra` / `media_block` / `strip_media`，无媒体消息与 0.3.0 逐字相同）、`config.py` 加 `adapter.media_mode`、`service.py` 加 `media=` 日志字段与去块重投、`adapter.py` 加 `--media-mode`。`--selftest --offline` 213 pass / 0 fail（原 170 条全保留，新增 43 条 `media_*` + 群夹具改造）。首轮 6 fail 全是夹具/期望问题：① `GROUP_ROUTES_PREVIEW.json` 是 09-23 的四群快照，而 live config 今天已有五群 → 合并逻辑改成「live 优先、预览补缺」并从生效配置取场景；② 未知段类型把 `None` 念成 `none`；③ DM 读回夹具没区分 sender 与 user_id。
- 23:41-23:47 一次性探针 `probe_media.py`（开发目录，只读 + 一条迟到投递）：`get_msg 910015` 回的真实段是 `{"type":"image","data":{"summary":"[动画表情]","sub_type":1,"file_size":"46695","url":"https://multimedia.nt.qq.com.cn/download?...&rkey=CAIS…"}}`——是动态表情不是照片，所以占位符改用平台自带的 `summary` 命名；`media_mode=off` 在真事件上复现 `no_text`，`full` 得到正文 `[图片（未解析）]` + `raw.asuna_media`。把这条真实消息（迟到 33 分钟）投给宿主：`HOST_POST kind=accepted code=200 episode_id=ep-435b26313c18e27b84c855c89e7ada05`，**没有 `MEDIA_REPOST`／403 → 宿主收 `raw.asuna_media` 已被真实往返证实**；随后在跑的 0.3.0 服务把角色的回复发出去了（`SEND_RESULT target=dm status=platform_accepted platform_message_id=910017 reply_to=910015`）。探针只调了一次 `get_msg`（读 owner 自己指给我们的那条），不是服务的新权限面。
- 顺带修一处只影响观测的判定：上面那条真实私聊出站的 `VERIFY` 报 `result=target_mismatch detail=private/900000000`——`get_msg` 对私聊消息回的 `user_id` 是**发送者**（读回自己那条时就是我们自己），拿它比对方 id 永远不等；改成「私聊 + 本账号发的」并标 `peer_bound=false`。这是第一次有真实 DM 读回，0.2.3 当时只在替身上验过，真实形状一上线就推翻了对字段语义的猜测（同一条教训：字段语义要拿真实回包核，不能按名字猜）。
- 23:54 `integration_stop`（停止时 `spool_inbound=0 spool_receipts=0`）→ `integration_start python3 /app/adapter.py --service`（0.4.0 冻结副本）。
- 00:04:10 **第一条真实图片入站在 0.4.0 上落地**（群 900000004，成员 qq:900000104，不是手工投的）：`INBOUND_SPOOLED event_id=910018 scene=group group=900000004 chars=14 media=1 media_types=image media_only=True` → `PEER ... source=api verified=True` → `INBOUND_ACCEPTED episode=ep-f8e6c110be0d89b22cb4f3b6addcb4d2 http=200`，**没有 `MEDIA_REPOST`**，计数 `inbound_media_only=1`。同一条在 0.3.0 下会是 `INBOUND_IGNORED reason=no_text`。正文 14 字 = `[图片:动画表情（未解析）]`，说明平台 `summary` 命名在真实流量里也用上了。
- 00:05-00:08 补一道长度护栏 `fit_host_limit`：占位符不能把一条 0.3.0 本来能提交的长消息推过宿主 16000 上限——超了就退回不含占位符的正文（0.3.0 形状）并标 `media_shrunk_for_limit`，`raw.asuna_media` 照旧带元数据；本来就超限的消息保持原样、仍只标 `over_host_limit`。`--selftest --offline` 216 pass / 0 fail（新增 3 条上限用例：私聊、群、本来就超限）。重启后 `CONFIG ... media_mode=full`、`IDENTITY match=true`、`READY ws_event=up ws_api=up spool_inbound=0`。
- 仍未核实：宿主 Web 检查器是否展示 `raw.asuna_media`；表情刷屏时 spool 与宿主行数的压力（退路是 `--media-mode annotate` 或 `off`，不用改代码）；超长消息（正文本身已近 16000）的截断策略还没定——护栏只保证不会因占位符多几个字而被拒（`media_shrunk_for_limit`），真要截断得先定截在哪、留不留尾部；私聊方向的第一条真实图片入站还没等到（重启后私聊安静），但群方向已经来了，见下条。

### 2026-10-04 自检改造：群覆盖搬到内置占位夹具（只改候选，未发布、未重启适配器、未发 QQ）

- 改前的真实基线（就在这个候选沙箱里，没有那份私有路由快照）：`--selftest --offline` **144 pass / 9 fail**。5 条红在「读不到 `GROUP_ROUTES_PREVIEW.json` → 群策略、群入站、出站参数、读回核实整段没跑」（`preview_readable` / `cfg_group_policy_cases` / `group_inbound_ran` / `outbound_params_ran` / `outbound_verify_ran`），4 条红在 `--offline` 仍去连这台机器上并不存在的 WS 与身份接口。也就是说「离线全过」以前是**只在有那份私有文件的那台机器上**才成立。
- 新增 `qqadapter/fixtures.py`（占位号：本号 `900000000`、四群 `900000001-900000004`、私聊对象 `900000010`、成员 `9000001xx` 且故意跨群重叠、名单外 `900000012`/`900000013`/`900000199`、可黑名单的 `900000101`/`900000004`），`selftest.py` 的行为断言全部改跑它；`adapter.py` 在默认路径没有配置文件时退回夹具并明说（`CONFIG_FALLBACK`），命令行点名的配置读不出来仍然 `CONFIG_ERROR` + 退出 2。
- 改后实测：干净候选无配置文件 `--selftest --offline` **269 pass / 0 fail / 3 skip**（exit 0）；`--config <现网形状的配置> --offline` **278 pass / 0 fail / 2 skip**（多出的 9 条是 `live_config_*` 交叉核对）；显式点名的坏配置 → `CONFIG_ERROR adapter section missing`、exit 2；同一个配置**不加** `--offline` 在这个没平台的沙箱里如实报 6 条 live FAIL（4 条 WS/身份 + 2 条宿主 HTTP），证明 live 段没被顺手关掉。
- 新增 `admission_*` 23 条（显式 5 + 自动 6 + 两种模式各 3 条黑名单 + 出站 5 + 收尾 1）与 `fixture_*` 7 条（夹具形状、占位号、成员快照、不再依赖本机路由快照）。首轮 5 条 FAIL 全是我自己新代码的夹具/期望问题：① 黑名单 DM 用例挡的是没被绑的那个人；② 出站黑名单用例拿的是没开黑名单的配置；③ 跨场景去重用的人不在第二个群的成员快照里；④ spool 名字用例同一个原因；⑤ 一处契约澄清——被黑名单的群**在 allowlist 上**时入站理由是 `group_route_missing` 而不是 `group_not_allowed`（黑名单是让路由不存在，不是把群从名单上摘掉）。
- 仍未核实：群管理动作（mute/unmute/kick/recall → `set_group_ban`/`set_group_kick`/`delete_msg`）在自检里**一条用例都没有**，只有代码路径与日志形状；`base64://` 图片在真实客户端是否渲染、`supports=image` 在真实宿主上的行为、附件失败时宿主侧的正文保留，都还没在真实流量上验过；本次没有发布、没有重启适配器。线上跑的**已经是 0.5.0 的适配器代码**：ACTIVE 快照 `asuna-napcat-qq-0.2.0-16317c9e73ec`（2026-10-04T15:25Z 发布、15:31Z 激活，发布改动含 `qqadapter/__init__.py`，包名里的 `0.2.0` 是 package.json 的版本，适配器自报 `__version__` 是 0.5.0），管理进程自 21:09:23Z 起 RUNNING。所以这次改的是候选，不动线上行为；写结论前查实际状态，别照抄上一轮的判断。

### 2026-10-04 补修：`peers.epoch()` 按本地时区读 UTC 时间戳（同一候选，未发布）

- 症状：在非 UTC 的机器上 `peer_rename_forces_fresh_lookup` 红，`no_cache` 是 `false`；UTC 沙箱里跑不出来。根因是 `peers.py` 的 `epoch()` 用 `time.mktime(time.strptime(...))` 把 `iso()` 写下的 UTC 串当**本地时间**读回来：本号以东偏早（一条几十秒前的查询被读成 9 小时前 → 越过 6 小时 TTL → 改名不再要求跳缓存，`no_cache=false`），以西偏晚（读成未来 → 永远算新鲜）。改成 `datetime.strptime(...).replace(tzinfo=timezone.utc).timestamp()`。全仓其余写 UTC 串的地方（`journal`、`outbound._now`、`service._now`、`inbound`）本来就用 `gmtime()`/显式 `timezone.utc`，只有这条读路径漏了。
- 自检不再靠机器的脸色：新增 `_check_peer_timekeeping()`，用 `time.tzset()` 把进程强制到 `Etc/GMT-9`（UTC+9）与 `Etc/GMT+4`（UTC-4）两侧，各跑「固定瞬间的 ISO 串必须原样读回同一个瞬间」「10 秒前的查询读起来仍是 10 秒、10 天前的仍是 10 天」「改名必须仍然要求跳缓存（端到端，用替身身份接口）」，跑完恢复原 TZ 并断言恢复成功；时区装不上就 SKIP 并说明，不静默放过。
- 实测（同一候选）：修好后 `--selftest --offline` 在 `TZ=UTC` / `TZ=Etc/GMT-9` / `TZ=Etc/GMT+4` 下都是 **279 pass / 0 fail / 3 skip**；把 `epoch()` 换回旧写法做反证，`TZ=UTC` 也有 **5 条红**（含 `peer_rename_forces_lookup_east9`：`no_cache=false`），`TZ=Etc/GMT-9` **7 条红**（连原来那条 `peer_rename_forces_fresh_lookup` 一起红，正是非 UTC 机器上看到的现象），`TZ=Etc/GMT+4` **6 条红**。也就是说以后不管跑在哪个时区，这条 bug 都藏不住。
- 顺手把技能里剩下的旧六位号（`101354`/`101748`/`301623`/`301718`/`300003`/`301996`/`101030`/`100813`/`101494`/`700002-700004`）统一换成 `9000000xx` 占位号，并在「配置形状」开头声明这些是占位号、试用记录里的六位 `91xxxx` 是平台消息 ID；注释里不再把「真实案例」和号码并排写。本机那份 `GROUP_ROUTES_PREVIEW.json` 保留未动（主人的本地数据）。
- 复跑结果：在非 UTC 的机器上用干净副本跑两次 `--selftest --offline`，都是 279 过 0 红 3 跳 —— 时区那条修对了。因为 `peers.py` 的行为变了，适配器版本提到 **0.5.1**（`qqadapter/__init__.py` 的 `__version__`；包名里的 `0.2.0` 仍是 package.json 的版本，两者不是一回事）。个人数据扫描：占位号段已扩到整段 `900000xxx`，剩下两行（夹具的宿主令牌、自检里那个固定时刻）加了 `personal-scan: ok` 标记并写明是占位令牌 / 固定时刻，不是号码。

### 2026-10-04 发布 0.5.1、重启适配器、真机不带 `--offline` 自检

- 发布：候选 `d2531906…` → 包 `asuna-napcat-qq-0.2.0-4530a244f2bb.tgz`（sha `4530a244…`），启动探针 exit 0，21:48:52Z；改动 8 个文件（`adapter.py`、`qqadapter/{fixtures,peers,selftest,__init__}.py`、`RUNTIME_API.md`、`SKILL.md`、`USAGE.md`），没有删除任何文件。包名里的 `0.2.0` 还是 package.json 的版本，适配器自报 `adapter 0.5.1`。<!-- personal-scan: ok (truncated candidate hash) -->
- 重启：`integration_stop`（旧进程自 21:09:23Z 跑了约 40 分钟，SIGTERM，exit −15）→ `integration_start ["python3","/app/adapter.py","--service"]` 冻结新快照。新进程 21:49:08Z 起来：`WS_UP /event` + `/api` → `CONFIG … shared_account=True … media_mode=full`（5 个授权群 + `owner-dm`）→ `IDENTITY {"match": true, "ok": true, "app_version": "4.18.0"}` → `PEERS {"people": 245, "scenes": 288}` → `READY pid=6 identity=… ws_event=up ws_api=up spool_inbound=0 spool_receipts=0`。停机窗口不到一分钟（旧进程最后一条日志 21:48:26，新进程 21:49:08 接上 WS）：这几秒里平台推过来的事件没有适配器接着，NapCat 不补投，那几条就过去了 —— 重启要挑群里安静的时候。
- 真机不带 `--offline` 的自检（只读，一条消息都没发）：**297 pass / 0 fail / 0 skip**，exit 0。阶梯对得上：279（无配置文件，3 跳）→ 288（给现网配置，2 跳）→ 297（真机，0 跳），多出来的正好是 9 条 `live_config_*` 加 9 条平台/宿主检查，说明「离线不碰平台」这条口径是真的。
- 现网配置交叉核对 9 条全过：现网 `adapter.admission` 是 **automatic**（不是显式），5 个群的成员快照都在，群/私聊没有越界，`describe()` 不吐令牌。真身份查询走的是生产代码不是替身：群里那位 `role=owner`、私聊那位 `relation=friend`，`peer_live_no_stranger_blob` 说明落盘里没有 `address` 这类原始 blob。`host_reachable_auth_enforced` 拿到真实 403；`host_outbox_empty` —— 队列当时是空的，自检没领走任何待发项，所以确实一条消息都没发。
- 仍未核实：群管理动作（mute/unmute/kick/recall）在自检里仍然一条用例都没有；`base64://` 图片在真实客户端是否渲染、`supports=image` 在真实宿主上的往返、附件失败时宿主侧正文保留。


### 2026-10-05 文档对齐：`integration_dev` 退役、发布/启动口径（只改技能文档与 `integration/RUNTIME_API.md`，未发布、未重启适配器、未发 QQ）

- `integration_dev` 不再是任何工具：探测与一次性脚本现在的做法是写进本候选 `integration/`，用 `integration_test ["python3","/app/<脚本名>.py"]` 试跑。实测（探针跑完即删）：`CWD /app`、`/app/adapter.py` 在、往 `/app` 写报 `OSError` 只读文件系统、`/integration/config.json` 可读、`ENDPOINT_KEYS ['host', 'image', 'napcat']`。
- 「代码在哪」「重新部署」与 USAGE.md 的启动/常见情况改成：改动只经 `development_publish` 生效；`integration_start` 只运行已发布版本，不运行未发布候选；宿主重启恢复当时已发布版本。试用记录里历史提到的「开发目录」按当时的叫法读，就是今天通道包候选的 `integration/`，不回头改写。
- `integration/RUNTIME_API.md` 与认知核根目录 `RUNTIME_API.md` 当时逐字节一致（两份各自 `sha256sum` 同前缀 `4fcca79c`，完整哈希见行动报告）；认知核文件本身没动。<!-- personal-scan: ok (哈希前缀，不是号码) -->
- 发布前再对齐：认知核根目录 `RUNTIME_API.md` 的发图一节已改成 `attach_image` 口径（DECIDE 时代的旧句去掉），通道包副本随之重抄，两份 `sha256sum` 现同前缀 `84b2a65c`（完整哈希见行动报告）。<!-- personal-scan: ok (哈希前缀，不是号码) -->
- 占位号口径不变：本文出现的账号/群号仍是 `900000xxx` 夹具占位号；本轮没有新增真实号、地址或端口。
