# 架构裁定：ADR-007 publish/restart lifecycle

本问题是 ADR-007 publish/restart lifecycle 的可用性问题，不是 A2 功能错误，也不是 boot_probe 覆盖不足。

严重度：High availability / self-development liveness。无数据损坏证据，但一次自主发布导致约 15 分钟不可预测等待，并可能要求浏览器手工刷新，不适合作为 resident agent 的长期行为。

一、不要修改 boot_probe 范围。

boot_probe 继续只验证 minimum logic-core survivability。不要启动完整 RuntimeHost、channels、Web 或模型完整 cold start，不要把 live readiness 变成 publish 前第二次完整启动。

二、publish 后的 restart 等待改为“只等 in-flight，不等 durable queue 排空”。

APPLIED 后立即标记 restart_pending。

- 当前正在执行的 action/role turn 不强杀；
- queued task/input 已持久化，不需要成为 restart blocker；
- restart_pending 后不要再开始新的 action work；
- 当前 in-flight work 结束后即可请求 restart；
- queued work 由新 RuntimeHost 的现有 recovery 继续；
- 不增加固定 timeout、取消任务或最大等待时间。

restart 条件除了 role turn finished 外，必须在 active action task 结束时重新判断。不要要求再发生一个无关的新聊天回合才触发 restart。

三、正常 self-publish 不再重启整个 Web shell。

目标生命周期：

long-lived asuna ui / DSH Web / UiBridge
↓
replaceable RuntimeHost

RuntimeHost restart 时：

- Web 8765 保持可访问；
- 浏览器现有页面不失效；
- 显示一个最小 runtime state：restarting；
- 第一版可令 canSend=false；
- RuntimeHost ready 后 Workbench/bridge 重新绑定；
- 页面自行重新读取 state，不要求 F5。

不要为此建立第二个 supervisor 服务、HA 系统或新 Web server。

start-asuna.cmd 的 exit-code-75 整进程重启不再作为正常 development_publish 的 activation 路径；可以继续保留为真正的 process-level/fatal maintenance 路径。

四、先增加最小阶段 timing，再优化 cold start。

只增加 existing evidence/log events：

restart.pending
restart.blocked（active_task、pending/task queue 数）
restart.requested
host.stop.started / finished
host.start.started
lane.character.start / ready
lane.executor.start / ready
lane.summary.start / ready
host.recovery.start / ready
host.channels.ready
host.integration.ready
host.schedule.ready
runtime.ready
web.ready

不要建设 metrics framework。用一次正常 publish/restart 得到时间分解即可。

五、summary lane 不应天然成为 foreground Web readiness 必需条件。

当前固定版上一版本顺序启动 character → executor → summary，而 summary 本身是 low-priority 功能。

本轮先用 timing 确认。如果 summary 是明显延迟来源，将 summary/indexer 初始化移到 foreground runtime ready 之后。如果其它阶段占主要延迟，只修实际最大的阶段。不要未经证据就同时并发化所有 lane。

六、A2 保持不动。

不要修改 linked-scene 语义、identity alias、history/retrieval、QQ route 或 publication 来解决本问题。

七、UI“正在读取对话”问题按 lifecycle 修，不做刷新补丁。

不要用：

- 自动 location.reload 定时器
- 失败几秒后强制刷新
- restart 后浏览器脚本 reload hack

来掩盖 Web process 被完整重启的问题。

八、最小验收：

1. development_publish 期间不杀正在执行的 action；
2. queued durable work 不再阻止 restart，restart 后仍可恢复；
3. Web 页面在 RuntimeHost restart 全程仍可访问；
4. 页面明确显示 restarting / ready，不需人工刷新；
5. 新 RuntimeHost ready 后原页面继续工作；
6. 一次 startup timing 能明确说明主要延迟所在；
7. A2 的 local-dm ↔ owner QQ DM continuity 在 restart 后仍正常。

不要重复多轮 benchmark，不做裸 DSH A/B，不重验 ADR-005 全集。

完成上述 lifecycle 修复及一次真实确认后停止。
