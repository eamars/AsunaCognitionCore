# 双脑主会话展示：2026-10-03 实现与验证

对应[已批准修订案](AMENDMENT-20261003-INLINE-BRAINS.md)。本记录只验收主会话展示，不代表 ADR-008 整体完成。

## 已实现行为

角色主会话通过持久关联引用实际 native action session。每次角色咨询前后记录行动来源的序列边界，主页面依次呈现行动、角色咨询、后续行动；不复制两脑正文或改变各自模型路由、上下文、发布策略。

蓝色“行动脑”、紫色“角色脑”沿用已批准标签。思考、工具输入输出、文件右栏及图片预览复用 DSH 原生渲染与展开设施。移除了原先默认打开行动页面的业务按钮；原生子会话导航仍可用于诊断。

DSH rc.2 的公开扩展位不能直接完成这种跨会话组合：原生 Chat 独占其节点插槽，原生工厂也会拒绝在不同来源下复用同一个工厂。本次最小扩展新增 Session 作用域的 native Chat 内容工厂，并按实际来源判断工厂循环；不复制 Chat、不替换 assistant renderer、不修改 node_modules。来源片段不进入主会话的滚动锚点与 turn 导航。

实现与构建方法见 [native extension](../../../tools/dsh-inline/README.md)。

## 实际 Web 证据

验证使用独立 `brain-ui` profile、端口 8781、一个合成模型 `inline-fixture / synthetic-one`。角色和行动是实际原生 Agent；业务推进由隔离的 fixture 驱动，不启动 Python/Mongo/QQ 消费链路。生产 profile、8780 及外部模型服务器未因本次开发而修改。

- 从原生输入区发起任务，观察真实流式更新及两次 `consult_character` 调用；行动 A → 角色咨询 → 行动 B → 第二次咨询 → 行动 C 在同一 Chat 中连续出现。
- 展开原生 Completed、Analysis 和 Think，可读角色原始推理；原生工具折叠展开后显示实际 IN/OUT。行动推理直接使用原生 Think。
- 强制合成行动失败，原生失败记录在主会话显示。
- 角色与行动使用不同目录；行动输出中的文件链接打开原生右栏中的正确来源文件，本地图片加载正确并可打开原生预览。
- DOM 确认一个输入区、一个主滚动区。浅色与深色截图确认两脑标签可辨认。
- 主机重启后恢复原始历史；最终页面刷新前后六个双脑来源日志的 SHA-256 完全相同，没有重放任务。

本机证据位于 `.runtime/adr008/evidence/inline-brains/`：`expanded-dom.txt`、`expanded-light.jpg`、`expanded-dark.jpg`、`reload.json`。临时运行根目录为 `C:/Users/rba90/AppData/Local/Temp/asuna-brain-ui-f6f65817c8304ac2bf3401a2f95cd68d`。浏览器保留“ 双脑连续记录 · 离线验证 ”页用于交互审阅。

## 检查结果与限制

| 检查 | 结果 |
| --- | --- |
| Asuna native tests | 22/22 通过 |
| DSH Chat、Conversation 接点及工厂检查 | 45 个文件、643/643 项通过 |
| Host/client 类型检查、构建 | 通过 |
| 四个交付包的独立安装及 Host 导出导入 | 通过；未启动实际消费者 |
| DSH 全量 GUI | 9519 项通过、2 项失败、1 项跳过；两个失败在原版基线也复现 |
| 五组相关 Web 回放 | 修改版与原版均为 43 项通过、5 项失败、2 项跳过，另有相同的三个套件结束时日志断言失败 |
| 全量 Web | 已尝试，出现多项失败及超时后停止；未通过全量验收 |

GUI 基线失败涉及 Windows 创建符号链接权限，以及日期选择器的时区断言。Web 对照的差异涉及 Windows 路径分隔符、原生 `pwsh` 与 Linux 预期 `bash` 的工具集合，以及 Windows 自带技能使回放日志多出事件。没有修改上游 goldens 来掩盖这些差异。全量 Web 中其余失败没有全部归因，不能宣称全量通过。

全量 GUI 还发现本次工厂变更曾导致首次创建会话时输入区重新挂载；已修复：来源身份仅用于循环检测，保留原有组件边界身份。修复后原有输入区用例及上述 643 项检查通过。

