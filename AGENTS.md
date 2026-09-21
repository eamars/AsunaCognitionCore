# Asuna 开发与交互入口

- 正式交互、功能开发的运行观察、调试呈现和交互验收统一通过现有 Web UI；浏览器可用时优先使用 in-app browser，真实操作页面并检查可见结果与执行详情。
- 默认入口为 `start-asuna.cmd`（`start-asuna-ui.cmd` 是同一入口的别名），运行 `asuna ui`。不得调用终端聊天、用 stdin 注入自然语言或用 `asuna run` 代替 Web 交互验收；Web 出错时修复 Web，不自动回退 CLI。
- CLI 只保留显式 `--debug` 的故障诊断/维护用途。Shell 可用于源码编辑、启动/停止宿主和必要的非交互诊断；这些结果不能代替 Web 验收。不要为验证入口防护而启动真实终端聊天或调用模型。
- `chat.py` 的 `Chat` 是 Web 复用的队列/行动控制器；`chat()` 与 `terminal()` 才是 debug 终端适配器。Web 不调用这两个函数，也不加载终端输入依赖。
- UI Elements V1 从 `docs/development_plans/ADR-004-asuna_ui_elements_v1_kit/CODEX_START.md` 进入，遵守同目录 `STRICT_BOUNDARIES.md`，满足 `ACCEPTANCE.md` 后停止扩展。优先复用 DSH 插件，保持三栏浅色工作台，不重构产品或后端。
- ADR-003 中旧的终端客户端指示受上述入口规则取代；其 QQ/定时器计划不因本次 UI 或入口调整自动进入实施。历史 CLI 证据保留为历史，不作为当前使用说明。
- 角色脑和行动脑是职责，不是模型名称。两条路由独立配置，允许同一模型/服务；UI 标签、兼容协议、推理和 token 计数均不得按职责硬编码特定模型。模型名称只来自配置或实际回执，历史文档中的部署名不约束后续选择。
- 正文英文可使用中文字体附带的英文字形，不要求单独加载英文字体；行内代码、代码块、JSON、工具 payload 和代码编辑区必须使用统一等宽字体栈。
