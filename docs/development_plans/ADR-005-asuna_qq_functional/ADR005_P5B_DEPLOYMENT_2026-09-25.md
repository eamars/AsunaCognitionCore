# ADR-005 P5 新群接入部署记录

2026-09-25（Pacific/Auckland），用户指定 QQ 群 `1124198125` 开启主动参与。小满在原任务中交付 `P5B_ONBOARD_GROUP_1124198125.patch`、宿主路由片段、adapter 配置补丁和自测说明；产品代码只改 `src/asuna/ui.py`，将 P5 程序拦下与角色选择沉默的 Web 状态分开。自测结果由小满报告，Codex 未增加独立产品验收。

Codex 在无 READY/RUNNING 任务的维护边界停止宿主，备份原配置与 UI 文件，机械应用补丁并只合并新群路由；原四条群路由和私聊路由保留。因 adapter profile 变化，按现有集成运行器执行显式 `integration_start`，再由 `start-asuna.cmd --port 8767` 重载宿主。重载后 adapter 健康记录显示 `group_routes=5`、QQ API 与事件连接均在线，正式 Web 场景列表出现群 `1124198125`。当前 P5 开关在 `1002866238`、`1124198125` 两群为开，另外三群为关。

以上确认配置和服务已生效；小满的 UI 修复、真实群互动观感与主动发言质量仍按实际使用观察，不把服务恢复写成这些产品效果已验收。备份位于忽略提交的 `.runtime/maintenance/p5b-1124198125-20260925/`。
