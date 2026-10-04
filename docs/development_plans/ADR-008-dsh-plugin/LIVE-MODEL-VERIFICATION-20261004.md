# 双脑主会话：真实模型验证（2026-10-03 至 2026-10-04）

本轮在先前隔离合成验证之后，由用户明确授权恢复真实模型。通过正式 `asuna-native` Web profile（8780）操作；外部模型服务器保持运行。此记录不代表 ADR-008 整体交付通过。

## 已取得的运行证据

- 服务模型目录只公布 `qwen38-next-uncensored-strata-vision`。实际原生请求记录分别使用 `asuna-character` 与 `asuna-action` provider，两者的 model 都是该完整名称，输出预算 32,768、推理设置 high；本轮没有使用 freetoken。
- 在现有“小满 · 本地私聊”从 Web 输入区发起只读文档任务。角色实际完成 MONOLOGUE、DECIDE，委托行动脑；行动完成 7 个原生步骤、13 次读取/列举调用，随后角色形成最终回复。没有为了通过测试修改人格或回复措辞。
- 同一主 Chat 显示真实行动来源的 Think、工具及正文；展开 `development_read · RUN_ASUNA.md` 的原生 IN/OUT，可核对实际内容与 SHA-256。原生角色记录仍在主会话，只有一个输入区。动作来源关联的边界为 `after_seq=-1`、`through_seq=69`、`state=completed`。
- 指定 QQ 群 1002866238 的真实新消息进入原来的连续会话，包括本轮 23:51 及之后的正常群聊消息。群与主人 DM 673225019 都显示原生只读输入区。此项证明消息接收与展示；没有据此声称新的 QQ 回复已送达。
- 最终版本的页面重载前后，本地角色日志与本轮只读行动日志的 SHA-256 完全相同；观察/刷新没有重放这个已完成任务。

## 本轮修复

正式旧会话启动时实际 prompt 达到 314,591 tokens，模型容量为 262,144。Asuna 预设漏挂了 DSH 的会话级 compaction 组合，而原生 Web 已禁用 Host 级组合。现已在角色、行动、摘要、恢复预设中复用 DSH 原生 compaction backend、`/compact` 与 tool-result pruner，保持原生隔离范围。

直接套用原生默认摘要预算 65,536 仍会溢出。预设改为摘要预算 8,192、最近历史保留比例 0.32。真实模型成功压缩 53 条历史（估算 88,942 tokens），随后另一轮压缩 9 条（估算 25,629 tokens）；原始持久记录保留，正常回复继续完成，原生上下文占用恢复为 53%–68% 的实际显示。

不能把 `/compact` 视作任意长度输入的修复保证：本轮首次手动压缩仍因选中跨度过大失败，自动压缩中也出现一次“摘要并未更小”的原生错误。失败记录保留，没有通过重置会话或删历史掩盖。

切换到冷 DM 时，原来的异步输入权限查询曾让输入区短暂可编辑。现在沿用 DSH 原生 `conversation.blocks`，先确认权限再启用输入。隔离 `brain-ui` profile 人为延迟查询 3 秒：QQ 输入区始终禁用，本地确认后正常恢复。迟到查询不会覆盖新选中的会话；查询失败会释放临时阻止，独立恢复入口不会因此被永久锁住。未新增自绘控件或侧栏。

## 实机暴露的未完成项

Host 重启恢复了一条先前未处理的旧 `task_feedback` 输入：原任务 `task-ep-e55cd55f354cac60fe60a187995e9539` 的 `result:1`。角色据此重新委托自修复 `task-ep-89f6848cc555a7ea1d0740a43a5ee7d4`。这不是浏览器重载复制原生消息，但会重新启动旧工作，与本轮明确限定的只读任务范围冲突。

已用现有 `--debug cancel` 维护命令撤销该任务权限，实际状态为 CANCELLED；后续调用被 `STALE_TASK_FENCE` 拒绝，原生子任务已结束。候选目录中在撤销前产生的一次性脚本保留，没有发布、激活或回滚以隐藏副作用；正式安装的 core 仍是下表所列实机验证包。

