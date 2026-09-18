# 01 · 架构、职责与设计要求

## 1. 范围与可证伪目标

V1 要验证六项假设：

H1：Gemma 获得完整、稳定的角色材料之后，比未设定角色的同一部署更能实现目标人设；这种差异不能只用“更温柔”判断。
H2：Qwen 的工具能力能被角色意图驱动，且不侵占意图、价值和公开表达。
H3：工具操作噪声、无关群消息、不同步 compaction 不显著损害角色连续性。
H4：多用户与跨群隔离在注入、检索、写回、发布和审计各层均成立。
H5：人格/记忆可演化且可回溯，不由重复检索、压缩或重试制造虚假经历。
H6：发生故障时系统可以准确报告未知、恢复状态并避免重复副作用。

“通过 V1”仅是通过本包的有限实验，不是数学上保证模型永远不走样，也不是证明模型具有真实情感或可读 thinking 等于真实因果过程。

### V1 必做

文本实时输入、2 个群场景 + 2 个私聊；身份映射；角色独立 monologue；工具委托/中断/回传；聊天及角色记忆持久化；真实向量检索；关系个性化；版本化人格修订；两侧独立压缩；重启恢复；本地模型真实评估；逐步审计与故障注入。

### V1 不做

真实 QQ/Discord 发布、真实家居设备控制、语音/视频、人脸身份、自由运行的无限自我改进、自动修改自身执行代码、全量旧记录迁移、通用插件市场、多机 HA。接口需留出，但不能让它们阻塞认知机制验证。提供手动/虚拟时钟触发的反思任务和提醒任务，验证生命周期即可。

## 2. 拓扑

```text
本地 CLI / 场景重放 / 虚拟计时事件
                 │
       [认证、身份、去重、场景路由]
                 │
       Python Coordinator（唯一业务状态机）
        │           │                  │
        │     MongoDB State/Memory     ├── Audit / Replay / Reports
        │           │                  │
        ├── ContextBuilder + Retrieval │
        │                              │
  Character DSH lane              Executor DSH lane
  Gemma4 26B                      Qwen3.8 Flash
  session: 每个社交场景             session: 每个任务连续体/项目 + scope
  无通用工具                       有界工具循环
  monologue → decision → speak      执行 → 证据结果/阻塞/需重议
        │                              │
        └──────任务记录与阶段回执─────────┘
                 │
         PublishService（唯一聊天出口）
                 │
       本地幂等消息接收器 / 用户视图
```

两种 lane 不是两个人。共享人物内核；角色模型拥有情境评价、意愿、关系理解和声音。执行模型得到同一身份内核与任务适用原则，但不接收无关私密关系和完整社交历史。

推荐两个长期 DSH subprocess，分别绑定两个模型路由，降低 SDK 全局初始化与跨 preset 泄露的复杂度。每个 subprocess 可管理多个同 lane 的持久 session。不是每次 monologue 新建进程，也不是每项小工具新建 Qwen session。单进程多 lane 可作为有依据的优化，不是 V1 必需。

## 3. 所有权和强约束

| 对象/决定 | 权威所有者 | 模型可以做什么 |
|---|---|---|
| 外部身份、场景、ACL、已送达事实 | 程序/消息平台证据 | 不能自报或改写 |
| 人格、语气、自身愿望、对人的态度 | 角色生成内容 + 程序版本存储 | Gemma 可提出并提交合规更新 |
| 用户/设备事实 | 原始事件及工具证据 | 两模型可解释，不可把推测变事实 |
| 当前行动意图 | Gemma 的明确 decision | Qwen 可指出不可行、请求重议 |
| 工具选择/执行/技术计划 | Qwen + 执行权限代码 | 在任务范围内自主推进 |
| 检索范围与基线记忆到达 | ContextBuilder | 模型可请求追加检索，不能扩权 |
| compact 时机和被替换范围 | DSH adapter / 程序预算 | 模型负责受控摘要，不改权限 |
| 发布对象与“已经说出” | PublishService + receipt | 只有经授权角色 speak 可以成为聊天正文 |
| 测试标准/审计保留/模型路由 | 操作者配置 | 演化不能修改 |

