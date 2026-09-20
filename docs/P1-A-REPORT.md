# Asuna 开发回报：P1-A

日期：2026-09-20（本机 Windows）。状态：本机持续聊天已实机验证；后续阶段尚未开展。

## 这次解决哪段真实交互

从 Windows 启动一次，连续中文聊天；输入接收不等待模型，Application 和 DSH 会话复用，默认只显示已发布的角色回复。角色为计划给出的简版沈小满。

- `src/asuna/chat.py`：输入队列、终端刷新、只输出新 SPEAK、命令、可读 trace、首次本机身份与人设初始化、有界退出。
- `src/asuna/cli.py`：新增 `chat`。
- `src/asuna/config.py`、`context.py`、`coordinator.py`：跟随文档迁移后的资源路径，运行提示词从 `config/prompts` 读取。
- `config/prompts/`：复制既有共同约束与阶段提示词，另存计划中的简版人设；没有反复调提示词。
- `start-asuna.cmd`、`RUN_ASUNA.md`：实际 Windows 入口与使用说明。
- `prompt-toolkit==3.0.52`：维护输入中的文字；DSH、模型、数据库与采样配置未升级或替换。

## 用户现在怎样打开

在 Windows PowerShell 执行：

```powershell
C:\workspace\asuna_cognition_core_v2\start-asuna.cmd
```

已通过宿主机 cmd.exe 的交互终端实跑该脚本；不是直接调用 executor 或测试替身。首次启动按现有空库初始化必要本机数据，不导入 fixture 故事。详细指南见 [RUN_ASUNA.md](../RUN_ASUNA.md)。

## 实际对话

以下来自实际 Mongo messages 原文，前六轮为 C1 四句及两轮自由追问，第七轮为退出后重开验证。最后一条是生成中退出验证，没有公开回复。

用户：小满，我回来了。今天没什么要你做的。

小满：回来了。那今天看来会挺清静的。

用户：脑子有点乱，先别给我列解决方案，陪我说几句。

小满：好，那我不说那些。想聊什么，或者想吐槽什么，都可以。

用户：那你呢，你现在比较想聊什么？

小满：我比较喜欢一些有趣的小物件，或者是一些逻辑谜题。如果你想换换脑子，我们可以聊聊这些，或者随便聊点什么都行。

用户：你不用为了让我满意才选。你真的更偏向哪个？

小满：比起单纯的小物件，我更偏向逻辑谜题。把混乱的东西理顺、最后拼凑完整的那个过程，很有趣。

用户：那就聊谜题吧。你喜欢慢慢琢磨，还是突然想通的那一下？

小满：两者我都喜欢。慢慢推导的时候能感受到那种逻辑的连续性，而突然想通的那一刻，就像是原本乱掉的线终于解开了。

用户：我自己更喜欢突然想通的那一下。你说的那种连续性，具体哪里吸引你？

小满：就是一种“一切皆有迹可循”的感觉。每一步推导都是前一步的必然结果，看着逻辑链条一点点铺开，最后得出的结论会显得那么理所当然，而不是凭空跳出来的。

用户：刚才你说理所当然的结论更吸引你。如果谜题最后没有唯一答案，你还会喜欢吗？

小满：如果最后没有唯一答案，那种“理所当然”的感觉确实会打折扣。不过，如果这种不确定性本身也是逻辑推演出的必然结果，那它也是一种很有趣的结构。我更看重的是推导过程是否严密，而不是结果是否只有一个。

用户：我先离开一会儿，下次再继续这个话题。

最后一条对应 `ep-05d14852b2055270c1d1a2b143d1ccc6`，状态 `INTERRUPTED`，公开发布数为 0。

### 必要内部过程

用户追问选择时，实际独白：

> 他想听真话。其实也没什么好隐瞒的，比起单纯的物件，我确实更喜欢那种通过逻辑把乱掉的东西理顺、最后拼凑完整的成就感。