测试日志位于临时运行根目录的 `build-logs/`：`inline-final.log`、`gui-final.log`、`gui-baseline.log`、`web-targeted.log`、`web-baseline.log`、`web.log`。Web 基线对照结束后已恢复批准的补丁并重建，源文件与补丁逐字匹配。

## 可审阅交付来源

原生基础固定为 DSH `dsh-v0.2.0-rc.2`，commit `639ed015397290b3745d163aafe02ffee4aa3f84`。

补丁 `tools/dsh-inline/rc2-inline.patch` SHA-256：`fa3103db373362cd4d54e92fb8abf69c169b70e051d03c4224fbf46d172ba339`。

交付清单 `.runtime/adr008/packages/manifest.json` 包含两个 Asuna 插件及两个原生渲染依赖；原生依赖版本为 `0.2.0-rc.2-asuna.1`。独立安装证据在 `.runtime/adr008/evidence/independent-install.json`。

| 包 | SHA-256 |
| --- | --- |
| native ui-chat | `467bd726e2d81762485ea793a287e59da0335dd546b241972822ce28b871c2d1` |
| native ui-renderer | `b51e163374a91a877bf6d45974fa9fdce1f1b65518d27152e13a28762d22704a` |
| cognition-core | `d2d309aaa86d5ebf92b2be201449d4debcc98d9061ab0674ac506ecbf510f6db` |
| xiaoman | `281e9d1c4158694b9834e5f015dfd6c0fa2ea7e0f2539f3b0d8a66054657e755` |

## 尚未覆盖的目标

本次证明了多次工具咨询与后续行动的原生记录展示。角色主动介入正在执行的行动任务、跨任务延续等执行协调缺口，仍需独立实现与运行证据。历史已有的 Asuna 持久关联可读取；只有原生 child catalog、没有 Asuna 关联的旧任务未自动补关联，也不根据子会话标题猜测归属。长来源日志分页随后取得实际浏览器证据，见下文。

真实模型与 QQ 交付复测、完整上游 Web 门禁仍未完成。不能由这次离线 UI 验证推断人格、业务执行或 ADR-008 整体已经验收。

后续授权实机测试的证据、实际修复和剩余限制见 [2026-10-04 实机验证](LIVE-MODEL-VERIFICATION-20261004.md)；上面的包哈希和检查数保留为本次合成验证时的记录。

## 2026-10-04：长来源原生分页

Mongo 无法连接时，按用户要求略过相关测试，继续使用上述隔离 profile。通过原生 Web 输入区提交 `dual-long`：实际原生行动会话持久化 600 个 assistant 步骤、599 组工具调用与回执，完成边界为 seq 3612。全部推理由合成 adapter 提供，不启动 Mongo、QQ 或真实模型链路。

冷加载主会话后，行动片段显示第 101 至 600 步，共 500 项。点击该来源片段内 DSH 原生 Load earlier 后，按原顺序显示 1 至 600 步，各出现一次；599 个原生工具节点保留。展开第一步工具显示 IN 的 `step: 1` 与 OUT 的 `source_record: 1` 及完整来源文本。主页面保持一个输入区，读取和展开前后所有来源日志 SHA-256 相同。

初次 280 步探针未触发分页上限，因为 DSH 按 assistant/user 消息计数，工具回执不计入该上限；因此改为 600 步，没有修改原生分页实现。运行与独立安装探针交错时曾观察到一次短暂空白截图；随后冷加载与分页正常，未捕获到渲染异常，日志只有隔离 Host 重启期间的断线重连警告。该暂态保留为观察项，不能称为已修复的故障。

证据位于 `.runtime/adr008/evidence/live-inline-20261003/long-source/`：`source.json`、`cold-600-dom.txt`、`expanded-600-dom.txt`、`expanded-600.jpg`、`paging.json`。本项通过不替代执行协调、真实 QQ 送达或上游完整 Web 门禁。

## 2026-10-04：连续执行来源与标签折叠一致性

同一执行绑定的新任务现在沿 DSH `agents.create/resume` 使用原来的实际行动来源，仍分别检查新任务授权、角色/actor/policy epoch。父会话将后续来源序号放入新的不重叠区间，重放旧回执不增添区间；新请求等前一原生回合的结果和清理结束后进入，避免在结果确认中等待产生死锁。DSH 原生 continuable manager 会继承父预设和 cwd，不能直接满足行动脑独立组合，因此这里保留公开 create/resume 和业务拥有的运行 handle，没有另建通用子代理管理器。