有界权限和真实状态是确定性约束；“像不像小满”是行为质量，不能靠一串禁词假装彻底解决。

## 4. 角色阶段：弱工具模型也能运行

默认每个被接纳的角色事件执行以下阶段；各阶段在同一角色 session 追加，不切换 preset。

1. `PREPARE`：冻结 scope、persona revision、关系 revision、有效 task revision；检索/去重/预算；验证最终准备材料。
2. `MONOLOGUE`：Gemma 一次独立普通文本输出，第一人称 1–4 句。可以平静，不强迫每次有情绪。不是 native reasoning 的复制。
3. `DECIDE`：Gemma 在相同上下文输出极小 JSON：`next=speak|delegate|recall|silent`、自然语言目标及非机械性的约束。程序补充 ID、权限、收件人。格式错误最多一次同模型修复；不能由 Qwen 重新解释她的意图。
4. `SPEAK`：需要时由 Gemma 单独产生公开话语。不输出控制 JSON、monologue 或工具过程。提交之前检查当前 episode/task/policy 仍有效。
5. `COMMIT`：保存 monologue 引用、发布候选和事件链接。公开文本必须通过唯一 PublishService。角色明确选择 silent 也要记录原因类别，不用假回复占位。

三次调用是 V1 可审计基线，非终态性能承诺。通过后可实验合并 MONOLOGUE 与 DECIDE，但必须重新测协议可靠性、文风与延迟，不能悄悄替换基线。普通问候不应调用执行模型。

DECIDE 选择 recall 时，由程序在当前 scope 内追加记忆结果，再进入 MONOLOGUE/DECIDE。每 episode 最多两次 recall；超过后记录 NEEDS_INFORMATION，不得无限循环，也不自动把缺失信息编成答案。恢复与修复轮的临时输出可审计，但只有被接受的 monologue 版本参与长期召回，避免修复垃圾挤占记忆。

独立 monologue 保存在角色历史、memory_units 和 episode 引用中；公开 message 关联相应 monologue IDs 供操作者以后调用，公众 API 不展开。存储关联不能造成相同独白在模型历史中重复追加。

`stop` 结束当前模型生成；它不等于 episode 完成。空白/截断/纯 thinking/原生 tool-call 出现在无工具阶段都属于阶段异常，不能被当作成功或沉默。模型输出的修复/重试不是新增经历。

### 委托和反馈

DECIDE 选择 delegate 后，程序创建 task 并入 Qwen 队列。若角色决定需要先告知，先执行一次 SPEAK；不强迫所有任务发占位回复。Qwen 结果以 `done|partial|blocked|needs_character_decision` 返回，并含完成事实、未完成项、不确定性、证据引用和实际副作用回执。

Gemma 再次收到结果时，形成新的 feedback episode，明确因果关联并可更新 monologue。重要失败可以改变她的看法；无关工具日志不能成为人物输入。Qwen 不能要求她“你应该高兴/温柔”，这种表达不属于可接收结果字段。

回传以终态/影响意图的变化为唤醒点；一般进度只存审计。模型循环最多 3 次角色↔执行重新委托；超过后记录 blocked，需要新事件再推进。每个 task 最多 64 个工具 step，默认一个项目同时只有一个活动 task。参数均可配置、冻结到实验 manifest。

## 5. 记忆的到达与权限

人格基线与授权的场景连续性由程序加载，不让 Gemma 先调用工具找自己。

ContextBuilder 分层装配：

- 稳定层：版本化角色内核、表达原则、能力概述、内部协议。
- 场景层：可信参与者、回复链、该场景允许使用的关系状态、未解决事项。
- 回忆层：当前相关事实、经历、monologue 及其时间/性质/来源。
- 新事件层：原始输入或带证据的任务结果。

