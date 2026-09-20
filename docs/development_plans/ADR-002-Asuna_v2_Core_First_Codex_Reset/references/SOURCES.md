# 依据与证据边界

## A. 本包来自哪些已确认要求

来自用户本次对话的明确决定：Gemma 是确定性代码推进的有界角色主体；Qwen 是更自主的行动脑；两侧隔离工具噪声但共享必要的价值和意图；记忆、人设和技能可以成长。

用户最新的顺序：先人格化自然交流、记忆与双脑交互；然后复用 DSH/Qwen 的必要错误恢复；再验证工具、人设与记忆成长。用户还要求本机可用入口，以及潜在的由运行中 Asuna 自行开发 NapCat 接入的第二版任务。Codex 尚未开始执行上一轮纠偏。

因此，本包中的具体入口、阶段退出条件和职责划分是此次合并设计，不应伪装成已经运行的事实。

## B. 现有文件依据

- `Asuna_v2_Core_First_Codex_Reset.zip`，以及对应的 `CODEX_START.md`、`DEVELOPMENT_PLAN.md`、`CONVERSATION_CHECKS.md`、`REPORT_TEMPLATE.md`：保留核心优先原则，合并新的本机入口和 V2 任务。旧的七段对话保留，仅补充本次使用说明。
- 用户的 `evidence.zip`：上一轮对总报告、部分源码和轨迹的核对在本包 `EVIDENCE_REVIEW.md` 原样保存。它是历史分析，不是本轮重新运行本机后的结论。旧代码后来若改变，以实际工作树为准，不盲目恢复旧实现。
- 用户提供的 Qwen 冷启动和 Gemma 轨迹、人设资料：说明读取文件标题不等于加载人格、维护可延迟公开回应、先写“已说过”再发言会造成记忆错位。可核对原会话附件 `Pasted text(20260918-135315).txt` 等；本包不再复制含私密关系内容的完整原始日志。
- 简版小满测试卡在 `CONVERSATION_CHECKS.md`。它是为了验证的简化角色材料，不是完整旧人设的逐字迁移，更不包含旧私密日记、自检仪式或值班任务。

## C. 本轮核对的官方技术资料

检索／核对日期：2026-09-20。优先当前安装版本的本地文档；以下资料用于核对可用方向，不要求升级依赖。

### NapCat 网络配置 [N1]

`https://napneko.github.io/config/basic`

支持本文的窄事实：网络配置区分 HTTP服务端／客户端和 WebSocket服务端／客户端；WebUI管理端口与业务端口不是同一概念。本文不引用它的示例端口作为用户本机地址。

### NapCat 项目介绍 [N0]

`https://napneko.github.io/guide/napcat`

`https://github.com/NapNeko/NapCatQQ`

用于确认官方项目和文档来源。V2 优先对接公开协议，不复制或修改 NapCat 内部实现；需要第三方代码时遵循其实际许可，不把文档链接当作任意复制授权。

### OneBot 11 正向 WebSocket [N2]

`https://raw.githubusercontent.com/botuniverse/onebot-11/master/communication/ws.md`

用于 Qwen 实施时阅读传输、事件和请求返回约定。本文只要求按真实安装环境选择一条路径，并未提供一个已经写好的适配器。

### DSH core [D1]

`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/core.md`

本轮核对到当前上游包含消息入队、唤醒与上下文注入接口区分。用户已经有 DSH 接线，优先沿用固定版本；不能把本项目 `receive_message` 等建议名称当成 DSH 原生方法。

### DSH Python SDK [D2]

`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/python/sdk/README.md`

用于确认 Python 子进程桥接方向。它不意味着本地所有扩展已经暴露，也不需要因更新套件再做一轮 SDK 基准或全量迁移。

## D. 本包没有证明的事情

未访问用户实际运行主机，未连接其模型、MongoDB、NapCat、QQ账号；没有更改代码、重跑认知测试、登录或发送消息。`asuna chat`、`asuna serve`、slash命令和启动脚本是需本机交付的接口契约。

用户当前端点、凭据、测试QQ号、容器名、准确启动路径均未在本包臆造。正式交付时由 Codex／运行中的 Asuna 在授权范围内获取真实配置。

查验 Markdown、相对链接和 ZIP完整性只证明文档交付可用，不证明核心聊天、成长或QQ接通。
