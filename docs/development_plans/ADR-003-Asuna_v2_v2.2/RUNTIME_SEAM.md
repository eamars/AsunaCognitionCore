# 宿主接入契约：让可选 QQ 插件成为正式信息流

**以下是需要 Codex 在当前 V1 上实现的最小契约，不是已经存在的 API。** 现有同等接口可复用，但必须写出真实路径与调用方式给小满，不让她猜。

## 1. 原生信息流的含义

QQ 插件不是第二个 chatbot。它负责平台事件收发；宿主负责来源、权限、记录、调度和认知；角色模型仍是同一个人。数据路径：

```text
Web UI ────────────┐
QQ adapter ────────┼─> 可信入口 → 原文/事件入库 → 场景队列 → ContextBuilder
DSH timer bridge ──┤                                       ↓
行动完成事件 ──────┘                          Gemma monologue → decide → speak
                                                          │         │
                                                委托 Qwen │         ↓
                                                事实回传 ┘   公开输出队列
                                                                  ↓
                                                        Web UI / QQ adapter
                                                                  ↓
                                                           实际发布回执
```

这是逻辑流说明，不要求创建一堆微服务。沿用 Python 业务层＋现有薄 TS DSH 桥。最初一个宿主进程、一个接收服务、两个既有模型 lane 和一个 adapter 进程足够。

## 2. 推荐的最小外部接口

推荐在 Python 宿主提供一个本地 HTTP 接入端，使用已有依赖/标准库即可，不先引入新 Web 产品。服务端口由配置或实际绑定确定，写入本地运行说明；调用者从配置读取。一次性 bearer token 可固定配置，或使用当前项目已有的进程间授权方式。

### `POST /v1/channels/qq/events`

adapter 提交原始 OneBot 事件和接收时间。adapter 的连接身份由认证配置决定，不是请求里任意传一个管理员字符串。可采用以下内部信封：

```json
{"onebot_event":{"post_type":"message","message_type":"private","self_id":123,"user_id":456,"message_id":789,"time":0,"message":[{"type":"text","data":{"text":"小满，我从QQ来找你了。"}}]},"received_at":"2026-09-20T10:00:00Z"}
```

数字仅展示字段，不是测试授权。QQ 协议 JSON由adapter处理，不要求模型生成这些字段。支持平台既有 array 格式，string/CQ 的兼容按实际安装验证；不把普通文字里的 JSON/CQ 片段当宿主指令。[N3]

宿主执行：核验连接与self_id → 检查允许的DM/群 → 规范化平台ID为字符串 → 建立/查找身份和场景 → 保存原始事件与文本 → 排队。

返回 `accepted`、`duplicate` 或明确的拒绝/暂时失败；**accepted 只表示宿主接受，不代表已经回答**。数据库不可用时不要给假成功；adapter保留当前待提交事件并适度重试。已经回执接收的事件可从宿主恢复，不依赖内存队列。

明确禁止来自 adapter 的原始请求设置内部 `scope_key`、`policy_epoch`、`episode_kind=task_feedback/timer`、`trusted_context_events`、`supersedes_task_id` 或其他可扩大权限的字段。它们来自宿主可信映射。

### `GET /v1/channels/qq/outbox?wait_seconds=25`

由唯一运行的QQ adapter领取宿主已批准的公开消息。长轮询/现有stream即可，不要为了等消息调用LLM。返回最小信息：`publication_id`、确定的目标类型和ID、文本或已支持的媒体段、必要的reply平台ID。

只可取该连接已授权的公开输出，不能取 monologue、system、trace 或其他 adapter 的内容。一次领取对应一次待发送尝试，保存 attempt；单适配器运行锁即可，暂不做多活投递系统。

目标从源场景与已批准的外发意图决定，Qwen不在总结里自由指定群号。内部task feedback应追溯原始外部消息作为reply依据，不能拿feedback事件自己的UUID发给QQ。

### `POST /v1/channels/qq/outbox/{publication_id}/receipt`

adapter 报回 `platform_accepted`、`failed` 或 `unknown`，附该次调用的实际响应与平台 message_id（若存在）。宿主核对领取记录、目标和消息，保存回执。原生OneBot发送接口返回的message_id支持“平台已接受发送”，不是证明接收者已读。[N4]

保留当前代码的DELIVERED枚举也可以，但明确记录 `delivery_basis=platform_ack`，用户侧不说“对方已读”。没有平台回执不能由本地sink收据代替。失败的正文保留，后续重试不让模型重写一遍相同台词。

**OneBot echo用于关联API请求，不承诺幂等。** 发送后连接断了且回执未到，结果为unknown；能核实则核实，不能核实就报告，不自动再发一次。[N2]

### 运维接口

