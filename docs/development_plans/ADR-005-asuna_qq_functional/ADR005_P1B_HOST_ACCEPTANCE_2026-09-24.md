# ADR-005 P1-b 宿主接入验收记录（2026-09-24）

依据：`ADR005_P1B_HOST_INTEGRATION_DECISION.md`。本记录是操作员的环境、发布与正式 Web 观察记录；P1-b 产品代码、宿主接线、测试和使用说明均由小满编写。

## 交付和隔离检查

- 给小满的脱敏当前宿主副本：`/task/asuna-host-p1b/`，含当前有效 P1-a 身份模块与实际宿主接口；没有生产连接凭据、聊天库、运行历史或 Git 历史。隔离入口说明为副本内的 `P1B_TEST_ENTRY.md`。
- 隔离宿主使用同一产品实现、独立受限 Mongo 库 `asuna_v2_test_p1b_host_20260924`、独立 DSH 目录；测试账户仅有该库的读写权限。QQ 收发、生产 outbox 与计划未在隔离宿主启动。
- 小满的最终统一补丁冻结为 `.runtime/p1b-isolation/submission-v5.patch`，SHA-256 为 `813da2c5edfa452b95e846513dbfdcd02fd3a613563cddf198cdd63711e3df9d`。产品改动是 `history_query.py`、`application.py`、`context.py`、`tasks.py`、`test_history_query.py` 和 `P1B_HOST_INTEGRATION_USAGE.md`。现有 `peer_context.py` 保持原值，SHA-256 为 `03ccdcdd1c7ad3c8de3582c0269e1f7b607e0eac07ea10ea12cb0f067014137d`。
- 最终补丁在受限隔离宿主的 `tests/test_history_query.py` 结果：13 passed，0 failed；125 条 `datetime.utcnow()` 弃用警告。日志在忽略提交的 `.runtime/p1b-isolation/pytest-v5.log`。夹具清理后没有遗留 READY 任务、消息或场景。
- 隔离 Web 用现有入口写入一条原始入站消息，再作自然语言查询。角色经实际 `query_authorized_history` 工具找回原文，显示记录作者、`messages.occurred_at`、`scene_seq` 和消息 ID；未把自己的出站复述作为用户原话。此项是隔离 Web 验证，不是 REAL_QQ。

## 正式宿主启用和原问题复查

重载前核对了实时任务、反馈队列和运行状态，并保存四个已有源码文件的本次基线到忽略提交的 `.runtime/p1b-isolation/production-baseline-v5/`。随后按现有 Web 维护入口停止原服务，将上述冻结补丁机械应用到当前宿主。六个产品文件与隔离验收版本逐字节一致；P1-a 身份模块未改。通过 `start-asuna.cmd --port 8767` 重载，正式 Web 再次可用。

2026-09-24 16:50（NZ）在正式 Web 输入自然语言复测，要求以原“雾灯”提问的实际保存时间 `2026-09-23T23:08:36.891626+00:00`、`scene_seq=265` 为严格边界，查找该边界之前本人说过且正文含“雾灯”的完整原话，排除边界提问、后续测试和小满自己的回复，并列出作者、实际时间来源、序列及消息 ID。输入未包含操作者已知的四条答案或其 ID。

正式执行任务 `task-ep-0063b5a9ed995a972fba9d5d2e39a235` 经现有 ToolBroker 两次调用 `query_authorized_history`。首次以 `person=local-user`、`query=雾灯`、上述 `until` 和 `limit=50` 查询；第二次将窗口扩到 90 天。两次结果均 `degraded=false`、`more=false`、`next_cursor=null`。工具命中五条原始入站记录，其中一条是与 inclusive `until` 同时刻的边界提问（seq 265），角色按用户的严格边界明确排除；工具也记录一条非该作者的命中被人物过滤。第二次兜底扫描 `exhausted=true`，窗口从 2026-06-26 起。本机场景数据库中最早入站记录为 2026-09-20，203 条入站记录均有 `occurred_at`，故该窗口覆盖当前保存的本机场景入站史。

Web 的工具结果直接显示四条边界前记录的原文、`author=local-user`、`direction=inbound`、`time_source=messages.occurred_at`、`verbatim=true` 和以下定位：

| scene_seq | UTC 时间 | 消息 ID |
|---:|---|---|
| 46 | 2026-09-20T05:39:53.917423+00:00 | `in-ep-1c966c4961d6338decfaeedbe1850dee` |
| 80 | 2026-09-20T05:50:24.791864+00:00 | `in-ep-d179721239bf2fcd4b0c1c762c7ac5a7` |
| 82 | 2026-09-20T05:52:24.667087+00:00 | `in-ep-17537fe12d77184c3f4129619001f47c` |
| 84 | 2026-09-20T05:53:42.838297+00:00 | `in-ep-0275fa58b4e98917e91f8cd6ebf72ab9` |

2026-09-24 16:53（NZ），小满在正式 Web 的 `SPEAK` 已送达答复：边界之前共四条本人原话，逐条给出完整文本、时间、序列和消息 ID，说明时间来源为 `occurred_at`，排除 seq 265 和自己的回复，且没有续页。Web 中可以展开两次工具结果直接回读原文和上述来源。为避免把本机私人谈话全文再复制进源码仓库，本记录只列定位；原文保留在既有正式 Web 记录中。

此项是**正式 Web 原问题复查通过**，不是原失败的自动恢复，也不代表已做 REAL_QQ 历史查询。未主动发送 QQ 群测试消息；普通 QQ 的权限和授权范围未扩大。当前不存在需架构师裁定的 P1-b 阻塞。
