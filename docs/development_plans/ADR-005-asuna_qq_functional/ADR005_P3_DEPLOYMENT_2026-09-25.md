# ADR-005 P3 部署记录

2026-09-25 00:30 左右（Pacific/Auckland），小满交付的 `P3_NL_SCHEDULE.patch` 已干净应用到现有宿主。通过 `start-asuna.cmd --port 8767` 完成维护重载，正式 Web 工作台恢复可打开。产品代码、测试和使用说明由小满编写；Codex 只做补丁应用与维护重载，没有另做产品验收。

小满报告离线自测 37/37 通过，覆盖新时间规则、创建/改期/取消/到期/恢复接线和角色可见计划投影。具体用法及边界见 [P3_NL_SCHEDULE_USAGE.md](P3_NL_SCHEDULE_USAGE.md)。她明确标出真 Mongo 测试尚未运行，以及原生 `/schedule/delete` 日志和 `/schedule/create` 回执字段仍待真实宿主确认。此次部署不把离线自测或 Web 恢复写成这些边界已验证。

P5 的主动参与开关随后已按用户选择在群 `1002866238` 启用，其他群关闭；P4 已移除。ADR-007 的开发目标待架构师交付。用户要求从 ADR-007 开始减少对小满的细项指示，并将真实数据与真实数据库交给她，Codex 不再为她的产品托底；相关现状见 [ADR007_ARCHITECT_HANDOFF_2026-09-24.md](ADR007_ARCHITECT_HANDOFF_2026-09-24.md)。
