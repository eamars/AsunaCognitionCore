# asuna-ai-cognition-core

V1 本地认知协调器：Python 管状态、权限、检索和发布；薄 TypeScript 插件连接固定版本 DSH。Gemma 独立生成 `MONOLOGUE → DECIDE → SPEAK`，Qwen 只执行已冻结任务，结果回到 Gemma。模型的 `stop` 只结束当前阶段。

当前为实施与验收中的版本。阶段证据在 `reports/M0`–`M6a` 及各不可覆盖的 attempt 目录。**探针通过不代表完整 V1 通过**；最终结论以 `report.json` 的四个 gate 为准。没有独立人工盲评，COGNITION 保持 INCONCLUSIVE。

本仓库不会接 QQ、摄像头或真实设备。CLI 场景模拟器、受控文件任务和 Mongo 幂等消息接收器均走正式 Coordinator/TaskService/PublishService。公开视图仅显示已经送达的 SPEAK；operator 审计包含独白与 native reasoning，不能作为公众 API 暴露。

## 安装与启动

在本仓库根目录运行；需要 Python 3.12、uv、Node 24，以及已安装 Ubuntu/bubblewrap 的 WSL。仅使用项目本地的 DSH，不全局升级。已验证版本为 `0.1.5-rc.2`（上游 0.1.5 发布线），SDK 同 commit；详见 [ADR-001](docs/ADR-001-runtime.md)。

```powershell
$env:PYTHONIOENCODING = 'utf-8'
npm ci --ignore-scripts --no-audit --no-fund
uv sync --frozen
Copy-Item config/local.example.json config/local.json
# 在 local.json 填入本机 ROOT 下的独立 dsh_home/workdir 及有效本地连接。
.venv\Scripts\asuna.exe doctor
.venv\Scripts\asuna.exe db-init
.venv\Scripts\asuna.exe seed
.venv\Scripts\asuna.exe index
.venv\Scripts\asuna.exe run --scene dm-a --person A --text '小满，欢迎回来'
```

已有 `config/local.json` 时不要覆盖它。配置和凭据均被 git 忽略。环境发现只读取旧项目配置中的允许字段；不导入旧应用、不运行其启动脚本。数据库写入仅允许明确配置的新库和 `asuna_v2_test_` 前缀测试库。

`doctor` 只表示连通性和元数据探测；`index` 的 `ready=true` 才表示向量索引可查询。服务声明的 262144 上限与真实容量测试分开记录，不修改服务启动参数来配合测试。

## 常用操作

```powershell
# JSONL 每行必须有 event_id、scene_id、person_id、text。
# 群事件还需 mentioned=true / reply_to / scene_tick 才唤醒角色。
.venv\Scripts\asuna.exe run --events examples/scenes.jsonl

# workspace 必须在本仓库 .runtime/work 内，禁止挂载旧工程或凭据目录。
.venv\Scripts\asuna.exe run --scene dm-a --person A --text '读取任务目录的 START_HERE.md 并完成任务' --workspace .runtime/work/my-task
.venv\Scripts\asuna.exe compact --scene dm-a
# compact 排队到下一完整阶段边界，不会立即伪造摘要。
.venv\Scripts\asuna.exe reflect --scope scene:dm-a --entity relationship:A
.venv\Scripts\asuna.exe cancel TASK_ID
.venv\Scripts\asuna.exe inspect episode EP_ID --format html --out reports/episode.html
.venv\Scripts\asuna.exe inspect request CALL_ID --view provider
.venv\Scripts\asuna.exe inspect trace --format html --out reports/operator-audit.html
.venv\Scripts\asuna.exe replay reports/RUN/trace.json --database asuna_v2_test_replay_unique --mode state-only --deny-model-and-tools
```

`cancel` 是 operator CLI；服务内部按可信 requester 检查身份。`delete MEMORY_ID --operator` 会提高 scope epoch、使旧会话失效，并保守清理该 scope 的派生内容。只对合成测试库操作删除，或先明确接受其 scope 范围影响。它不撤回外部备份、已下载导出或 Git 历史；全局记忆删除当前会被拒绝。

## 测试和证据

验收合同保存在原始 [docs/04](asuna_v2_v1_handoff/docs/04_ACCEPTANCE.md) 和 [41 项夹具](asuna_v2_v1_handoff/fixtures/acceptance_cases.json)，没有改写阈值。

```powershell
.venv\Scripts\python.exe asuna_v2_v1_handoff/tools/verify_bundle.py
.venv\Scripts\python.exe tools/run_checks.py -q
.venv\Scripts\asuna.exe evaluate --test L01 --out reports/my-L01-unique
.venv\Scripts\asuna.exe evaluate --test A01 --out reports/my-A01-unique
.venv\Scripts\python.exe tools/run_acceptance.py L04
.venv\Scripts\python.exe tools/run_acceptance.py L03 --probe-count 1
.venv\Scripts\python.exe tools/run_acceptance.py F01
.venv\Scripts\asuna.exe report --out reports/my-report-unique.json
.venv\Scripts\asuna.exe export --out evidence-unique.zip
```

每轮创建新的 experiment_id，先写 manifest，再调用模型；同名输出目录会拒绝覆盖。所有失败与重试保留。`--probe-count` 是缩小的设计探针，不算正式验收。A01 生成匿名评审表与单独 operator 映射；模型或本代理的自评不能替代用户评分。

详细限制、测试命令与 exit code 见各 `result.json`。特别需要区分：真实 native compaction 与 mock、真实长输入与 metadata、向量命中与近期回读、收到模型文本与实际送达、状态重放与模型重跑。

## 部署边界

DSH home、工作目录和测试数据库均独立。DSH 子进程只收到必需环境变量；Qwen 工具在无网络 WSL/bubblewrap namespace 中执行，仅挂载 task 目录，不持有 Mongo 或发布凭据。真实模型请求经过固定本地路由代理，保存最终 HTTP body 和原始返回。Qwen 服务未暴露最终 OpenAI 渲染 token IDs，等价服务端 count 已与返回 usage 核对；该缺口仍会报告。

operator 授权过一次 Mongo 服务的 nofile 修复，证据见 `reports/M3.md` 与 `reports/search-diagnostics`：没有修改旧库数据或模型启动参数。当前进程软限制已提高，Compose 中持久配置需下次正式重建容器后生效；不要把普通 Docker restart 当作已应用新 Compose。
