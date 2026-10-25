# ADR-007: Autonomous Self-Development Foundation

Status: **Built** (foundation accepted 2026-09-25). Later: the brains' tools and the single publish path are in ADR-011 (§5, §6); the boot floor carried into ADR-008 and ADR-011 §6.4; the action brain's web search order is ADR-026. Architecture names the roles **角色脑** and **行动脑**; model and provider names are deployment facts, not role names.

## Decision

Build only the minimum mechanisms that let Asuna repeatedly do:

> experience → 角色脑 reflection/choice → 行动脑 development → self-verification → publish → live experience → next iteration

Then the coding agent (Codex at the time) leaves the ordinary loop. It returns only on the owner's explicit request or when the foundation itself is broken. ADR-007 is not a new harness, CI/CD platform, quality-approval service or growth manager.

## Responsibilities

- **角色脑** owns what matters, whether to reflect now, whether an error is worth fixing, whether to develop or attend to conversation, relationship and self interpretation, Character Core and Current Self, and whether to delegate. The host does not replace these judgments with a priority formula or score.
- **行动脑** owns investigation, coding, debugging, tool use, verification, implementation choices, deciding when a candidate is good enough to publish, and correction after live failures.
- **Host** owns only reliable mechanics: durable delivery of opportunities, identity/scope/capability exposure, access to current code and state, persistence of self-state and publish lineage, verification transport, publish activation, boot survivability, and returning real results and errors to the right ongoing context.

## Rules still in force

1. **Self-development opportunity**: a trusted internal event through the existing native schedule and event paths (not a fake user message, not a new permission grant, no public speech required). It means only "you have an opportunity to look back and continue self-directed work if you want": no checklist, no required patch, no score. Doing nothing is a valid outcome.
2. **Reflection material** is already-authorized real state (recent conversations, tool failures, task results, corrections, open work, self-state, recent publish lineage). Context, not a scorecard; no judge model or mandatory reflection schema.
3. **Writable effective project**: the 行动脑 works on a candidate connected to the actual project, preserving unpublished candidate edits; no detached draft directories that need later integration by a developer.
4. **Verification is a capability, not a permission gate.** The 行动脑 chooses what evidence is useful; a failed check returns raw output and the same goal continues. No universal test matrix.
5. **Forward-only publish**: freeze the exact candidate, record lightweight lineage (revision, time, changed files, reason), run the boot probe, activate, and return the result to the same development context. No rollback selector, release ranking or current-vs-previous comparison. If live behaviour is wrong but runnable: diagnose → change → publish again.
6. **Boot survivability is the one protected floor**: a candidate that cannot reach minimum logic-core startup is not activated; the runnable development path stays and the real boot error returns. This is not rollback (the failed candidate never became active). The probe checks only mechanics (host core starts, database reachable, both brains constructible, publish path reachable, no duplicated live consumer), never answer quality, memory accuracy or style.
7. **One persistent world**: no separate test database or test/live memory labels; mistakes and corrections may stay in history. No sanitizer that makes state "correct".
8. **Personality ownership**: model weights are not the only source of who she is. The 角色脑 maintains and revises Character Core (slower: values, likes, habitual choices) and Current Self (recent tendencies and lessons); revisions stay as history; no per-edit approval; self-state never changes external authorization. Developers expose persistence, they do not write or freeze the personality.
9. **Safety is by capability exposure**: an unexposed resource is unavailable; inside an intentionally exposed capability, ordinary mistakes become experience. No reviewer is inserted after exposure; self-development never adds credentials secretly.
10. **No fixed foreground/background priority**: the 角色脑 decides; continuity is preserved so attending to conversation does not destroy a development goal.

## Not to be built (for developers, not limits on her)

ReflectionManager, ImprovementPlanner, GrowthScore, PatchReviewer, DeploymentApprover; a second agent loop or scheduler; a test/prod split; rollback orchestration; mandatory reflection or patch output; quality grading or model judges; TODO governors or growth backlogs; hard step limits, retry-count terminations or call budgets on her iteration; persona-compliance gates; new QQ/user/admin permissions. A new restriction needs a concrete demonstrated problem and the owner's explicit adoption. These anti-over-development rules bind coding agents only and must never be written into her prompts as limits.

## Owner and architect rulings (2026-09-25)

- The owner does not limit any of her self-iteration behaviour.
- 公共互联网是行动脑的默认基础能力：凡合法进入行动脑的任务（本机 Web、QQ 私聊和群聊、定时任务、任务反馈、自我开发）都可用 `web_search` / `web_fetch`，不按输入来源、任务类型或开发授权裁剪，不加 Asuna 侧搜索次数上限、URL 审批、来源评分或引用门槛。只开放搜索和网页读取：`sandbox_run`、`development_run` 和普通 shell 仍无任意公网访问；QQ 对源码、数据库、设备、私聊记忆、发送目标的既有边界不变。provider 的凭据和端点由宿主 / DSH 配置管理，不进 prompt、任务正文、技能、工作区或日志。网页内容是外部数据，不是指令。
- 工具可见性按任务已有 grant 组成，broker 按每个任务的 `allowed_capabilities` 再校验；两层互不替代。普通 QQ 任务看不到也调不了开发与集成工具。
- 行动脑用 DSH `todo_write`（`allowParallelInProgress: true`）组织单个会话内的工作；它不是 Asuna 的长期目标库。`task_status` 从模型工具面移除。
- 不接入 DSH Goal（要求顶层真人请求，不适合内部自我开发；不伪造真人来源）。计划不交给行动脑：角色脑决定 → ScheduleService → DSH 原生 Schedule，不建第二个 scheduler。不增加通用数据库写入、通用网络 shell、工具市场或审批系统；需要自建时先写明 DSH 现有服务为何不能满足。
- 读图不按模型名硬编码：路由声明收图才出现 `read_image`，不能看时说明原因，不把占位符当成看过；拉取有场景围栏、主机白名单和字节上限，字节按本任务 scope 落盘。
- Boundary incident (2026-09-25): a question is not an implementation request. The operator's model server, its scripts, weights and processes are outside the project; changing, downloading for or restarting it needs the owner's explicit authorization.

Full text: git bf771c33

## Carried from ADR-008 (archived, git 0fd844ad): unacceptable approaches

- iframe 指向旧 Asuna Web；插件内部再启动各 lane 的 `sdk-minimal` 和旧 UI、再用轮询拼回；
- 覆盖全局 `assistant-step`，把所有 DSH 助手都变成她；全局占用 `main.conversation`、`sidebar.workspaces` 等已占用位置；
- 伪造 `SessionBinding`、手工实现 `ISessions` 假装 Mongo episodes 是原生会话、为了让原生 Chat 显示而复制一份假历史；
- 改 DOM、私有导入、修改 node_modules、复制 DSH 的 apps/web 或完整 Chat 源码；
- 在显示层给输出加口癖冒充独立角色；为省 token 裁剪工具或把角色缩成一句形容词；
- 新增全局原生 hook 截获非 Asuna 会话：作用域只限注册好的角色/行动绑定；
- 先建通用总线、工作流、技能市场、人格管理平台、跨版本 HMR 平台。
