---
name: asuna-database
description: 从库里取数据（她的消息、群、人、任务、心里话、文档、审计记录）之前先读这一份：走哪条路、真集合名和真字段名、时间怎么比、群的旧历史在哪、查空怎么报。用 asuna.dbread 读，别自己连库猜名字。
---

# asuna-database

与人格无关的核心技能，随认知核发布。

## 一句话

用 `asuna.dbread` 读：它自己连库，只读，每次回答都原样带上「查了哪个库、哪个集合、什么过滤、本地时段换成的 UTC 区间、命中几行」。报告结论时把这段一起交回去，交代的人拿它对你的结论。

## 走哪条路

- 家里交的任务，`sandbox_run` 跑一个 python3 脚本：`from asuna import dbread`。库地址和她的时区由程序给这条命令，脚本里不写地址、不读配置文件。
- 开发任务里的 `development_database_read`：一样只读，一页最多 50 行。
- 只查某段对话里谁说了什么：`query_authorized_history` 更省事。
- 范围是任务决定的：先在报告里写「这次绑在哪个对话、够得到哪些、可达多少条」，再写结论。够不到的数不是全量。

```python
from asuna import dbread
when = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00')   # 她的钟点 → UTC 区间
dbread.show(dbread.find('messages', {'scene_id': 'local-dm', 'received_at': when},
                        fields=['author', 'text', 'received_at'], sort=[('scene_seq', 1)]))
```

- `find(集合, 过滤, fields=[...], sort=[...], limit=50, skip=0)`：最多 500 行；不给 fields 时去掉 embedding 和 event.raw；回答里照写 sort 和 skip。
- `count`、`distinct(集合, 字段, 过滤)`、`aggregate(集合, 管道)`（`$out`、`$merge` 不做）。
- `history(scene_id)`：现在的行和群的旧历史（`archive:<scene_id>`）分开给。
- `place('g41690f')`：笔记和计划里的地点代号是哪个对话（scene_id）。
- `collections()`、`fields(集合)`：真名单。集合名写错，回答里列出真名；过滤里有没见过的字段，回答里写 `unseen_fields`。
- 查空时回答写着「零行」。报告里照写零行，不要空着、不要猜内容。

## 时间

- 库里所有 `*_at` 都是 UTC 的 ISO 字符串：进来的消息 `occurred_at` 以 `Z` 结尾，其他多是 `+00:00`。
- 她说的「21:00」是本地钟点：一定先 `local_window` 换成 UTC 再比，不要拿本地钟点直接比，也不要用空格分隔的时间串、不要 `$regex` 比时间。
- **圈「本地自然日」的窗口，一律传带时刻的完整时间戳**：`dbread.local_window('2026-11-03 00:00:00', '2026-11-04 00:00:00')`，不要只给日期。`local_window` 只给日期时右端会多出整整一天（实测：只给日期的 `$lt` 落在后一天的同一钟点，计数踩成虚高；带时刻传才得到正好一天，和锚点脚本的窗口一致）。复算别人的数时也先核两边窗口是不是同一把尺。
- `dbread.count(...)` 回的是 dict，数在 `['found']`，不是整数。
- 「现在」「最近 24 小时」：`dbread.now()` 是她这边现在的钟点，`dbread.recent(24)` 直接给最近 24 小时的区间。
- 她自己说出去的行（outbound）没有 `occurred_at`/`received_at`，只有一部分有 `receipt_at`：按 `scene_seq` 排。
- 翻长对话按 `scene_seq` 分段，不要大 `skip`。

## 真名

- `messages`：`scene_id`、`scene_seq`（整数）、`direction`（inbound/outbound/archived/internal）、`author`、`text`、`occurred_at`、`received_at`、`episode_id`。她的行 `author` 是她的角色 id。群的旧历史：`scene_id` 是 `archive:<scene_id>`，`direction` 是 archived，名字在 `historical_display_name`。
- 程序写进去的行（任务结果回执「你交给行动脑的「…」有了结果…」、到期计划、便条、内部时刻）`author` 是 `asuna:internal`，**不是发起人**：发起人的 person id 在事件的 `person_id` 上，不在 `author`（判据：`src/asuna/ingress.py:author_of`，程序行 = `CORE_NOTICE_KINDS` 的 task_feedback／scheduled／note 加 `INTERNAL_KINDS`）。这些行 `direction` 照旧是 `inbound`，所以**按 `author` 数「谁说了多少」之前先剔掉 `asuna:internal`**（或按正文那句固定前缀剔），否则把程序的话算成人说的；`reply_to` 也可能指向这些行，照回复链归人时同理（10-19 那趟量到：20 条最长回复里 3 条的 `reply_to` 指向注入行）。这一格要现读、别抄旧结论：用 `dbread.aggregate('messages', ...)` 按 `author` 分组，数正文以「你交给行动脑的」开头的行——其 `author` 应全是 `asuna:internal`（出处：那次聚合的回答；旧记录曾写「author 挂发起人」，与现读对不上，以现读为准）。

