# 给本地 Codex 的执行指令

按本包从零实现 `asuna-ai-cognition-core` 的 V1。先读 README 及 docs/01–06；以 docs/04 和 `fixtures/acceptance_cases.json` 为验收合同。不要先写一个新的通用 harness。

## 必须先做

- 建立独立仓库、独立 DSH_HOME、独立工作目录与 Asuna MongoDB 数据库。不得改动已运行的 Kazusa/小满实例、默认 DSH profile、现有模型启动参数或旧数据库。
- 只从旧项目的本地有效环境中读取 MongoDB 与 embedding 连接配置。不要执行/导入旧应用读取配置，不要 `source` 未审查 shell 文件，不要输出凭据。公开仓库的 localhost/mongo URI 只是样例，不是已核实地址。
- 输出 `environment.json` 与 `integration_probe.md`。固定 DSH executable/version/commit、插件依赖、模型权重/量化/MTP/template 和 sampling。用户指定 qwen3.8 flash 与 gemma4 26B；262k 是待确认的部署上限，不允许仅修改 client 元数据冒充服务端已支持。
- 完成阶段 0 探针后再大量开发。优先 Python + 薄 TS；真实 SDK 缺口要记录，不能虚构接口。必须保留可替换 DSH adapter 边界。

## 执行原则

1. 无工具的角色阶段也必须能完整运行：monologue 是独立模型输出，speak 是后续输出，程序推进阶段。Gemma 的 stop 只结束当前阶段。
2. 工具、进程和模型调用全部本地。辅助标题、压缩、embedding、评分也不能暗用云模型。
3. 角色读到的人格/关系/记忆必须有实际请求证据。仅检查文件存在不算加载成功。
4. 不允许 Qwen 改写角色 monologue 或润色 Gemma 的公开回复；不允许 Qwen 绕过发布服务。
5. 自动维护与每轮情绪脚本不在角色必经路径。V1 不接真实摄像头、设备或群消息发送。使用 CLI 场景模拟器、受控文件任务和可审计消息接收器；它们必须走同一正式路由，不得另写演示捷径。
6. 人格与记忆可写，程序管理来源、scope、版本与并发。角色可决定新内容，但不能改 ACL、工具权限、审计开关、模型路由、测试阈值或真值夹具。
7. 每个阶段有独立提交、测试及报告。允许修 bug 后重测；必须保留所有失败 attempt，不能只展示最好输出。
8. 先冻结实验配置和夹具 hash，再运行正式评估。修改人设/评分阈值/模型配置后使用新 experiment_id，不覆盖旧结果。
9. 没有自然语言评分的人工复核时，COGNITION 只能 INCONCLUSIVE，不能让演员自评或者让同一个 Qwen 单独宣布成功。
10. 报告任何范围缩减。包括：未跑真实 196k 长上下文、仅做 mock compaction、向量索引未 READY、不能捕获最终 provider request、沙箱无法隔离凭据等。

## 最终提交

可运行仓库、锁文件、启动说明、数据库 migration、完整测试、审计 CLI/静态 HTML、脱敏 evidence.zip、`report.json` 和 `report.md`。使用 `reports/report.template.json` 的结构，逐项引用测试 ID、artifact path、hash、命令与 exit code。包含一个反例和一个正常 trace。

不把“没有异常”当作“角色没有被稀释”。首先证明工程边界，再证明两个真实模型在固定实验中的行为质量。
