# ADR-003 D：原生定时计划与成长实测

2026-09-23。C 的已知 QQ 入站提及、出站真实提及和回复归属缺口修复后，按 V2.2 顺序进入 D。角色咨询保持可选；调度与它没有固定交替关系。

## 接线

固定版 DSH `0.1.5-rc.2` 的 `@deepseek-ai/dsh-schedule` 负责创建、持久保存、计时和 dispatch。单独的 native schedule root 只持有原生 session，不发模型请求。到期 `source.kind=plugin, plugin=schedule` 由该 root 的 `agent/pre-step` 接住；原生 dispatch 先 flush，再通过 localhost token 回调宿主，返回 `reject`，不让调度 root 自己生成回复。Python 宿主只记录 plan 的原场景、人物、权限 epoch、创建时集成授权与原生 schedule ID，并把可信到期事件送进现有 Chat/Router/Coordinator 队列。没有第二个时间轮或轮询到期表。

宿主重启时重新打开同一个原生调度 session，回读 `schedule/change`，按原生 dispatch seq 恢复未送达的 occurrence。同一 event_id 的宿主输入持久去重；固定间隔使用最后处理的 seq 避免旧 dispatch 重放。到期前重新核对原人物、场景、epoch 和群路由；创建时集成授权仅在当前 profile 仍允许时带入。取消使用原生 `schedule_delete`。角色 DECIDE 仅新增可选 `schedule` 或 `cancel_plan_id` 字段：计划登记、到期排队和实际改善有不同记录，不能互相冒充。

## 早期运行探针

- 安装版 schedule 记录 API：一次性 120 秒、固定间隔 300 秒、原生 create/dispatch fold 通过；未把此纯数据探针当作真实到期。
- 独立 native DSH 进程创建 2 秒计划后，实际出现 `schedule/change` create 与 dispatch、宿主回调一次，调度 root provider requests **0**；证据 `reports/schedule-native-probe-*`。
- 宿主服务探针：回调后同场景原文只持久接收一次，plan 从 ACTIVE → FIRED；证据 `reports/schedule-host-probe-*`。
- 创建计划后关闭并恢复原生调度进程：到期后仍只持久接收一条，模型请求 **0**；证据 `reports/schedule-restart-before-*`、`reports/schedule-restart-after-*`。
- 将源场景 policy epoch 变更后到期：原生 dispatch 仍记录，宿主标 `SCHEDULE_POLICY_STALE`，没有把事件交给角色；证据 `reports/schedule-revoke-*`。

## 正式 Web 两分钟观察

本机 Web 以 owner 集成授权提出「两分钟后从最近 QQ 麻烦中自己选一件值得改善的事再判断，不立刻开工」。角色 episode `ep-34f5ce7406664da24e589e404c007679` 真实选择 `schedule:{intent:"决定是否通过 adapter 层核实平台真实渲染状态，而非仅依赖 retcode=0",after_seconds:120}`；宿主保存 `plan-34f5ce7406664da24e589e404c007679`，原生 `schedule-1`，目标时间 2026-09-23 09:13:28.679 UTC。

无人追加输入时，原生 dispatch seq 2 到期，plan `FIRED / ENQUEUED`；宿主接收唯一 `episode_kind=scheduled` 输入 `in-ep-7bf7be617905a363ca5ac6235cfdcdb7`。角色到期后选择先核实 `get_msg` 读取自身已发送消息的可行性和现有授权，没有把计时完成当成改进完成。行动任务 `task-ep-7bf7be617905a363ca5ac6235cfdcdb7` 的实际结果与后续是否改进仍待核对。因此目前 **N7 一次无外部输入触发已验证；N8 实际改善未验证**。

固定间隔创建／取消、QQ 客户端真实提醒显示、完整 N8 改进与重启后复用分别保留为待验项，不用上面的探针或计划文本代替。

## 2026-09-23 后续：反馈断点与固定间隔取消

上述定时行动 `RETURNED` 后，原反馈在角色 `MONOLOGUE` 因窗口只剩 30 输出 token 而 `max-tokens`，宿主原先把它停在 `FAILED_PROTOCOL`。按架构师裁定修正原反馈消费接线并定点续接后，同一 feedback episode 由原角色会话完成；角色因人工路径已先行完成并公开汇报，选择 `silent`，没有重复发布或重跑行动。人工路径的 adapter 0.2.3 改进不追认为定时计划的自主成长。真实错误、预算、接线和验证见 [行动反馈连续性报告](ADR003-FEEDBACK-CONTINUITY-REPORT.md)。

本机 Web 另创建 300 秒原生固定间隔计划，并在到期前明确取消；宿主计划 `plan-a0329d52e7782a90efd31a22b533e604` 为 `CANCELLED`，原生 DSH `schedule/change` 有 `schedule-2` create seq 7、delete seq 8。因此固定间隔创建和取消已验证；不把未实际到期的间隔轮次算作触发。N8 的实际自主改善、首次新版自然群出站读回、QQ 客户端提醒显示及改进后的重启复用仍待验。