隔离 Web 中同一行动来源实际有两个 Turn、六个 assistant 记录、四组咨询工具调用与回执；第二轮原生请求携带上一轮内容，主 Chat 按六个不重叠区间连续显示。另一次探针在第一轮结果确认中发起后续任务，仍正常完成。刷新前后来源日志哈希相同，只有一个输入区。证据在 `live-inline-20261003/continuity/` 及 `evidence/action-continuity/`；这不代表真实模型一定会选择续接决策，也未证明角色主动打断执行。

用户要求两脑标签默认显示一致。原先角色的步骤级标签进入原生折叠过程，行动片段的标签在外部；现在都在折叠区外沿用已批准的 Pill，紫色“角色脑”、蓝色“行动脑”。角色同一 Turn 的多个阶段不重复加标签，每个步骤的原生归属仍独立保留。标签放在对应记录前、用户输入后；部分历史冷加载只采用已加载的明确归属，加载更早页面时重定位同一个标签。

隔离合成 Web 验证了默认折叠、原生 Completed/Analysis 展开、刷新后的可见性、颜色及单一输入区；角色来源 SHA-256 在查看前后相同。未添加控件、未调用真实模型、未修改 DSH 折叠实现。证据在 `live-inline-20261003/brain-labels/`。新增原生 assembler 的多阶段/部分 Turn 回归，Asuna native 检查共 28/28 通过。

待正式 QQ 工作完成后，通过 DSH 官方安装命令将标签包 `ab0fb85d949e0e2b8ed3d35f584edf9480bd6596d01079c6f2dfb795534c1449` 装入 `asuna-native`。与此前 ACTIVE 包相比只有 `src/client.js` 变化，83 个安装文件逐字匹配 tarball，已保存 profile 配置 SHA-256 不变；worker 于 2026-10-03 13:45:36 UTC 返回 ACTIVE。8780 当前群聊页面默认折叠时两脑 Pill 均可见，展开后没有增加副本；两次已完成真实只读任务来源的哈希保持不变。正式检查读取现有记录，没有提交真实推理样本。

## 2026-10-04：角色介入运行中的行动

角色的持久 `delegate + continue_task_id` 决策现在可以修订自己同场景、同人物、同 scope/epoch、相同集成授权的 READY/RUNNING 任务。沿用既有 TaskService 修订及原生 cancel/create/resume：同一 task 的 intent revision 前进，旧版本被 fence，原生来源完成中断和清理后才接纳新版本。迟到的旧 fence 通知只匹配原 operation，不能取消后来的回合。重启暂停与用户取消限制继续适用。

工具 RPC 绑定实际未完成 operation 捕获的 task 和 workspace，而非仅凭可变 session 里的最新 task_id；原生工具的执行前接点与模型请求前接点也检查该 operation。每个 operation 的 broker 绑定在结束时释放。这样旧回调不能借新任务的授权继续操作。

隔离真实 Mongo/NativeLane 桥接探针实际读取沙箱文件，随后由 Coordinator 修订任务；旧 Future 返回 STALE_TASK_FENCE，同一个行动来源接受 revision 2，旧写文件调用被拒绝且文件不存在，新只读回执正常。数据库在证据导出后删除。隔离 Web 以合成推理操作原生输入区：旧行动先产生真实工具回执并停留在推理流中；在同一主聊天提交调整后，原生 Turn 以 hook/task_revised 中断，新 Turn 读取旧 assistant 上下文，两次咨询角色后完成。来源有 2 个 Turn、3 个工具回执、仅 1 个成功 stage-result；冷加载日志哈希不变，没有重放。没有新增 UI 元素。

证据在 `evidence/action-intervention/`（Coordinator 基线、实际桥接与沙箱、Mongo 回归）及 `live-inline-20261003/intervention/`（原生 Web、来源事件、冷加载）。Asuna native 29/29、Python native/product/workspace/Host 59/59 通过。包 `f31917851afaaf59cd3d4e546e128b683f14f55ad53711f5e364d1d6913177cf` 已正式安装，83 文件逐字一致，配置哈希不变，worker 返回 ACTIVE。上述介入证明使用合成推理，不宣称真实模型已经主动选择介入。