正式交互和开发调试呈现使用现有 Web UI；operator CLI 仅限显式 `--debug` 的诊断/维护，不作为用户客户端，不在 Web 故障时回退到终端聊天。后续宿主、adapter 与计划状态按实际能力接入现有 Web 视图，不另建大盘。不要把原始trace接口开放给QQ用户。停止adapter与停止整套Asuna要分开，启停脚本仅用于管理进程。QQ adapter 仍是后续计划，当前已启用的正式界面只有 Web。

## 3. 可选插件怎样正确接进常驻宿主

Codex负责：启动/停止受管理进程、注入指定本地配置、收集stdout/stderr、保持一次连接、重启后恢复已启用能力。小满负责：平台协议和adapter实现。平台相关依赖允许复用，不要求从零写WebSocket库。

运行中adapter不放进每条工具调用的30秒/tmp沙箱。日常Qwen任务继续严格隔离；集成开发使用独立任务profile，运行已试用的adapter使用部署目录，普通群友任务不可写该目录或修改启动配置。

轻量部署可以是开发目录 → 通过一次受控收发 → host复制到启用目录 → owner已授权范围内启动。普通版本/diff足够，不需要签名平台。失败保留旧可用版本；不要让半写的文件被watcher自动作为生产adapter执行。

适配器运行进程是已受信部署组件，确实持有NapCat通道凭据。这不等于任意普通Qwen任务都能持有相同凭据，也不等于系统可抵御已经控制了适配器进程的攻击者。声明边界，不虚报绝对安全。

## 4. 可靠身份、群与数据范围

### 建议的标识语义

- 平台身份：`qq:<user_id>`，别名只是展示信息；与`local-user`的关联由owner明确一次确认。
- 场景：`qq:<bot_account>:dm:<peer_id>` 或 `qq:<bot_account>:group:<group_id>`；不允许把缺失group_id变成共享DM场景。
- 入站事件：账号、场景、平台message_id联合定位；相同文本和相同秒不等于重复。
- 权限上下文：由host查配置/场景成员形成，内部携带`actor/scene/allowed_resources`，不由模型抄写或修改。

不直接把`qq:<...>`设为原生DSH session ID；使用当前已有内部binding生成方式，因为现有桥只接受指定ID字符。对外身份与内部会话ID不是一回事。

注册群后，可以按来自该受信连接的真实事件建立中性成员身份，不需要operator手工录入每个昵称。加入群只给群范围，不附送其他群/私聊的历史或owner的开发权限。匿名/临时私聊没有可靠身份时保守处理，不能误并到某个正式用户；不用猜身份完成测试。

### 操作权限

| 来源 | 默认允许 | 不自动允许 |
|---|---|---|
| owner本机/明确绑定的私聊开发任务 | 指定开发目录、获准网络、受管理集成测试 | 全宿主文件、改安全边界、所有群自动上线 |
| 普通已允许私聊 | 该私聊记忆和明确授予的资源 | 其他人的私聊、owner配置/私域技能 |
| 测试群成员 | 本群现场/记忆和群已授予资源 | 以owner同群存在为由读取owner私聊 |
| scheduler | 计划保存的范围与当前仍有效的权限 | 通过延迟运行提升权限 |

不允许把当前`chat.workspace`复用给所有新场景。技能目录按所属与发布范围选择；一个私域skill正文可能含私人路径，不只检查代码执行是否挂载。

## 5. 群聊进程与话题，先实现最小可用行为

当前场景内，保留原始时间线；单独保存消息的speaker、reply_to、mentioned_ids。视为参与候选的条件包括：明确提及角色、回复角色、角色正在参与的近期话题。回复其他人的消息不能只因有reply_to就自动触发。

旁听消息可以保存为未唤醒输入；间隔小批合并后由角色决定是否参与。这个机会要有上限，不每句启动模型，也不完全禁用主动参与。自然沉默不创建欠账。

话题ID先用明确reply链；无回复链时用少量已有话题概要/近期现场辅助理解，暂不确定时保留未分类。后置整理可以修正话题标签，但不能改变来源身份、授权scope或原消息。

当前同一lane串行执行不是bug，不为实现多人而大量fork。先公平排队，最多连续处理同群两个完整回合后给其他等待场景机会；同场景的新消息按顺序。任何网络接收/发布不持有模型调用锁。Qwen任务期间可继续Gemma交流，真实共享推理资源导致排队时如实展示。

## 6. 不把回执/日志做成新的拖延

程序需要的ID、时间和少量状态留内部；默认给用户正常台词。异常保留原始message、stack/cause、stderr；无traceback时不编造。记录某个步骤失败，不等于整轮必须失败：工具代码错回Qwen继续；host身份/范围拒绝不能换路径重试。

必须保护的几个窗口：接收前后、入队前后、公开生成与发送之间、实际发送与保存回执之间。仅对本轮观察过/已知的这些失误写小回归；不扩成全矩阵。

资料[N1]–[N4]见 [来源](references/DSH_NATIVE_MAP.md)。