随后用户选择“等待我在现有本地聊天中明确要求继续”，已写入 [重启暂停修订案](AMENDMENT-20261004-RESTART-PAUSE.md)。源码现在将未完成旧行动与反馈设为 PAUSED、推进执行 fence，并保留结果和执行绑定；仅新的本地明确续接决策可沿原关联创建新任务，内部机会不能恢复暂停的旧工作。已完成反馈只核对持久状态，不重新生成。

在数据库中断前，隔离真实 Mongo 探针证明：恢复没有模型调用、没有排队行动或反馈；明确的新本地请求保留原执行绑定。另一个并发探针先复现“取消后仍继续 DECIDE/SPEAK，直到发布才报错”，修复后只保留已经在途的 MONOLOGUE 输出，反馈转为 SUPPRESSED，不再生成后续阶段、写公开消息或覆盖取消状态。两项探针均使用公开业务路径、真实持久化与合成推理，不调用真实模型或 QQ。

新增回归依赖的 Mongo 随后不可用；用户重启后复试仍发生连接拒绝，并明确要求先略过 Mongo 相关测试。该阶段跳过新增 8 个恢复/取消回归及正式重启验收，构建待安装 core 包 `78d0e397040580d8e65fd999b0772cb6104f9e26dced8d9d5e71c3e9e9e6736f`，正式 profile 当时仍运行实机验证的 `99dc149e9a82…` 包。随后继续完成不依赖 Mongo 的分页与独立安装检查，再安装修复包；启动时 Mongo 已恢复，补验结果见下文。

本轮尚未取得主人新 DM 的收发链路证据，也未取得新的 QQ 回复送达回执。长来源的浏览器分页已取得[隔离原生 Web 证据](INLINE-BRAINS-VERIFICATION-20261003.md)。角色主动介入行动、跨任务延续以及完整上游 Web 门禁，仍沿用前次记录中的未完成状态。

## 检查与安装

- Asuna native：24/24 通过，新增实际原生预设压缩与冷输入权限回归。
- Python native worker/product：24/24 通过。
- 在新增恢复修复后再次执行上述不依赖 Mongo 的两组检查，仍分别为 24/24；源码编译、打包与 `git diff --check` 通过。Mongo 相关回归按用户要求略过，不能计为通过。
- 四个正式安装包的文件逐字匹配对应交付 tarball；core 与 xiaoman 实际状态为 ACTIVE。
- `git diff --check` 通过；没有重新宣称上游全量 Web 门禁通过。

已用于上述真实模型交互验证的包 SHA-256（当前恢复修复包的安装见下文）：

| 包 | SHA-256 |
| --- | --- |
| native ui-chat | `467bd726e2d81762485ea793a287e59da0335dd546b241972822ce28b871c2d1` |
| native ui-renderer | `b51e163374a91a877bf6d45974fa9fdce1f1b65518d27152e13a28762d22704a` |
| cognition-core | `99dc149e9a82c4e0733a055d606aec47300a5e348fb38a56c526069b0b42900d` |
| xiaoman | `7c7380622637574063af0f7ad70bcdaa05ee33ad62403ed46674b741b52333a5` |

本机私有证据目录：`.runtime/adr008/evidence/live-inline-20261003/`。包含原生事件关联、模型路由、主会话 DOM/截图、延迟权限查询、取消回执、最终刷新比较及安装文件验证。运行日志中的 Web 鉴权地址不应公开；这些运行状态、聊天内容与凭据不进入插件交付包。

## 后续安装与 Mongo 恢复后的补验

用户要求 Mongo 不可用时先略过相关测试，因此先完成长来源原生分页和四个包的独立安装检查。独立安装确认新 core 的 8 个 Host 导出可导入、21 个 native peer 从 DSH 安装范围解析；没有启动业务消费者。

随后用 DSH 官方插件安装命令把 `78d0e397040580d8e65fd999b0772cb6104f9e26dced8d9d5e71c3e9e9e6736f` 安装到正式 `asuna-native` profile。83 个包文件逐字匹配 tarball，已保存的 `cordis.patch.yml` SHA-256 不变；未重新导入或覆盖模型凭据。原生 Host 重启后业务 worker 成功连接 Mongo，并由 `workerReady` 返回该 core 的 ACTIVE 回执（2026-10-03 12:19:20 UTC）。这证明正式安装与启动，不能替代新版全部真实模型/QQ 交互验收。

