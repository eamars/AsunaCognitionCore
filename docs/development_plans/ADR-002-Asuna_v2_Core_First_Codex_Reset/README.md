# Asuna · 本机入口与自主 QQ 接入开发套件

**套件修订 2.0｜2026-09-20｜实施指导，不是已安装的运行时。**

本包整合上一次“核心优先”纠偏包，以及之后确认的本机使用方式、成长属性与 NapCat QQ 第二版任务。用户说明 Codex 尚未开始执行这一轮纠偏，因此直接使用本包，不需要先执行旧包再升级。

现有 `asuna_cognition_core_v2` 的代码、MongoDB、DSH 接线和有效证据继续复用。不是重建项目，也不是回到 Kazusa 架构。既有源码问题以本地当前工作树核对为准。

## 只记住这条交付路线

**V1：先让用户在本机持续聊天 → 聊天中自然执行任务 → 新记忆真正影响以后 → 最小异常恢复 → 基础成长。**

**V2：用户在这个已可用的入口提出愿望，由运行中的 Asuna／Qwen 自己开发 NapCat QQ 适配器。Codex 提供必要接入点，不代写适配器。**

V2 是明确保留、按用户启动的后续任务，不得提前抢占 V1，也不能把成长整体推迟到 V2。V1 核心刚可用就交给用户试聊，不等后续任务全部完成。

## 从哪里开始

| 读者／时机 | 文件 |
|---|---|
| Codex 开始动手，只先读此入口 | [CODEX_START.md](CODEX_START.md) |
| 当前阶段的精确开发顺序 | [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) |
| 本机入口的行为与实现要求 | [LOCAL_ENTRY.md](LOCAL_ENTRY.md) |
| 用户如何开始使用 | [USER_GUIDE.md](USER_GUIDE.md) |
| 七段自然语言验收，沿用核心优先方案 | [CONVERSATION_CHECKS.md](CONVERSATION_CHECKS.md) |
| V2 之前需要的薄接入位置 | [CHANNEL_SEAM.md](CHANNEL_SEAM.md) |
| V2 自主开发 QQ 的职责与验收 | [V2_NAPCAT_TASK.md](V2_NAPCAT_TASK.md) |
| 用户到时发给 Asuna 的任务原话 | [tasks/ASK_ASUNA_TO_BUILD_QQ.md](tasks/ASK_ASUNA_TO_BUILD_QQ.md) |
| Codex 交回实机启动方法时填写 | [templates/RUN_ASUNA.template.md](templates/RUN_ASUNA.template.md) |
| 每次短回报 | [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) |
| 证据来源、版本与已知限制 | [references/SOURCES.md](references/SOURCES.md) |
| 需要定位旧缺口时才读 | [references/EVIDENCE_REVIEW.md](references/EVIDENCE_REVIEW.md) |

`asuna chat`、`/trace` 和 V2 的服务命令在本包中是**要求交付的接口**，不是声明本机现在已经存在。Codex 必须交回实际跑通的启动命令及启动脚本，不能只把这些名字抄进报告。

## 本次明确替代什么

本包替代此前套件的执行入口、优先级和首轮交付要求。旧 41 项合同、264 组归因矩阵、容量测试、哈希流水线、已撤回的 `V1_FEASIBILITY_SCOPE.md` 都不再是当前开发队列。已经存在的记录不删除，真实通过的底层能力不重复证明。

不附 NapCat 成品实现，不附假对话，不预写“学会了”的数据库记录。当前没有连接用户本机模型、MongoDB、DSH 或 QQ；本包不声称任何产品验收已经通过。