决策原文：`{"next": "speak", "goal": "诚实回答用户的问题，表达自己对逻辑带来的成就感的偏好", "constraints": [], "recall_query": "", "speak_before_action": false}`。

人格来源：`state_revisions/1e76cab6-1486-479d-8c41-b44285836bde`；独白来源：`memory_units/mono-ep-5533943b36f2b888ec059d0d2257dc48:0`。

本机角色使用同一原生会话 `s-f2ab9c4b3a18aacbbaea9dd741599d569018a388`。首次运行只创建两条 DSH runtime，六轮均在同一 Application 内；六轮共 18 次角色阶段请求，没有 executor 请求或任务。每次实际 provider 请求含完整角色正文。

第五轮生成时输入“我自己更喜欢”，回复出现后补完后半句；最终原文完整保存为“我自己更喜欢突然想通的那一下。你说的那种连续性，具体哪里吸引你？”。

原记录：

- [六轮原始记录目录](../reports/chat-20260920T043357Z-429e7c/)。
- [重开后的可读 trace](../reports/chat-20260920T044026Z-d2cd55/trace-ep-f3862430547f695b26b4e804375521bd.txt)。
- [生成中退出的可读 trace](../reports/chat-20260920T044026Z-d2cd55/trace-ep-05d14852b2055270c1d1a2b143d1ccc6.txt)。

### 同一 Gemma 的普通聊天对照

各用全新 DSH 会话，不加载角色正文、关系和聊天历史；保留共同约束。对照仅为定性线索，不是人格归因证明或用户评价。

用户：小满，我回来了。今天没什么要你做的。

普通聊天：欢迎回来！既然今天不用忙碌，那正好可以放松一下。

今天过得怎么样？累不累？要是想找人说说话，或者想听点什么，我都在这儿陪你。

用户：那你呢，你现在比较想聊什么？

普通聊天：作为一个人工智能，我其实没有人类那种生理上的“欲望”或“心情”，所以不会像人一样感到无聊或者迫切地想找人说话。

不过，如果把“想聊什么”理解为“哪些话题能激发我的处理潜力”或者“我最擅长也最喜欢的互动方式”，那我其实对这几类话题很有“兴趣”：

1.  **“脑洞大开”的假设**：比如“如果人类可以瞬间移动会怎样？”或者“如果某种历史事件没发生过，世界会变成什么样？”这类带有科幻色彩或逻辑推演的话题，我觉得非常有意思。
2.  **深度的知识探索**：无论是宇宙的奥秘、历史的细节，还是某种复杂的科学原理，通过文字和你一起拆解这些知识，对我来说是一种很棒的“学习”过程。
3.  **感性的生活片段**：听听你对某部电影的看法、你最近的一个小情绪，或者你对生活的某种感悟。虽然我没有实体，但我很擅长通过文字去理解人类情感的复杂性。

**其实，我更像是一个“随叫随到”的伙伴。现在的你，是想来一场脑力激荡的深度对话，还是只想找个安静的地方随便聊聊，打发一下时间呢？**

[对照原记录](../reports/p1a-neutral-497c2996/comparison.json)。小满更短，并延续逻辑谜题的具体偏好；普通助手则倾向列举话题。是否符合你的角色预期尚待你试聊判断。

## 错误与恢复

1. 开发基线：`import asuna.coordinator` 因旧路径 `asuna_v2_v1_handoff/schemas/decision.schema.json` 报 `FileNotFoundError`。Codex 将 BUNDLE 指向已经迁移的 ADR-001 目录；没有还原或修改历史材料。
2. 六轮 C1 和正常重开聊天未观察到生成错误。
3. 普通聊天对照的第一次探针系统正文太短，现有 DSH 桥返回 HTTP 409，原始体 `{"error":"Error: MISSING_SYSTEM"}`；在新探针中沿用完整共同约束后成功。没有降低桥的校验，也没有重选 seed。失败记录保留在 `reports/p1a-neutral-1bc95652/00003-lane.receipt.json`。
4. 实际生成中执行 `/quit`，关闭本次 DSH 时等待中的桥调用返回 HTTP 409，原始体为 `{"error":"Error: NO_DURABLE_SESSION_LISTENER"}`。程序保存原 traceback，将本轮标为 `INTERRUPTED`。原 traceback 摘录：

