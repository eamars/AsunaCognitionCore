# DSH／NapCat 原生机制映射与外部资料

公开资料核对日期：2026-09-20。DSH参考版本固定到当前项目Python SDK依赖的提交 `fb2c4b9e698e30edb738bca4cf0618587db7d203`；实际可执行报告为`0.1.5-rc.2`。本机checkout若含本地修订，以真实调用结果记录差异，不擅自升级。以下是官方资料，不证明本机服务已启用某功能。

## 谁已有、谁需要补

| 机制 | 最新V1与本轮选择 |
|---|---|
| Profile / preset | V1已用sdk-minimal＋两个lane的配置补丁。保留实际工作组合；角色与执行职责不同，不为每轮／每个话题切preset。无需为了名字漂亮先合并进程或新建一堆profile。 |
| PromptSection | V1桥已有完整的角色／执行system贡献，直接复用。 |
| PromptContext | 新状态和能力说明可在需要时使用；同步provider读取已准备的场景快照。当前有全量suppressRuntimeContext，需只在触及相关注入时调整，不先迁移所有ContextBuilder。系统上下文不能被测试文件内容冒充。 |
| Tool loop + skills | native skill发现和调用已有实证；小满写脚本／SKILL.md即可发展能力。受控运行入口保留权限，不能为了QQ使全体任务绕过。 |
| followup / inject / steer | 复用消息投递和队列语义；它们不是Asuna任务完成回执。宿主保留意图／任务／场景关联。 |
| Compaction | 复用native机制，角色摘要和执行摘要语义分开。现有auto禁用需要在持续使用路径接好，而不是另做压缩事务系统。 |
| Schedule | 使用原生记录、计时和恢复。到期进入宿主计划事件，不能裸followup绕过角色阶段。live root的生命周期需宿主管理。 |
| Session persistence | DSH保存运行轨迹；Mongo保存Asuna消息与记忆。显式各自确认，不以idle代表数据库和外部平台均完成。 |

### 关键解释

- DSH的原生Schedule是提醒：记录能持久保存，但到时依赖其所属live root；冷会话恢复后处理逾期。周期至少300秒，错过多次时只交最新一次，不是cron。原生dispatch表示已排队，不代表任务完成。[D1]
- Schedule源码对到期内容使用插件来源消息并`followup`，另写dispatch记录。它没有现成的Asuna计划权限或Python回调；本包的timer bridge是要实现的薄接线，不是已存在的API。[D2]
- `PromptContext`在变更或被压缩移除后追加快照；它不替应用做Mongo检索、权限选择或主题判断。[D4]
- 新技能目录发现与现有session的preset composition变更不是同一件事；发展普通脚本技能优先走已有稳定工具。[D5][D6]
- DSH的文件写入模式不等于QQ任务已获得网络／进程／读取隔离；保留当前真实执行沙箱，根据实际部署落实最小边界。[D8]

## 资料（仅在对应实现时查阅）

[D1] DSH Schedule 文档：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/packages/schedule/schedule/README.md`

[D2] Schedule 到期投递源码：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/packages/schedule/schedule/src/runtime.ts`

[D3] Agent 核心与pre-step／消息投递：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/docs/subsystems/core.md`

[D4] System Prompt／PromptContext：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/docs/subsystems/system-prompt.md`

[D5] Filesystem skills：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/packages/skill/skill-filesystem/README.md`

[D6] Agent presets：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/packages/preset/agent-presets/README.md`

[D7] Session与flush：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/docs/subsystems/session.md`

[D8] Sandbox边界：
`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/fb2c4b9e698e30edb738bca4cf0618587db7d203/docs/subsystems/sandbox.md`

[N1] NapCat 网络配置：
`https://napneko.github.io/config/basic`

[N2] OneBot 11 正向WebSocket：
`https://raw.githubusercontent.com/botuniverse/onebot-11/master/communication/ws.md`

[N3] OneBot 11 消息事件：
`https://raw.githubusercontent.com/botuniverse/onebot-11/master/event/message.md`

[N4] OneBot 11 公共API：
`https://raw.githubusercontent.com/botuniverse/onebot-11/master/api/public.md`

NapCat管理WebUI与OneBot业务端点不是一回事。只选本机当前已启用的一种传输；正向WS已开启时可同连接接事件和发API，但不要求为了本包改动旧实例。[N1][N2]

`echo`用于请求／响应关联，不是可靠去重键；成功发送返回的message_id也不等于对方已读。正文尽量使用纯文本segment，防止把模型生成的字符串当成额外平台命令。实际字段以安装版本核对。[N2][N3][N4]