- `scenes`：`_id` 就是 scene_id（`qq:<号>:group:<群号>`、`qq:<号>:dm:<号>`、`local-dm`、`agent:home:dm:<线>`…），`kind`、`sequence`。没有名字字段。
- `scene_people`：一个群里一人一条：`scene_id`、`person`、`author`、`handle`（她看到的 #编号）、`card`、`nickname`、`role`、`previous`。群成员名单（`group_members`）不是说过话的记录。
- `identities`：`_id` 是 person id，`display_name`。
- `episodes`：`_id` 是回合 id，`episode_kind`（external/presence/visit/note/self_development/task_feedback/scheduled/settlement/consult）、`scene_id`、`source_event_id`、`silent_reason`。
- `tasks`：`_id` 是任务 id（没有 task_id），`state`、`title`、`goal`、`brief`、`created_at`、`finished_at`、`result`、`failure_type`。
- `audit_events`：`stream_id`（回合、任务等的 id）、`seq`、`type`、`occurred_at`、`payload`。一次工具调用是 `type: role_tool`，`stream_id` 是那个回合。`context.prepared` 只记 manifest（选了哪些、上下文的哈希）和 person_id／policy_epoch，上下文全文在 `episodes.context`。超过保留期的记录每天清掉（`role_tool` 保留得更久，每种回顾最近一次展示的那条一直留着；数据超过大小上限时最早的先清）。保留天数和大小上限不抄这里：现读 `audit.pruned` 那条的内容与审计配置（出处：那条 `audit_events` 记录的 payload）。查得更早的，先看 `audit.pruned` 那条说清到哪天、为什么。
- `memory_units`：`kind`（monologue/dialogue_summary/chat_chunk/memory_unit）、`status`、`body_markdown`（正文；没有 text/content/body）、`scene_id`、`participants`。
- 文档没有 documents 集合：`state_heads`（`_id` 如 `doc:<主人>:<名字>`，`revision_id`）→ `state_revisions`（`content.sections`）。

## 读流水（`journal_entries`）：两步，快照滞后是常态

流水的真身是 `journal_entries`（`slug` 为 `work_log`），库里没有叫 `work_log` 的集合。跑着的回合里装配进来的那一份快照会滞后（滞后是常态，不是故障），所以要现读，两步：

1. **先取最新**：按 `created_at` 倒序（`sort` 写 `{created_at: -1}`，`dbread` 里是 `sort=[('created_at', -1)]`）取最新几条，只要 `seq`、`heading`、`created_at`。最大的 `seq` 就是「现在流水写到哪」，快照里看到的比它小就是滞后。
2. **再按 `seq` 整数区间取**：`{'slug': 'work_log', 'seq': {'$gte': a, '$lte': b}}`。`seq` 存的是整数，用字符串做等值过滤（`{'seq': '1080'}`）会得 0 行——那不是「没有这条」，是类型不对（已实测一次）。取正文用 `body`；搜字面先只拉 `seq`、`heading`，再按命中的 `seq` 取全文，别一页拉 50 条全文。
3. 报告里写出处：集合、过滤、「最大 `seq` 是多少」、区间、命中几行。查空写「零行」。

## 取证：回合原文、被拒的词、收口正文在哪

复看自己某个回合原文时的三条路径（实测过，第一趟用 `dbread` 取 `episodes` 取空、拒词差点判不了）：

1. **被拒的 `speak` 调用，拒词原文只在 `episodes` 的 `tool_calls.<id>.refused`**；`audit_events` 里那次调用的 `payload.result` 是空的，不要拿它当「没有拒词」。
2. **取 `episodes` 的子文档（`tool_calls` 这类）要用 `development_database_read` 的 `projection`**；`asuna.dbread` 不给 `tool_calls`，用它取 `episodes` 会取空。
3. **`turn.ending_body` 只有字数**；收口正文在 `lane_receipts` 的 `result.content`，按 `_id` 是 `<episode_id>:TURN` 查。

## 写

dbread 不写。真要改库里的东西，那是一件要先想清楚、说清楚的事：写进报告，说改什么、为什么、怎么撤回。
