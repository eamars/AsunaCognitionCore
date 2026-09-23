# ADR-005 依据、变更与证据边界

2026-09-23。此包由架构师根据用户更正编写；不是当前本机源码审核或运行验收。只读取上一版功能包的全文与公开协议/DSH相关文档，没有clone项目、连接用户服务、运行用户模型或代写功能实现。

## 1. 本轮最高优先级依据：用户更正

- 功能包正式改为ADR-005，是新独立项目，不依赖ADR-004；原UI任务不重命名。
- 增加QQ昵称、群名片、群成员/管理员等平台资料与适用的QQ功能。
- 增加真实读图，依据实际能力动态决定谁阅读，不按脑/模型名字写死。
- 开发主体改为运行中的小满；Codex只观察和提意见。

这些更正覆盖上一份草案的编号、默认作者分工与角色优先视觉描述。原始七类产品能力、非退化的DSH设计原则、Web实际使用和受控多人验收保留。

## 2. 对已交付草案做了哪些实质修改

已读取上一包CODEX_START、DECISIONS、DELIVERY_PLAN、ACCEPTANCE和SOURCE_NOTES全文，并保留其中不冲突的功能语义。本包自包含，旧包不是执行依赖。

| 旧草案内容 | ADR-005处理 |
|---|---|
| ADR-004.1编号 | 撤销该误称；本包新建独立ADR-005记录，不改原ADR-004。 |
| Codex负责宿主查询/持久化/媒体接线 | 删除默认分工；小满编写这些必要实现，Codex仅审阅/建议。 |
| 缺接口默认Codex补 | 不再成立；已授权开发域内由小满实现，真实权限缺口提出给用户，不自动接管。 |
| 角色路由支持视觉时直接给角色 | 替换为实际能力与任务驱动的分工，可双方读但不强制重复。 |
| 七类功能与默认产品值 | 保留；新增QQ资料和视觉章节，未将旧未验收项变成通过。 |
| 必須等待第二真人/所有旧验收 | 不要求；受控原文经隔离的同一宿主实现验证功能，真实平台体验另标。 |

早期ADR-003错误说明曾区分“错误可见、能够诊断、修改权限、恢复执行”，并承认额外检查改变运行语义。这里只保留这项教训，不把旧错误报告当作当前代码仍有那些限制的证据。新的作者分工也不保证小满永不犯错；建议和实际诊断仍可进入原任务，但不能靠Codex反复新建用户输入推进。

## 3. 本次外部核对（只作接口线索）

### N1. OneBot 11 公开API
https://raw.githubusercontent.com/botuniverse/onebot-11/master/api/public.md

成员接口区分user_id、group_id、nickname、card、role等；角色有owner/admin/member。群成员列表不保证与单成员接口字段完全相同。好友remark与nickname也有区别。这些是QQ事实接口，不是Asuna权限API。

### N2. OneBot消息事件
https://raw.githubusercontent.com/botuniverse/onebot-11/master/event/message.md

群消息sender可含昵称、名片和角色，但字段按尽力提供，可能缺失/缓存过时。故本包要求旧值、未知值和当前核实分开，而不是每句话强制刷新。

### N3. OneBot通知事件
https://raw.githubusercontent.com/botuniverse/onebot-11/master/event/notice.md

管理员变更、成员变动等通知可作为当前资料更新来源。具体NapCat版本可能有扩展，不假定每种名片变更都有标准事件。

### N4. NapCat官方兼容表
https://napneko.github.io/develop/api

官方列出了资料、群、成员、图片等OneBot接口与若干扩展能力。只用于定位已有接口；是否在本机部署支持仍由当前实际返回/版本决定，不据网页升级或重装NapCat。不能从“有管理API”推导本任务允许所有管理副作用。

### D1. DSH模型和多模态消息契约
https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/llm-streaming.md

当前上游的模型元数据包含inputModalities（缺失表示未知），且有原生image内容块。目录是发现材料，不等于运行授权或完整功能验证。本机固定版本未必有同名接口；用已有等价能力或小范围本地配置补充，不升级DSH、不新增强制资格检查。

### D2. DSH附件
https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/attachment.md

图片通过附件与请求序列化链到达模型；UI中的图或文字路径本身不能替代实际多模态输入。复用本机对应路径，不把上游main的类型细节直接当成本地现成API。

### D3. DSH工具扩展
https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/tools.md

用于查当前可扩展工具和结果路径。新读图/资料能力沿已有执行循环，普通工具错误不另建宿主终止策略。

## 4. 旧源码线索的地位

上一份草案曾选择性核对Asuna的retrieval.py、memory.py、memory_indexer.py、schedule.py、router.py、publish.py、application.py、host.py和RUNTIME_API.md。本轮没有重新获取当前工作树，因此DELIVERY_PLAN中的路径只是供小满按需定位的线索，不能作为“最新代码缺某项”的判据。

尤其不能从旧裸DSH小满的模型名带vision、旧skill清单中存在read_image，推断当前Asuna部署已经能看图。以当前获准的模型路由、附件接线和实际调用为准。

## 5. 本包交付检查不等于产品通过

仅检查本包文档相对链接、编号、作者分工和示例可解析性。没有本地QQ读取、图像推理、自动总结、定时或自主开发的新运行证据。

包内示例均为合成来源，无生产账号、凭据或私人聊天。旧22条原始对话素材保留，另加6条QQ资料/通知素材；所有素材都不是生产HTTP契约，不携带授权答案，也不直接写最终偏好、分数或模型回复。