同时保存 selected/excluded/truncated 条目、token 预算、排序、source revision 和最终 provider 请求映射。文件存在、检索到、选择了、序列化进请求、模型声称使用了，是五种不同事实。

第一版检索是程序协调的结构过滤 + 向量召回 + 精确/关键词补充，不增加常驻 RAG agent。reranker 接口预留，默认关闭；Qwen 仅处理复杂证据查询，不是每轮记忆入口。

### 私聊隔离原则

scope 是硬边界，人物知道一件事不等于每个场景允许使用。v1 默认不让私聊信息流入群内角色上下文，连由该信息产生的私密关系结论和摘要都不可跨域。

生成记录继承整次模型请求中信息的保守 scope，不仅看模型列出的 source_refs。私密材料生成的“泛化人格修订”默认只能成为私域 overlay；不能删除姓名就升为全局。全局自我修订只使用 global-safe 源；解除限制需明确操作者操作与审计。

跨域发布 v1 默认禁止。请求“把这段私聊转发群里”返回需明确分享授权的状态；不能由 Gemma 的一句愿意替代程序确认。

## 6. 多人/多群与关系

`scene_id` 表示群 G1/G2 或私聊 D1/D2；`person_id` 是可信身份，不根据昵称推断，跨平台账户链接需操作者确认。群内保留共同的社交顺序、reply_to 和显式 mentions；话题是标签，不自动开 agent。

角色 binding key：`character_id + scene_id + policy_epoch + model_route`。执行 binding key：`project_or_task_lineage + scope_key + policy_epoch + tool_policy_revision + model_route`。禁止以“同一个角色”把私聊和群聊绑定成同一 session。

关系由 scoped 叙事 + 4 个低精度参数表达：familiarity、trust、closeness（0–4）、tension（0–4）。参数是角色状态，不是心理测量；不自动换算唯一好感总分。记录对方事实、角色解释、交流边界、未完成关系事项。情绪是 scene/subject-scoped 的当前 appraisal，不用单一全局“心情差”污染所有用户。

相同名字两个人、一个人在不同群、第三人引用私聊、群内轮流发言都必须测试。关系更新只有 Gemma 可提议，程序检查主体、来源、版本、scope；重复事件只影响一次。熟悉度不开放更多数据权限。

## 7. 人格演化

状态有 `persona.base`（global-safe）、`persona.overlay`（scope）、`relationship`、`scene_affect`。正常对话不重写整个人格。

用有界 REFLECT episode（手动或虚拟 timer）提出显式修订：base_revision、目标字段、old/new、reason、source_ids、scope、change_class。由程序校验并 CAS 提交。scope 无法升级；policy 类路径不可写；普通用户引用文本不是系统指令。

日常已完成 episode 自动保存 monologue，实际事件自动记录；长期解释/关系变动可由周期反思生成。允许得出 no_change，不为“进化”强迫修改。保留旧版本，可比较、回滚。每次 active episode 固定旧版本完成，下一 episode 使用新版本；权限撤销立即打断并重建受影响上下文。

模型对事实的错误解释可以修正，不能改写原始用户消息/工具回执。旧判断保留为“当时看法”，与当前状态分开。重复召回、compaction、反思引用不能被计为新的外部证据。

## 8. 上下文、compaction 与缓存

两边独立周期。不因 Qwen 压缩而清空 Gemma；不把 Qwen 摘要投给 Gemma当人物恢复包。任务/承诺/已交付状态在 Mongo 外部记录中，不靠 session 摘要唯一保存。

部署上限暂定 262k：需分清用户称呼 262k、日志 `262000`、模型/服务端 `262144`。预检记录 DSH、服务端、tokenizer 三方容量；有效上限取可证明最小值。客户端虚报大窗口不算支持。

V1 初始工作预算（实验参数，不是最佳值）：角色 65,536、执行 196,608；各自最大输出 4,096/8,192，硬安全余量 4,096。角色 recent tail 12,288；执行 32,768；角色摘要上限 4,096，执行 8,192。硬不变量：实际准备输入 + 本次完整输出预算 + 安全余量 <= effective capacity。正常步骤的软输入上限取 min(working_input_budget, effective_capacity - max_output_tokens - safety_margin_tokens)，在加入新消息/工具结果之后检查。不得只设最大窗口元数据而忘记实现工作预算；容量压力测试的显式覆盖另行记录。

