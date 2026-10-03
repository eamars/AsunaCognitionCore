# 界面：原生聊天，两个新增业务位置

本方案替代旧“自绘 Asuna 三栏工作台”交付方向；不是让 Codex 继续在 `/asuna/` 内复制 DSH 布局。

2026-10-03 已批准[主会话内连续展示双脑记录修订案](AMENDMENT-20261003-INLINE-BRAINS.md)。以下第 2 节的分会话默认展示决定由该修订替代；其余原生 UI 边界继续适用。

## 1. 默认页面

```text
DSH 原生会话导航 | DSH 原生 Chat / Trajectory | DSH 原生右侧栏（按需打开）
真实角色/行动会话  实际消息与 native tool rows    “Asuna 记忆”标签
```

不自绘左栏、composer、消息 store、流式缓冲区、分页器、session switcher 或连接状态条。原生 New Session 属于 DSH；不要再造一个 Asuna“新上下文”。新原生会话也不会自动接管某个已绑定 QQ 场景或获得 owner 权限。

## 2. 角色与行动怎样看

- 角色会话显示模型真实生成的 MONOLOGUE/阶段内容和公开表达；阶段标签使用小型 Asuna 业务事件/已有扩展位置。
- 行动任务引用同 Host 内真实原生 session 的记录，在主会话中阅读；原生子会话导航仍可用于诊断。
- 经 2026-10-03 修订，默认在角色主会话连续展示双脑真实记录，紫色“角色脑”、蓝色“行动脑”沿用已批准标签。底层原生会话和上下文独立，展示组合复用原生记录与渲染，见修订案的实现边界。
- 两脑身份标签默认可见，放在原生过程折叠区外；折叠只控制记录内容。沿用同一种 Pill，不追加描述词、输出标签或自绘控件。同一原生角色回合的多个阶段只显示一次身份，每个步骤的实际归属仍保留。
- CONSULT 关联原调用，结果留在实际来源会话和 tool result；不为它多发一条 QQ 公开消息。
- 原生 Assistant 文本 renderer 不作全局 shadow；不复制猫娘插件给输出加后缀的方案。
- MONOLOGUE 的自然正文不改成 reasoning 类型。不要另建 Thinking 专区。当前原生 UI 对 native reasoning 的显示遵从其现有可用设置，不能伪造字段或另造 renderer 来假称二者相同。
- provider 原包使用原生会话日志/已有诊断按需查看，绝不替代正文。不能因为 observer 未打开而停止模型。

重要取舍：这里保留“两个脑的真实过程可查”，不承诺仍用旧工作台的同一位置显示所有内容。换取的是直接复用 DSH 原生会话流与导航，而非维护两个 UI。

## 3. 记忆标签：一个新增业务正文，不是 Memory CMS

原生接口：`ctx.sidebarRightTabs.register(...)` 注册 page kind；正文注册 `sidebar.right.pane.tab`，使用实际 `useTabInfo()` 与当前 session 绑定。由原生 guide/右栏入口打开，不新增常驻按钮栏。

标题“记忆”。正文默认呈现当前角色和当前场景；提供一个类型选择：全部 / 自我 / 关系与偏好 / 交流摘要 / 原始来源。利用公开 Input、Button、DisclosureRow、MarkdownText、CodeBlock；沿现有字体和间距，不绘制新图表、关系网或五色评分卡。

**列表**：标题、简短原文摘录、更新时间、实际类型/来源场景。沿已有分页，默认一页，不读完所有历史到浏览器。隐藏/切换后释放对应订阅，不能在关闭标签时持续下载整库。

**详情**：点开才取得正文、当前版本、实际发言人、时间与来源；原文和模型理解分开展示。来源回读沿现有授权查询，不把 Mongo 原记录伪造成原生聊天消息。

**自我**：显示当前 Character Core / Current Self / VOICE 的实际内容与来源版本，沿现有用户查看/编辑权限；没有等价编辑接口时不新增任意 Mongo 编辑器，用户仍可通过正常聊天让角色自己调整。

**关系**：显示现有正文及已有档位，不在 UI 重新评分、合并不同人的偏好或发起情感校验。

现有 owner-private continuity 仍可从双方来源检索；群会话不会因为打开记忆 tab 继承 owner 的可见范围。对操作者与 QQ 消息执行身份的区分沿当前授权，不新增“记忆访问模式”开关。

## 4. 设置卡：放在 DSH Settings → Plugins → Asuna

Host 用 `ctx.settings.installSection` 注册一处 namespace，Client 用 `ctx.settingsScope.bind` + `settings.plugin.item` 对应。

首版字段只覆盖本次功能：

| 分组 | 内容 | 不做什么 |
|---|---|---|
| 连接 | 现有 Mongo/业务 worker 配置与可用状态；私密值写 secret 或凭据引用 | 不把 URI/token 送到角色或网页正文 |
| 双脑路由 | 角色脑、行动脑引用 DSH 已配置的 provider/model；可显示实际能力元数据 | 不重做供应商列表、API key 编辑页或模型服务启停器 |
| 当前角色 | 选择已安装的小满贡献，显示版本、工作目录、当前自我来源 | 不在设置保存时覆盖运行中人格正文 |
| 现有集成 | 配置引用与当前状态；沿已有机制决定是否需要重载 | 不新增 QQ 逐条开发许可或互联网开关 |

模型凭据仍在 DSH 原生模型设置管理；Asuna 只保存路由引用。Mongo/NapCat 等确实不是 LLM provider 的凭据，可以放宿主原有本地配置/secret 字段，显示“已配置”而非完整值。

配置写入失败保留表单和真实原因；已保存不等于立即生效，原生 `applies: restart`/实际应用状态说清即可。不在 settings 保存前额外做模型问答或语义健康评分。

## 5. 已批准的最小自定义范围

DSH 没有 Asuna 的记忆查询正文，也不会自动根据 namespace 生成完整 settings card；因此本轮批准“记忆 tab 正文”和“Asuna 设置卡正文”，其外壳/控件/请求作用域复用原生能力。

还批准一个必要的角色→行动 session 业务关联节点，若原生已有实际 subagent 展示且真实关系符合则优先复用；不能伪造子 agent 归属来套控件。

这些不是允许重做主会话 UI 的例外。不得全局占用 `assistant-step`、`main.conversation`、`sidebar.workspaces` 等已占用位置。

## 6. 可见行为检查

用真实 DSH Web 页面检查 native composer、角色实际内容、行动会话跳转、一次 CONSULT，以及记忆点击后才加载详情。刷新/重连通过原生 controller 衔接，不要求用户 F5 才结算，不重发任务。

浏览器内存与延迟仅做与改动相关的一次观察：确保旧 `/asuna/api/state`/`stream` 主聊天请求已退出，记忆关闭时不轮询、大正文没有复制成多条历史。记录实际堆/请求体等；不保证固定内存数、不用裸 DSH 模型质量 A/B 代替 UI 接线判断。