实际 Host 证据 `reports/native-host-aefb365a6a/` 记录 23 条旧任务转为 PAUSED。只读数据库核对确认暂停原因、原状态、执行绑定和 fence 均保留；重启之后没有新的 `execution.output`，没有重跑旧行动。恢复/接收的输入显示 RECEIVED_NO_WAKE。原生 Web 仍能查看 Local 与 QQ 的连续历史，记忆索引可读取；人格基线展开后可见持久化原文的最后一段，不再只能读列表的 200 字摘录。

此前跳过的 8 项恢复/取消回归在隔离真实 Mongo 数据库中全部通过，使用合成推理，不发送 QQ。扩大检查后 Host 的 20 项通过，workspace 有两条旧断言失败；未修改源码的 HEAD 基线也复现相同失败，分别依赖已退役的 `task_status` 与 `declared_status`。按现行原生回合结束及 `finish_reason` 契约修正这两条断言后，workspace 的 9 项全部通过，保留只读文件、工具权限、自然语言结果与实际回执检查。

本机证据：`.runtime/adr008/evidence/independent-install.json`、`recovery-install.json`、`formal-recovery-audit.json`、`recovery-regressions.xml`、`host-workspace-regressions.xml`、`workspace-baseline.xml`、`workspace-regressions-current.xml`，以及 `live-inline-20261003/persona-completeness.json`。首次扩大检查的失败 XML 保留，没有把基线失败或旧断言修正前的结果计成通过。上游完整 Web 门禁及上述执行协调、QQ 送达缺口不因此视为已完成。

## 后续真实只读交互与测试数据库清理

用户指出测试数据库积累，并授权再次使用真实 LLM 验证完整流程。清理前实际有 53 个数据库，其中 45 个是本项目生成的 `asuna_v2_test_M1_…`；先保存具体清单，再按清单删除。清理后保留 8 个原有数据库，正式库与无关库未删除，测试库为零。测试 fixture 在导出文件证据后执行 drop，包括 seed/setup 失败、应用已经关闭连接的路径；新保护与真实 teardown 检查 5/5，实际 workspace 测试导出证据后也确认数据库已删除。此前“为审计保留测试库”的 teardown 已取消。没有把用户报告的文件限制根因写成已经测量过的 OS 指标。证据在 `evidence/mongo-cleanup/`。

连续执行来源修复包 `602d2bdb0fe50aa9d876f15d0dbd86bec8be5d482565473e5f3e8baef8b26aff` 安装后，正式 worker 返回 ACTIVE。通过现有本地 Web 对话完成两次真实只读请求：读取 RUN_ASUNA，以及继续核对 RUNTIME_API 的恢复说明。两次任务均 RETURNED、反馈 DELIVERED；实际行动来源分别持久化 7 个 assistant 步骤、9/10 组工具调用与回执，主 Chat 显示真实记录及角色最终答复。

这次模型虽然收到明确的续接自然语言，仍选择新委托，产生新的 execution binding 和行动来源，没有填续接任务字段。因此只能证明两轮真实执行与 UI 展示，不能把它计为真实跨任务上下文续用通过。源码对相同 execution binding 的续用已取得隔离原生 Web 与真实 NativeLane 桥接证据，见[离线补验](INLINE-BRAINS-VERIFICATION-20261003.md)；真实决策入口仍需完成验证。未通过调整人格或措辞掩盖这一差异。

本机新证据为 `evidence/action-continuity/formal-current.json`、`live-inline-20261003/continuity/formal-first-dom.txt`、`formal-second-dom.txt`、`formal-sources.json`。标签一致性修复仅在合成 profile 开发与审阅，正式安装后只读取已有记录核验显示，不用真实模型生成 UI 测试样本。

## 续接上下文遗漏的实际原因与群发送回执

