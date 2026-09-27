# 实施顺序与局部验收

## P0：先证明原生接点

只做一条接线，不迁移全库、不先改全部 UI。

使用当前固定版本创建一个可安装的 Core 开发包和真实 Asuna 角色 preset/session。启用的是同一个 DSH Host；不同 session 不是第二个运行时。已有正常服务不被这个准备步骤擅自重启，测试路径不得同时消费相同 QQ 路由。

验证原生 composer 提交 → scoped 阶段上下文 → 实际角色模型输出 → 必要委托 → 实际行动原生会话与工具结果 → 角色原关联返回。用户给什么自然任务就沿实际能力走，不指定固定台词/工具轨迹。

只确认：
- UI 通过真实 Host SessionController 看消息，不调用旧 Asuna `/state` 作为聊天来源；
- 不发生同一消息处理两次；
- 阶段推进不嵌套等待自身 agent，不把内部反馈伪装用户；
- 正常行动错误仍在原生循环中，CONSULT 不导致角色/行动共享锁互等；
- scoped 插件不影响一个普通非 Asuna 会话。

若 native Chat 本身缺失必需关联接口，具体指出固定版签名、现有可用替代与最小缺口。本地 UI 拟定的业务节点可以调整，但不能 fallback 到 iframe、自绘全套聊天或修改 node_modules。P0 不是要求完美角色表现或新性能平台。

## P1：迁移运行所有权，保留业务

| 当前路径/职责 | 本轮处理 |
|---|---|
| `dsh_lane.py` + `runtime-v2.ts` 的独立 SDK/HTTP model-run | 将 agent create/resume、阶段接点、工具 setup 移入 Core Host 插件；旧桥仅到迁移结束前保留 |
| `application.py` / `host.py` | 拆出 Python 业务依赖与当前 queue/state/publication；删除 worker 再启动 DSH/Web 的职责 |
| `coordinator.py` | 提取现有阶段准备/结果消费；不复制成第二套规范流程 |
| `context.py` / `memory.py` / `retrieval.py` / `history_query.py` / `discussion_digest.py` | 复用实际实现、A2 和来源边界；不为迁移重做查询/摘要 |
| `tasks.py` / `integration.py` / `schedule.py` | 保留业务与授权，调用新的 Host agent/schedule 接口；不恢复 task_status/Goal/逐条许可 |
| `provider_proxy.py` | 先清点剩余实际依赖；取消“UI 得到 token 必须经过 Asuna proxy”的依赖；确有部署兼容职责时保留该部分而非照搬整代理 |
| `ui.py` / `ui_stream.py` / ui static/client/store | 原聊天搬到 native 后删除默认启动路径和无消费者部分；历史诊断源有真实用途可留只读访问 |
| `start-asuna.cmd` | 最终可做启动既有 DSH profile 的薄兼容入口；不继续串联重启双 Web 服务 |

不要按这些文件名整文件盲删；本机可能有别人的未发布修改。先沿实际调用链停用/替代，再删除本轮确实无调用者的分支。

## P2：人格与自开发项目独立

按 PERSONA_PACKAGING 建立两个 package。小满包使用当前真实角色资源和可分发代码；保留当前 Mongo/self head。连接角色自我读取/变更后的注入、技能目录和可发布工作树。

可检查结果：Core 不包含硬编码的小满正文；小满包安装能被选择；已有自我没有被重置；后续角色自己改一段理解或行动修改一个合适的 skill，更新由既有路径实际可见。不是让 Codex编造人格素材通过测试。

移出个人资源不缩窄现有 owner 自主开发能力；Core 依然可作为已有授权的开发目标。普通 QQ 不因它所在 Host 有 owner 原生终端而取得源码/credentials。不要把 default DSH standard 全工具配置盲目挂给 QQ。

## P3：仅两个新 UI 正文

按 UI_SPEC 接记忆右栏和设置卡。行动过程使用真实 native session，避免重复事件聚合。插件设置里的模型选择引用原生已配置 provider；凭据不经 prompt 和普通内容传输。

浏览器确认一条真正原位流、一条行动链接、一次记忆分页和点击详情、设置保存/未生效状态。DOM/实际 Network 是 UI 证据；构建通过不是界面完成。

## P4：接回 QQ/定时/发布并退出旧工作台

本轮不重演所有旧验收。沿现有授权选择必要的实际入口，确认 QQ 输入到对应角色 native session，最终一份 SPEAK 从原场景发出；owner 两个 DM 连续性仍由既有 A2 数据读取维持，不把 QQ 变成本机 owner 工作区。

计划使用原 Host 中调度会话。模型请求、回执或 worker 更新错误沿既有目标继续。保留单库和 forward-only。

现有 DSH 日志如果能以公开 resume/persistence 契约原样采用，可复用；若旧各 lane 的 DSH_HOME 无法直接接入当前 Host，不盲移同 ID、不拼接几个 log。保留原文件与 Mongo历史，在明确无 in-flight 副作用的边界创建真实新 native binding，用原授权资料接续，并记录这是迁移后的上下文恢复，不宣称 KV cache 或旧 native history 从未中断。

不回放已发送消息/已执行工具；不重建失败为新的用户目标；保持 task/feedback 当前状态及恢复职责。迁移不使用虚假历史使 UI 看起来完整。旧原文仍从记忆标签/历史来源访问。

完成后卸载旧 UI/plugin 启动项，并删除已替代的未引用代码。不得长期让新旧两套系统同时拥有一个 QQ route、outbox 或同一个 action 的执行权。已有 default UI 保留到真实切换成功，不用一半迁移制造长期断路。

## 最小验收与不是验收的内容

| 看什么 | 通过含义 |
|---|---|
| 包安装 | 两个本地 tarball/插件产物，遵循固定版 Loader/Client 格式；普通 DSH 原生页面启动 |
| 原生执行 | 一条真实角色输入及行动关联确实属于同 Host session；不是镜像文本 |
| 角色连续性 | 当前自我与相关原记忆可用，MONOLOGUE 仍是实际内容；不评分人格 |
| 工具 | 当前可用 web/todo/skills/history/开发工具不因迁移丢失或由新 approval 阻断；不逐项跑全矩阵 |
| 来源/QQ | 绑定与实际目标保持；无复制输入或双发 |
| 记忆与配置 | 标签/卡片由原生插槽承载，列表有界详情按需，秘密不进入普通内容 |
| 自发布 | 对小满项目的正常修改不依赖 Codex；最低失败仍保留开发入口，事件返回原目标 |
| 旧负担退出 | 默认不再加载自有聊天 polling/stream/store/scene renderer；相关订阅可释放 |

文件包/依赖契约检查和少量 deterministic 接线测试可做。真实模型不要求同 seed、同工具路径、固定字数或多次抽样。一次正常长交互检查 UI 是否重复下载、堆持续增长即可，不设虚构“必须小于X MB”。

## 最终报告与停止

聊天报告：实际安装方式、原生真实会话如何进入、删掉什么旧路径、Python 尚保留什么、两个包如何开发/发布、可见界面证据与确切未验证项。当前手册写现在的使用方式；`docs/development_plans/**` 保留，不把日记继续塞 README。

基座接通后 Codex退出日常迭代；不继续建 marketplace、通用插件管理器、workflow designer、全域观测台、模型服务控制器或“下一代 Asuna UI”。
