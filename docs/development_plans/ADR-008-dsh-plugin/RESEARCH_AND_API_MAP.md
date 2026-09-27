# 研究依据与固定接口地图

## 证据口径

没有 clone 两个仓库；只读选定 raw 源文件/文档。DSH 参考固定标签 `dsh-v0.1.5-rc.2`。Asuna 和猫娘插件读取的是公开 `main`，不是本机运行快照；main 在研究期间有更新，不能将不同时间的网页片段称为一个冻结commit。Codex动手前只核对本机相关调用链/实际依赖，不用公开main覆盖本地成果。

本包未运行 DSH、Python业务宿主、QQ或用户模型。P0仍是必须证明的一处集成可行性，不是已经验收的事实。

## 原生可复用与明确限制

| 需求 | 已核对公开接点 | 实施限制 |
|---|---|---|
| profile/package | `dsh.bundle.patch` / `dsh plugin --profile …` | 自定义profile先由web模板建立，不能安装成只有base而没有Web；不自动覆盖已有profile |
| per-agent组成 | `ctx.agents.create/resume` + `setup` / native preset | 不伪造SessionBinding；scope之外不拦其它会话 |
| 人格与记忆 | `systemPrompt.section/context` | 动态内容用快照；不每次重构system prefix |
| 角色阶段 | `agent/pre-step`、native session events、`agent/turn-stopping` | P0验证异步顺序；不自己调用agent-loop；不在自身hook等待自身空闲 |
| 原生聊天 | SessionController、Conversation、Chat、Trajectory | 需要同一Host真实session，不接受任意Mongo消息数组替代 |
| 记忆界面 | `sidebarRightTabs.register` + `sidebar.right.pane.tab` | 只加业务正文，不替换rightbar |
| 插件设置 | `settings.installSection` + `settingsScope.bind` + `settings.plugin.item` | card正文由插件提供；不是一份schema自动生成整页 |
| 浏览器构建 | `./client` export、`dsh.client`、lazy-CJS factory | 无公开可import的仓库私有tsdown preset；自己生成同格式，不复制React |
| Host→Client业务读取 | API gateway/Remote | 需真实public注册与构建声明；不能凭空使用ctx.remote.asuna |

## 猫娘插件：借什么，不借什么

借鉴 npm分包、公开插槽、薄prompt贡献和外部Client构建方式。它的主打方案把猫娘口吻加在显示层、并裁剪工具；这与Asuna需要角色脑独立理解和行动能力保持不同。其简短任务自评不能证明本项目无需双脑或可安全删工具。本轮不安装它为Asuna运行依赖。

## 安装形状（是待实现产物，不是现在已可执行的包）

先构建并在本机生成两个tgz，使用本机现有固定版 `dsh`。可复用现有Web profile或一次建立自己的Asuna web profile；后者是运行配置，不是新的用户UI/context管理器。

```text
# 首次建立自有profile时：会实际启动，须在约定维护时机执行
dsh --profile asuna --from-default-profile web
# 安装本次实际生成的tarball，文件名以npm pack真实输出为准
dsh plugin --profile asuna add /absolute/path/to/core.tgz /absolute/path/to/xiaoman.tgz
# 查看有效组合；按实际plugin命令输出核对bundle列表
dsh --profile asuna --dump-config
# 正常运行使用同一个DSH launcher
dsh --profile asuna
```

安装依赖与把bundle加入profile composition不是仅凭文件存在就完成；核对 `dsh.profile.bundles` 与最终dump的实际注册。避免手写目标机器绝对路径进入可分发包；局部开发路径放本机配置。

## 来源索引

### S01 — Asuna dependency pin
锁定 DSH 0.1.5-rc.2；不说明本机工作树是否已发布。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/package.json

### S02 — Asuna lane boot
各 lane 启动独立 DeepSeekHarness sdk-minimal，配置代理/原生工具。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/dsh_lane.py

### S03 — Asuna runtime bridge
已有真实 agent create/resume/setup、operation关联可迁移。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/dsh-plugin/runtime-v2.ts

### S04 — Asuna client
自有state/stream/history/viewStore；后续读取已见delta、revision及idle降频，不声称所有旧缺陷仍在。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/dsh-plugin/ui/client.js

### S05 — Asuna UI server
现有场景/记录/诊断视图及Asuna服务接口。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/ui.py

