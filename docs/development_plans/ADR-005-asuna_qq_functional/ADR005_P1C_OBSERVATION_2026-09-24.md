# ADR-005 P1-c｜开发观察与宿主验收边界

2026-09-24 18:55（Pacific/Auckland）。本记录是 Codex 的只读审阅和离线复核，不是 P1-c 交付验收。

## 当前状态

- 小满在隔离开发域 `/task/asuna-host-p1b` 编写按需群讨论整理、宿主 ToolBroker 接线、测试和说明，提交 `/task/P1C_HOST_INTEGRATION.patch`。本机对应副本为 `.runtime/integration/owner/development/asuna-host-p1b/`，补丁为 `.runtime/integration/owner/development/P1C_HOST_INTEGRATION.patch`。
- 补丁只涉及 `discussion_digest.py`、现有 Application/Context/Tasks 接线、P1-c 定向测试与说明；P1-a 身份模块和 P1-b `history_query.py` 未被补丁覆盖。Codex 未编写或修改产品源码、测试或模型提示词。
- 当前正式宿主仍加载已验收的 P1-b；P1-c 补丁尚未应用、重载或经正式 Web/QQ 验收。

## 可核对的结果

- Codex 在小满开发副本执行 `tools/p1c_offline_check.py`：18/18 通过。这是离线假集合检查，不是 Mongo 宿主检查。
- Codex 独立复现：主题“雾灯”的首条与不重复主题词的 reply 更正均进入整理；两条同主题消息以 `limit=1` 续页无重复；11 条 reply 链先返回 m1–m9 并给续页，再返回 m10–m11 且末页标完整；指定 A 的发言为种子时，B 的链内更正标 `person_match=false`，覆盖字段记 1 条他人上下文。
- 在当前 P1-b 工作树对该补丁运行 `git apply --check` 成功。此命令只检查可应用性，没有应用补丁。
- 小满的使用说明列出 15 个待由操作员在受限 Mongo 隔离宿主执行的定向用例。当前没有这 15 个用例的操作员 stdout/stderr、受限测试配置和正式 Web 结果；角色回复中提到的“真实 Mongo 已跑通”不作为验收证据。

## 唯一下一步

按 `ADR005_P1B_HOST_INTEGRATION_DECISION.md` 的授权边界，P1-b 的宿主操作权不自动延伸到 P1-c。取得本次 P1-c 限定授权后，由 Codex 准备受限隔离 Mongo 配置并运行小满的 15 个宿主用例；失败交回小满原开发目标。通过后核对补丁快照，机械应用到现有宿主、必要维护重载，并通过正式 Web 的原角色/工具路径验收按需整理、覆盖与来源。没有授权前，正式宿主保持 P1-b。当前没有需要架构师裁定的真实技术阻塞。
