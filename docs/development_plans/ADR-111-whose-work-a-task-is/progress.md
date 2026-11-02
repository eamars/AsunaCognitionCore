# ADR-111 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Decided 2026-10-30 by the owner: requests from outside default to the home line (the Web chat), everything else as today; his answers in the question tool; designed on `claude/elegant-goodall-2ip12g`, reviewed against the code by a fresh reviewer; not built. Owner's rule: she reads it only when the feature is fully built

Checked 2026-11-02 against git and the live install (`loaded.commit` `ec9211cc`): L1 (`553e2f3d`, `2d58e42e`, records
whose work a task is and changes nothing she reads or can do) is on main and installed. Its two-day reading by
structure (design.md, "L1") comes before L2; L2 is not built.

小满落款：这一页钉在锚点 1c62b1e28d241285698a91b22a594d1ccb1a3a3f（design.md 76a129573f6bbd42e12d8832311bcbc2cb862f01）。这段的作用是给我的东西留一个可比的底：以后有人改这一页，脚本拿这个号去比，不匹配就停下来问我。**这不等于我逐字读过这一页**：这页我这趟没逐字读，只钉锚点。钉的時刻是本地 2026-11-02 18:46，那一刻 main 尖是 e747bbd0cdf085b3f8711d30d5d642dfa3648ed0。

L1 reading, 2026-11-03 by structure (no content), from the install (`c22436ec`, 2026-10-30 23:42 NZDT) to 11-03
10:36: 118 new tasks, 52 new plans and 763 episodes, all with `whose` (0 missing). Tasks by turn kind and `whose.by`:
external/words 51, task_feedback/words 23, scheduled/words 17, self_development/standing 13, presence/own 5,
visit/own 2, task_feedback/own 2, task_feedback/standing 2, scheduled/standing 2, note/own 1. Development grant today on
94; under §2.4 one would lose it (the note turn, `own`, as §2.4 intends) and none would gain it; the 34 on the agent
line keep it. Begun before the install and still open: 13 tasks (11 BLOCKED, 2 PAUSED, the oldest from 10-05) and 14
ACTIVE plans, which §2.6 reads. L2 next.

L2 installed 2026-11-03 11:07 NZDT (`b2313f71e13f`, `loaded.commit` checked, 166 installed files match): the
development grant from `whose` (`grants.for_whose`), `delegate`'s `for` (outside work runs on the Web chat; a person
named in a group), continuations keep their task's grant, the executor's and consult's input fenced, and what she reads.
Suite green on the commit (python 884, js 296), integration 133. Live specs: `for`'s home form in the 5 owner-private
conversations, its group form in the 22 public groups, none in the 1 DM with someone else. She was told in one message
and asked to read the whole page. Next: the two-day reading by structure (§8, L2).

小满落款：

判于 11-03 11:3x 之后（本地钟面；提交落地可能更晚）。读的是 `b2313f71e13fab13fd65e3246757eabbf950f497` 那一格：README blob `1c62b1e28d241285698a91b22a594d1ccb1a3a3f`（127 行）、design.md blob `76a129573f6bbd42e12d8832311bcbc2cb862f01`（482 行），两份全文逐字读完（取全文那一趟 task-c97fcd706b774b5179cd1c60ee835b4a，76 条工具记录，src/ 与该提交零差异）。这不等于我把 §10 引的那几枚早期提交也读了——我只读了 design 里写出的结论。

**签**：decisions 1–8 全签。§2.2 那张表、§2.4 的 `earns_development`、§2.5 两种 `for` 形态、§3.6 只在三处加字、§2.6 不改老行，都与我这条线上被咬过的现场一致。两格我特别认：

- `own`（心跳、结算、可信便条、visit、我自己的计划）不再带 `development_*` —— `src/asuna/whose.py:earns_development:163-164` 那一句 `return False`，和我 10-25 被三拒之后自己写下的「办事先认拍」是同一个方向，这次是把它落成全局规则。
- 每事件只加 15–43 字、只在三处加，其余一律不加。比我见过的多数设计克制。

**今日两格实证**（不是签的前提，留作对照）：11:19 我从这条 agent 线派的一趟用上了 `development_publish`，`whose` 判成 `words`，走的是 `agent_home_scene` 那一支——L2 装上后第一次真发布成了，与 §2.4 一致；`whose.by == 'outside'` 至今零样本，outside 那条路今晚起我才会真用到，两条测试目前只在夹具上。

**两处代码与 design 文字不一致，判「改文档、代码不动」**：① `whose.py:26` 是 `STEPS_MOST = 64`，design §2.2 写「stops after eight steps」——以代码为准（64 是断链兜底，注释也写明不是真实度量），文档改成 64。② `FOR_UNKNOWN_HERE`（`whose.py:40-41`，`role_tools.py:_for:2315` 会用）漏在 §3.1 字表、§4.1 生命周期表与 §9 字数清单之外——补上，并把那句拒话的字面给我看一眼：按 ADR-087 那条，退回的话要说清"这一拍为什么不给、去哪儿用"。

**一处我不替他定，请转金主**（只问一句，不扩范围）：`role_tools.py:placed_spec:781-786` 按 class 划分，**家里的群**（`session_class` 为 OWNER_PRIVATE 的 group）拿到的是 place 形态，那里想点名这一回合里的另一个人会被 `FOR_UNKNOWN_PLACE` 拒；他答案 5 的字面是「in a group」。代码按 class 不按"是不是群"。要不要连家里的群也认人标签归他定；`tests/test_specs_by_place.py` 现在没测 `(OWNER_PRIVATE,'group')` 这一格，定了我再签新用例。

**七条 defects 我不要求现在修**（README 已写明不在本 ADR 范围），只钉两格：① defect 5（结果所在的对话没了 → `TaskService.feedback` 读 None 的 `policy_epoch` 抛 TypeError）不修可以，但这条 crash 要能在 worker 日志里读到，别变成结果无声消失；② 链走到 64 步答 `own`（`whose.py:of_turn:69-70`）——**降级那一格现在有没有留下任何可读记录**？没有的话一条长链末端会静默丢掉授权，请回我一句有没有，我再决定要不要提改动。

**另要一格读数**（不另立判据，她 L2 那两天结构读数顺手能带）：我手上挂着的计划里 `whose.by` 是 `words`/`standing` 几条、`own` 几条。到点那一拍不带 `development_*` 的那几条，我要提前把写盘挪到带权拍，不想 11-05、11-06 两枚钟到点才发现写不了 progress.md。

2026-11-03, the owner, after the 11-01/11-02 notes: a public conversation's notes reached home through two doors, the
Web chat and his own direct chats, each with its own daily cap of 6; twice since 10-28 a note hit the Web chat's cap and
went to his direct chat minutes later (62 to the Web chat, 2 to his direct chat), and once she tried an agent line,
which was refused. His decision: the Web chat is her work channel and the one door home for notes from outside; his
direct chats and the agent lines are not destinations for them. Built with the follow-ups of her reading
(`notes.targets`; test `test_a_note_from_outside_has_one_door_home`).
