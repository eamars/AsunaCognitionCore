# 最新 V1 证据核对：保留成果，定位 QQ 接入缺口

## 证据边界

本轮基线是用户上传的 `asuna-v1-core-raw-20260920 (2).zip`。ZIP 内源码根为 `asuna-v1-core-raw-20260920/asuna_cognition_core_v2/`；以下路径相对该根。已静态检查关键 Python／TS 代码、最终交付报告、分阶段报告，并核对 P3-A/B、P3-C、P1-D/P2 的代表性验证记录；没有运行用户代码、连接模型、QQ 或 Mongo，也没有重做 V1 验收。

报告中的 verified 是开发者记录的有限实跑结果；本文指出哪些结果有相应轨迹，哪些仍有局限。原始 `_delivery/manifest.json` 对应裁剪前完整交付，不能用它认定本次上传仍包含 `.runtime` 或二进制依赖。用户已说明删去了这些内容；本轮不把裁剪当实现缺失。

独立 `qq(1).zip` 不是本项目源码。它与行动脑使用同类本地 Qwen 部署，因此提供合理的错误模式参考；不能从同模型推导每个缺陷必定在本项目重现。

## V1 已经成立到哪里

| 观察 | 证据位置与限制 | V2.2 的处理 |
|---|---|---|
| 最终状态为 `CORE_FLOW_VERIFIED_WITH_LIMITATIONS`，不是早期核心整体未成立 | `reports/final-v1-20260920/result.json`：`status`、`stages`、`limitations`；`docs/V1-FINAL-DELIVERY.md` | 不重启旧验收项目，保留本机入口与模型组合 |
| 当前角色已换 Gemma31B，窗口68,608，native_thinking关闭 | 最终报告 `character`、`limitations`；`config/local.json` | 不回退早期Gemma26B/262k；Qwen沿用实际配置 |
| 已有 Windows 本机入口 | `RUN_ASUNA.md`；最终报告 `startup` = `C:\workspace\asuna_cognition_core_v2\start-asuna.cmd` | 新增宿主生命期，保留入口体验，真实启动方法由Codex在本机填写 |
| 聊天期间可以推进自主行动，任务错误由原Qwen处理 | `docs/P1-B-REPORT.md`、`docs/P2-REPORT.md`、`reports/p1d-p2-verification-20260920.json` | 不再让Codex替行动脑改任务文件；仅补网络／长运行条件 |
| 技能确由运行中的Qwen开发，并在恢复后通过native `skill` 调用 | `docs/P3-AB-REPORT.md`；`reports/p3-ab-verification-20260920.json` 的任务与 `native_skill_audits` | 保留已有DSH skill目录、loader与watcher，不另造技能市场 |
| 关系理解已经产生真实版本更新，恢复后影响回答 | `docs/P3-C-REPORT.md`；`reports/p3c-verification-20260920.json` 中输入、REFLECT、更新后关系和后续公开内容 | 把这一通路扩展到新QQ身份／场景；不是从零建“记忆可写” |
| 原生手动压缩曾在Qwen任务期间完成，任务仍返回原场景 | `docs/P1-D-REPORT.md`；`reports/p1d-p2-verification-20260920.json` 的 compaction 与结果事件 | 延续独立周期；增加一个适合长度的真实自动触发，不重复长容量矩阵 |

### 两段特别有意义的实跑经验

P3-A/B 报告区分了两次指令：最初“自行琢磨…工具化”只得到 SPEAK，没有实际委托；随后“现在动手实现并试用”才产生任务与代码。验收不能把愿望当完成。Qwen 实际遇到长命令、数据结构与临时目录等问题并继续修复；Codex不应以零错误作为自主开发门槛。

P3-C 记录了用户要求“先给结论、细节以后再问”的反馈，Gemma 形成并提交新的关系理解，后续同一人得到简短结论，另一人没有继承全部私人状态。它证明一次有限变化和隔离，不证明所有关系语义均正确，也不证明全球人格已自动进化。

## 当前代码对 V2.2 的直接影响

### E1：常驻的是终端，尚不是供通道共享的宿主

`src/asuna/chat.py:52–110` 的现有 worker／task 队列值得复用；`120–126` 的输入排队不等于Mongo已经收到原始消息；`128–201` 串起角色与任务反馈。`296–325` 的退出会取消本实例任务，`369–378` 将 Application 与终端放在同一生命周期。

V2.2 需要最小提取这些已工作代码：宿主持有 Application、按场景消费事件，终端只订阅／提交。不是在外层再套一个会逐条启动旧CLI的HTTP接口。

### E2：输入保存目前晚于上下文准备

`src/asuna/coordinator.py:35–53` 中，`context.prepare` 先于原消息写入。对于网络收件，一次embedding或记忆读取故障不应该让已收到的QQ内容消失。先可信归类和持久保存，再调用上下文与模型；恢复只重排尚未完成的事件，避免重复插入。