优先在完整 episode 后软压缩。自动压力/硬溢出时不得剪断 tool-call/result 对，也不得只留下 monologue 丢掉其输入/发言对应关系。若 DSH 平衡范围不理解 Asuna episode，用显式 range selector；仅改 summarize 模板不够。无法安全压缩就明确 blocked，不隐藏截断。

角色摘要保留人物现在所知、事实与推断的区别、未决关系/愿望、有效承诺、任务关联、少量关键 monologue 原文。基线人格从版本存储重新注入，不从多代摘要递归重写。摘要不得制造新关系分数或 persona revision。

执行摘要保留目标、授权约束、关键证据、失败路径、资源、进度、下一步，不要求角色化。两侧 summary 调用都纳入本地模型队列、token 与审计统计；不能在普通 request hook 之外漏审。[S2][S4]

Gemma native thinking 默认按其部署模板处理；官方多轮建议不重放普通回合的旧 thoughts，工具回合例外。monologue 是普通 content，因此独立保留。Qwen 的 thinking replay 以用户实际部署为准，不套用别的 Qwen 版本规则。[S9]

不得每个阶段更换系统 prompt 或工具表。阶段指令追加到历史。人物小修订用版本增量/快照追加，自然重建时合并。记录实际序列化前缀变化；高 prefix reuse 不等于模型真使用记忆，KV cache 命中也不等于免除 decode。[S3][S10]

## 9. 调度、可靠性与安全

每个推理 endpoint 默认并发 1。两个 endpoint 能否真正同时运行先测；共享硬件/同 executor 则用同一 resource group semaphore。标题自动生成、默认云 web provider、自动 agent teams、额外评分模型等一律从验收 profile 移除。

队列按 scene 公平轮转，同场景最多连续 2 个 episode；不抢占正在 decode 的调用。直接 mention/reply/私聊优先；普通群消息写入聊天记录，但默认不唤醒角色，直到相关事件或批量场景 tick。不把所有未回应群消息变成欠账。

Qwen 不能持有 MongoDB 凭据、公开发布凭据或操作审计文件。代码工具在独立限制环境中执行，仅挂载 task 工作区；默认无网络，不挂宿主 DSH_HOME/旧仓库/密钥。模型调用由可信 DSH runtime 发起，工具子进程与其权限分开。若本地 DSH 沙箱不能证明该隔离，改用受控执行工具 broker；不能因提示词写了禁止就宣布安全。

所有真实外部副作用在 V1 关闭。本地发布接收器支持 idempotency_key。一般远端 exactly-once 无法由本架构单独保证：接收端不支持幂等且发送后丢回执时标 UNKNOWN，禁止自动重发。人物发言需区别“准备”“接受任务”“已完成”“已送达”。

明确边界：Runtime/模型服务器/操作者为可信计算基。不是抵御宿主 root、模型权重恶意代码或外部数据库管理员的全面安全证明。hash 链提供检测材料，不是不可抵赖公证。

## 10. 不可用“结构验证”伪装成已解决的语义问题

程序可以确定性验证scope、phase、schema、task版本、证据引用是否存在，以及消息是否真的送达；但不能仅凭JSON schema证明自然语言完全没有幻觉、语气一定像人物、价值观始终被遵从。

V1 在PublishService做结构/权限/状态验证，语义真实性通过限定工具结果、明确未知、行为回归和人工盲评检验。不要把一个未经验证的LLM“安全评分器”插入后就宣布绝无幻觉。非合格speak可以标记失败和保留样本，不能在评估中暗用模板重写成正确答案。

在任何模型请求中，fixture的gold、expected、p1_prediction/p2_prediction、oracle代码都属于测试控制面，不可加入模型输入。它们只供runner和评分者使用。