补查第二轮持久 context，发现先前只读任务没有出现在 task_state_from_program：查询按数据库 revision 倒序取 8 项，旧的高写入任务挤掉了较新的文档任务。因此上文“模型没有选择续接”是观察到的决策结果，不能归因为人格或模型不愿续接。

任务上下文已改为优先 READY/RUNNING，其余依真实持久输入 received_at 排列；保持 8 项上限，复用 messages 的原 ID 查询，不建额外索引库或消息记录。只读正式数据探针调用实际 ContextBuilder 后，两轮文档任务均进入上下文。回归另外保留 9 个较早的高 revision 任务，证明活跃任务优先，最近已返回任务仍可见。没有为通过测试调整人格或回复。

正式群 1002866238 的后续实际任务 `task-ep-dc763fd9b7b8cf2060faaacfb33456c4` 已 RETURNED、feedback DELIVERED。其角色回复 `ep-a8d86dae61cfc2dc93910c20b718bea0:speak:0` 的 delivery_basis 为 platform_ack，实际 QQ adapter 保存 platform_accepted、retcode=0 和 message_id=521134024。此项补齐群发送证据；本轮没有手工编写群回复或伪造平台回执。指定主人 DM 在本轮时间窗口仍无新的入站/出站，不能据此声称新的 DM 往返已验证。

执行介入及上下文修复包 `f31917851afaaf59cd3d4e546e128b683f14f55ad53711f5e364d1d6913177cf` 通过正式 DSH 安装，worker 于 2026-10-03 14:35:24 UTC 返回 ACTIVE，83 文件逐字匹配，profile 配置 SHA-256 不变。已完成 29 项原生及 59 项 Python/Mongo 回归；拥有的测试数据库清单为空。安装后在原本地聊天提出新的真实模型只读续接请求；其运行结果另记，不预先计为续接通过。

本机证据：`evidence/action-intervention/formal-audit.json`、`worker-probe.json`、`regressions-final.xml`、`install.json`，以及 `live-inline-20261003/intervention/`。完整上游 Web 门禁仍未计为通过。

## 修复后的真实模型续接

正式 Web 现有本地聊天中，以自然语言要求继续刚才的两份说明核对，只读、不改配置、不启停、不修复、不发布。实际模型选择 `continue_task_id=task-ep-cfcd840be775cc5fbff480b68f9deb9e`，新任务 `task-ep-faf2bb8bafba8da5250fbed7912f14c3` 保留前任务 execution binding，并复用原来的 `asuna-action-afe6392c7b243de5e42d75f326a6131d`。本次行动完成 4 个新 assistant 步骤、5 组实际只读工具调用/回执；同一来源累计 2 个成功 Turn、11 个 assistant 记录、15 组工具调用/回执及 1 份原始 child descriptor。

新任务 RETURNED、feedback DELIVERED，最终角色回复出现在原主聊天。父来源的前一范围止于 seq 63，续接范围为 after_seq=63、through_seq=97，state=completed；没有新建行动来源或复制旧消息。主 Chat 保持一个输入区，页面上已加载的紫色角色脑、蓝色行动脑标签都默认可见。角色没有为通过测试换措辞或人格，行动原始记录也没有伪造。

冷加载前后行动来源哈希相同。角色来源首次快照尚未包含异步完成的 subagent/catalog；旧快照哈希精确对应当前日志前 1,320,890 字节，随后仅追加 seq 636 的目录完成事件。待该元数据落库后再次冷加载，角色日志哈希也相同，没有新增模型 Turn 或重放行动。首次不同的哈希结果保留在证据中，没有把它直接计为刷新通过。

行动指出当时 RUN_ASUNA 尚无介入说明；核对完成后，Codex 将同任务修订、旧 operation 停止、原历史续接、取消/暂停边界以及两脑标签默认可见的现行行为补入运行指南。没有要求角色修订文档或为了测试改变回答。证据在 `live-inline-20261003/intervention/formal-source.json`、`formal-completed-dom.txt`、`formal-reload.json`、`formal-settled-reload.json`、`formal-last-metadata.json`，及 `evidence/action-intervention/live-current.json`。主人新 DM 往返和上游完整 Web 门禁仍未验证。
