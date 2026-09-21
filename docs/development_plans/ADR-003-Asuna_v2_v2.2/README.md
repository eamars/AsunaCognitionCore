# Asuna V2.2 · NapCat 原生信息流与自主成长

2026-09-20。**这是基于最新 V1 交付记录制定的下一阶段任务包，不是已运行的 QQ 实现。**

2026-09-21 入口规则已修订：正式交互与后续开发验收统一使用 ADR-004 Web UI，CLI 仅限显式 debug。以 [CODEX_START.md](CODEX_START.md) 的入口修订覆盖本包旧终端客户端指示；本次修订不启动 QQ 等后续工作。

当前基线是 `asuna-v1-core-raw-20260920 (2).zip` 中的 `asuna_cognition_core_v2`。V1 已获得有限真实验证；不再退回重做 V1、旧 41 项验收或全模型矩阵。裸 DSH 小满的 `qq(1).zip` 仅提供错误案例与设计经验，不是 Asuna 的代码，也不直接移植。相同 Qwen 部署使其失误具有参考价值，但不证明不同上下文下一定重现。

## 从哪里开始

**Codex 只从 [CODEX_START.md](CODEX_START.md) 开始，按 [V2_2_PLAN.md](V2_2_PLAN.md) 顺序推进。**

| 阅读时机 | 文档 |
|---|---|
| 当前实施顺序 | [V2_2_PLAN.md](V2_2_PLAN.md) |
| 开发偏离、条件缺失与继续推进 | [STAGE_RECOVERY.md](STAGE_RECOVERY.md) |
| 接宿主输入、输出与权限 | [RUNTIME_SEAM.md](RUNTIME_SEAM.md) |
| 小满开始实际开发 QQ | [自然语言开发任务](tasks/ASK_XIAOMAN_BUILD_QQ.md) |
| 接定时器和自主活动 | [DSH_TIMERS_AND_GROWTH.md](DSH_TIMERS_AND_GROWTH.md) |
| 记忆与 Bonus 总结／偏好 | [MEMORY_AND_PREFERENCES.md](MEMORY_AND_PREFERENCES.md) |
| 当前步骤怎样验收 | [ACCEPTANCE_DIALOGUES.md](ACCEPTANCE_DIALOGUES.md) |
| 用户怎样实际使用 | [USER_GUIDE.md](USER_GUIDE.md) |
| 怎样交回结果 | [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) |
| 有疑问再查的证据 | [V1 核对](references/V1_EVIDENCE_REVIEW.md) · [原型教训](references/PROTOTYPE_LESSONS.md) · [DSH 原生接口](references/DSH_NATIVE_MAP.md) |

## 一句话目标

用户从 QQ 自然说话，进入同一个 Asuna 角色、记忆与行动回路；无人输入时，既有授权的自主计划能到期触发；原文、独白、实际发布和成长结果真实保存，跨用户不串台。

**先交付私聊可用，再扩展一个测试群，再验证定时成长；总结与偏好自动整理作为最后一段 Bonus，不拖住前面的可用交付。** 少量必要权限检查是多用户接入的正确性要求，不是重开安全平台工程。

## 重要配置事实

最新记录的角色模型是本机 **Gemma 31B、68,608 部署窗口、native_thinking=false**，不是早期计划的 Gemma 26B/262k。Qwen 与固定 DSH 版本沿用 V1。只核对当前实际值，不擅自切回旧模型。

用户允许 LAN 固定 token 和本地明文配置；不引入 Vault、OAuth、证书服务或频繁人工审批。`config/napcat.local.candidate.json` 含来自独立原型的连接候选，**不是已验证的 Asuna 连接或发送授权**。Codex 在本机确认一次，妥善保存在被 Git 忽略的配置中；不要把 token 放进角色提示词、聊天、技能正文或公开报告。

没有附带成品 NapCat adapter、虚构验收结果或旧私人聊天库。包内未连接你的服务、未运行模型、未修改 V1。