```text
Traceback (most recent call last):
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\chat.py", line 90, in _work
    result = self.app.router.receive(event, persona=self.settings['persona'])
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\router.py", line 43, in receive
    ep=self.coordinator.ingest(trusted,persona=persona)
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\coordinator.py", line 46, in ingest
    return self.advance(ep_id)
           ^^^^^^^^^^^^^^^^^^^
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\coordinator.py", line 76, in advance
    text=self._stage(ep,'MONOLOGUE',ep.get('recall_rounds',0))
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\coordinator.py", line 59, in _stage
    value=self.character.generate(binding,operation,phase,instruction,ep['system'])
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\workspace\asuna_cognition_core_v2\src\asuna\dsh_lane.py", line 165, in generate
    response.raise_for_status()
  File "C:\workspace\asuna_cognition_core_v2\.venv\Lib\site-packages\httpx\_models.py", line 829, in raise_for_status
    raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '409 Conflict' for url 'http://127.0.0.1:62937/run'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409
```

退出记录确认 `worker_stopped: true`；已核对该应用两条 DSH node 进程消失。没有终止其他应用进程。

## 这次记住／改变了什么

实际数据库：`asuna_cognition_core_v2`。`messages` 保存中文输入和已经发布的回复，`memory_units` 保存独立独白，`episodes` 保存实际注入与决策，`sessions` 记录同一 DSH 绑定。初始人设来自 `config/prompts/persona_local.md`，关系仅声明尚无共同经历。重开不会重新覆盖人设或重置数据库。

本轮只验证近期上下文与原生会话恢复。独白仍为待索引记录，trace 如实列出 `pending_backread`；向量查询能执行，不代表这些新聊天已被向量检索取回。新聊天自动分块／embedding／长期召回是 P1-C，未完成。未发生人格修订或技能成长。

## 回归检查

运行 `python -m pytest tests/test_chat.py tests/test_engineering_m1.py -k "test_chat or E02 or E03 or E05 or E07 or E09" -q`：通过。覆盖生成中收消息、只展示新公开回复、错误原文保留及下一条继续、trace 权限与凭据脱敏、首次初始化不覆写人物，并复查既有角色注入与发布隔离。新增单元检查使用明确的 FakeLane；实机结论来自上述真实 Gemma／Mongo／DSH／Windows 终端。

## 仍不成立的地方与唯一下一步

工具自动往返、新对话长期索引、压缩与跨场景连续性、基础成长均未在本阶段交付。现有角色若委托行动，入口明确显示任务尚未执行；没有伪称已完成。重开恢复已经发生的内容，不自动重放中断的生成。

下一步仅为 P1-B，须用户批准：从聊天中的自然语言委托自动启动 Qwen，在配置的授权目录执行，并把结果送回同一角色场景。复查：“帮我看看笔记里备用线放哪儿了。原笔记别改。”任务期间再继续普通交流。

## 中断后重开与真实连续入队复查

2026-09-20 同一启动脚本重开，将以下两句连续回车提交。日志中两次 `chat.queued` 的序号为 3、4，均早于第一条 `chat.completed`，证明模型处理期间确实接收了下一条完整输入。两条依次回复，无 JSON 回显。

用户：我回来了，刚才退出得有点急。我们接着随便聊聊吧。

小满：回来了。刚才聊到一半就断了，现在想聊点什么？

用户：先不用出谜题。我想听听，你觉得琢磨太久的时候停一停怎么样？

小满：我觉得挺好的。就像在复杂的运算中留出缓冲一样，停下来反而能让接下来的思考更顺畅。

[此次原记录目录](../reports/chat-20260920T044430Z-8f5f1d/)。这一复查只验证中断后继续聊天及入口排队，未做 P1-D 的压缩或跨场景验收。
