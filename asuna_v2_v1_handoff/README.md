# Asuna v2 · V1 架构与 Codex 执行包

版本：1.0 · 2026-09-19 · 状态：设计交付，尚未在用户本地执行。

## 给执行者

这是一个新项目，不是 Kazusa 的迁移、兼容层或功能扩写。唯一需要参考旧项目的部署信息是 MongoDB/embedding 的有效连接配置；不得导入旧 cognition graph、恢复仪式、心情脚本或人物私密日志。人物基准由本包独立定义。

目标不是“工具助手的答案经过角色润色”，而是：**角色从可靠注入的人格、关系和经历形成意图；逻辑模型执行；角色理解现实反馈并发言。工具噪声不能通过上下文、压缩或记忆写回稀释人格。**

推荐实现：Python 控制与状态层 + 薄 TypeScript DSH 插件；两个长期驻留的 DSH lane，各自管理多个持久 session。Python SDK 不覆盖的能力经自定义、可测试的桥接接口暴露，不假设上游已有这些业务 API。SDK 接入阻塞时，允许转单一 TypeScript 控制层，但必须写 ADR，不能维护两套控制逻辑。

## 阅读顺序

1. `docs/01_ARCHITECTURE.md`：范围、职责、生命周期、隔离、人格演化。
2. `docs/02_DATABASE.md`：包括聊天记录的 MongoDB 方案、索引、检索、并发与删除。
3. `docs/03_IMPLEMENTATION.md`：本地发现、DSH 映射、仓库结构、分阶段执行与命令契约。
4. `docs/04_ACCEPTANCE.md`：可复现的验收流程、矩阵、指标、失败定义。
5. `docs/05_PERSONA_AND_EXPERIMENTS.md`：小满简版、反向人设、底模归因实验。
6. `docs/06_AUDIT_AND_REPORT.md`：逐步审计、重放与 Codex 回报。
7. `docs/07_ACCEPTANCE_CATALOG.md`：41项验收的逐项准备、操作、断言与证据要求。
8. `docs/90_SOURCES.md`：用户材料、已核对接口与仍待本地确认的事实。

配套资产：`prompts/`、`config/`、`schemas/`、`fixtures/`、`reports/`、`tools/`。

**先读 `CODEX_START.md` 再实施。** 不要求先拿到全部真实聊天历史；使用本包合成夹具即可独立开始。

## 本包能运行的内容

```bash
python tools/verify_bundle.py
python tools/check_report.py reports/report.template.json --allow-incomplete
```

另外 `tools/generate_distractors.py` 生成可复现的合成干扰记忆；不连接数据库。上述检查命令只验证文档包、夹具及报告格式，**不测试 DSH、MongoDB 或模型**。

所有 `asuna ...` 命令均是要求 Codex 实现的 CLI 契约，目前不是本包提供的可执行系统。禁止把文档包检查通过写成架构验收通过。

## 完成的含义

分别报告 `ENGINEERING`、`COGNITION`、`PERFORMANCE`、`LOCAL_DEPLOYMENT` 四项结论。模拟成功不能代替真模型成功；隐藏截断、云端回退、硬编码理想台词、跳过向量检索，都不能标记通过。可如实交付 FAIL / BLOCKED / NOT_RUN / INCONCLUSIVE；不确定项必须带复现材料与下一步最小实验。