### S06 — Asuna context
persona/关系/linked scope/近期历史的实际使用位置。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/context.py

### S07 — Asuna state
state heads/revisions及现有角色硬编码需脱钩；不是全库迁移建议。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/state.py

### S08 — Asuna skills
当前skills路径与owner限定，不能只移动文件不改接线。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/skills.py

### S09 — Asuna development
现有候选/发布目标绑定ROOT，拆包需调整目标路径而非重新构建发布平台。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/development.py

### S10 — Asuna application
当前模型lane依赖组装。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/application.py

### S11 — Asuna coordinator
保留现有角色阶段含义，拆同步控制边界。

https://raw.githubusercontent.com/eamars/AsunaCognitionCore/main/src/asuna/coordinator.py

### S12 — DSH preview status
官方明确预览版会有兼容性破坏；插件不等于永久免维护。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/README.md

### S13 — DSH architecture
Host、profiles、scope、真实事件与流的归属。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/architecture.md

### S14 — DSH core APIs
AgentFactory/setup、followup/steer/inject、pre-step和turn-stopping、whenIdle边界。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/subsystems/core.md

### S15 — Native conversation
真实会话事件与view node，增量组装和稳定关联。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/subsystems/conversation.md

### S16 — SessionController
原生会话观察、历史分页、live chunk结算。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/api/session-controller/README.md

### S17 — Workspace contracts
工作区必须有实际路径和匹配session cwd。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/subsystems/workspace.md

### S18 — Client slots
新增key而非shadow全局，公开插槽层次与scoped props。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/subsystems/slots.md

### S19 — Right sidebar
sidebarRightTabs.register与sidebar.right.pane.tab，原生dock/chrome。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/client/ui-sidebar-right/README.md

### S20 — Settings card cookbook
installSection/settingsScope、secret字段、插件必须提供自己的小card正文。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/cookbook/adding-a-settings-card.md

### S21 — Client module packaging
dsh.client和./client，lazy-CJS factory，共享runtime externals。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/client/modules/README.md

### S22 — Manifest
bundle.patch/client是真正metadata；persona贡献接口需由Asuna定义。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/util/package-manifest/README.md

### S23 — Preset
空session选preset、composition generation、子agent继承，不能当运行时人格数据库。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/preset/agent-presets/README.md

### S24 — Persona prompt
scoped persona配置，complete不是随便全局设置。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/preset/persona/README.md

### S25 — Prompt contexts
稳定section与动态context分开，native日志化与压缩后恢复。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/subsystems/system-prompt.md

### S26 — CLI/profile install
dsh plugin --profile … 转发pnpm；原生web启动，不需要重建apps/web。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/apps/cli/README.md

### S27 — App boot
profile bundle/patch、各profile reload不同、dump-config。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/boot/app-boot/README.md

### S28 — Typed remote seam
Remote需真实注册/类型生成与mount，不存在自动ctx.remote.asuna。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/docs/api-gateway.md

### S29 — Catgirl README
公开方案有显示层人格和工具裁剪；不据其自评推断Asuna角色能力。

https://raw.githubusercontent.com/Freakz2z/dsh-catgirl-plugin/main/README.md

### S30 — Catgirl client registration
覆盖assistant-step；只研究插槽用法，不照搬全局shadow。

https://raw.githubusercontent.com/Freakz2z/dsh-catgirl-plugin/main/client/src/client/index.tsx

### S31 — Catgirl external bundle build
外部包按lazy-CJS输出并external共享React，示例而非本机兼容已验证。

https://raw.githubusercontent.com/Freakz2z/dsh-catgirl-plugin/main/client/tsdown.config.ts

### S32 — Native prompt prefix 常量
真实的 `PERSONA_PREFIX_SECTION` 与 `getSectionOrder` 从公开root导出；示例以scoped注册覆盖全局persona而非叠加另一位助手身份。

https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/dsh-v0.1.5-rc.2/packages/core/system-prompt/src/index.ts

## 可维护性结论

公开接口/原生UI能显著缩小Asuna的兼容面，但DSH明确仍是developer preview，不能保证任意后续版本无需适配。将DSH依赖接线集中在Core，不让小满的role/skills到处import内部类型；先固定本机版本，未来明确升级时才检查变化的接口与一条实际路径，不每日A/B。