`src/asuna/router.py:29–44` 仍包含用于本机探针的 `fixture` 适配器标记与简化唤醒。不能接收客户端自报的scope、内部来源或任意回复ID后直接按管理员消息处理。

### E3：本地“已送达”不是平台“已接受”

`src/asuna/publish.py:18–46` 约束角色作者／SPEAK阶段并检查当前scope等，随后以本地 `sink_receipts` 模拟效果并标记送达。这条路径对V1本机有限验证有用，不能直接充当QQ网络回执。

新通道要区分生成、待发送、平台接受、失败、结果未知；实际 OneBot 返回的 message_id 与本次发送关联。平台接受不是对方已读。已发送但回执不明时，不靠重新生成角色回复来修复。

### E4：普通任务沙箱不能承载网络适配器开发和常驻运行

`src/asuna/sandbox.py:23–25、58` 等位置限定命令大小、约30秒、bubblewrap `--unshare-all`、临时 `/tmp` 和有限资源；`/task` 与授权 `/skills` 是持久写入位置。`docs/P3-AB-REPORT.md` 已记录 `/tmp` 内容在后续调用消失的任务经验。

这是隔离普通任务的有效基础。不能直接把所有任务改成宿主无限权限来让QQ连接成功。补一个仅用于已授权集成任务的开发／试运行入口，并由宿主管理部署程序；普通群请求不获得它的连接配置与部署写权限。

### E5：技能发现已经是原生能力，不应再作为未完成的“大重构”

`src/asuna/dsh_lane.py:86–109` 已加载native filesystem skill roots，`dsh-plugin/runtime-v2.ts:50–71` 按执行侧保留skill工具并提供complete PromptSection。`src/asuna/skills.py:6–16` 则将目录绑定到已配置的本机人物／场景。

QQ接入要将授权owner新场景正确映射到可见技能，并为群范围提供适合的可用集合；不能只把全部现有目录向每位群友开放，也不能因为原来的 `local-dm` 限制而让新QQ场景完全不知道已有能力。

### E6：记忆已经接上，但工作器仍绑定一个场景

`src/asuna/memory.py:79–105` 已按Unicode分块并保存长消息，不再是旧证据里超过900字节直接跳过的实现。`src/asuna/memory_indexer.py:13、24–40` 则围绕一个配置scene循环。

需要扩展为实际入站／完成事件触发的dirty-scope处理，而不是为每个群建立不断扫描全库的模型或工作进程。保留原文来源身份，以及 monologue ≠ human fact 的区别。

### E7：当前检索已经有scope过滤；仍有容量和投影细节需留意

`src/asuna/retrieval.py:78–105、130` 使用请求scope与明确global-safe记录，并对结果重新核对。因此，不能把独立原型的“全库扫描仅同群加分”缺陷归到当前Asuna。

但 `84–85` 的4096记录上限会使累积后的正常群聊触发 `LEXICAL_SCOPE_LIMIT`；应当在既有授权范围内限制词法候选并复用向量查询，不能因为记录多就关闭范围检查。`src/asuna/context.py:24–41` 的近期消息、检索结果和任务投影还需要保留真实发言者／出处，避免总结归属混淆。

### E8：定时器不是打开插件就能运行

`dsh-plugin/runtime-v2.ts:29–32` 在没有owned operation时抛出 `UNOWNED_LANE_GENERATION`。这可以防止旁路生成，但native Schedule到期会进入其原agent的followup，不能简单开启后期待它自动走Python Coordinator。

在模型请求之前区分真正的schedule事件，把它交给宿主计划事件流；普通未知生成仍拦截。具体接法见本包定时器章节，固定版本接口需实测一次，不整体关闭检查。

### E9：自动压缩仍未验证；现有摘要已经有具体错误

`src/asuna/dsh_lane.py:96–100` 配置 `auto:false`、`maxOverflowRetries:0`；运行桥提供手动compact并等待flush。P1-D验证了手动压缩，但原文指出摘要中出现偏好归属与引用错误。不能从“shadowed tokens有数值”推导“角色总结完全正确”。

应修数据投影和来源保留，新增一次真实阈值触发的有限检查。原始信息保存、摘要保存、检索可用和回答使用分别看，不新建全局评分流程。

## 当前原型安全经验怎样用于新阶段

相同本地Qwen可能继续写出作用域比较错误、异常吞噬、错误的完成状态等普通软件缺陷。用简短的宿主边界与少量自然反例捕获，而不是要求模型永远自己“记得安全”。这些反例对应本包N4–N6，不要求穷举攻击套件。

**本文是静态核对与已有记录的解释，不是对本地最新工作树的全面安全审计，也不是新的实机通过证明。**
