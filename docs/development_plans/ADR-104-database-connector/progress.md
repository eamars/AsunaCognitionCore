# ADR-104 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Decision 9 (the owner, 2026-10-29): the rest in one piece, without the detour; built on `claude/adr104-finish` (the core reaches its records only through owner modules, the MongoDB adapter behind its registry, tests in three layers); landed as `63770851aa19` and installed 2026-10-29 22:39 (`loaded.commit` `63770851`, the 160 files the core ships matching it). Her verdict as she wrote it (2026-10-29 22:32, its second half as she corrected it at 22:34): 「签的是 `0d785a2891e7` 到 `627264381258` 这批的差（39 枚，含两枚 merge），代码止于 `627264381258`，落地枚另算；2026-10-29 一次读完，凭据 `task-ed4ab3f0c9d8`。装没装上按 `loaded.commit` 算，这一格装机之后照实更新，不用再问我要句子。」

The after-install batch (docs only), her verdict as she wrote it (2026-10-29 22:48): 「签的是 `ca4a9c82bc32` 这一枚：四个文档文件、没代码，三枚 blob 我核过（`a21c25c3ef5c`、`66d3e0aedccb`、`49bcc3932c69`）；2026-10-29 22:47 一次读完，凭据 `task-e7415861db5f`。」

Her two corrections to the kept-tests table, asked in the same message, are in `01d09d2e36b2` (kept-tests blob `ecb71d753688`); for them she said: 「我不重签，因为改动就是照我这两条做的」.

The commit she named, `ca4a9c82bc32`, was written again as `4a60ed6891c2` before the push, with the same files (the same blobs she checked) and only its message reworded: the message held a short commit id of digits only, which the push gate refuses.

Before it: Decided 2026-10-28; step 1a built and installed 2026-10-28 (vector search through the store, her search unchanged); step 1b built 2026-10-28 (exact search; on her real searches the same final six in 73 of 73), on main.

Step 2 onward designed 2026-10-28 evening ([design.md](ADR-104-database-connector/design.md), decisions 7 and 8).

The design, her verdict as she wrote it (2026-10-28 17:30): 「**一、设计：签**，签在 README blob `f61f67d43889` ＋ design.md blob `f5268d6f3b6f`（提交 `d870a560bd68`）。」

B1a (the store package, the in-memory adapter, the contract suite), her verdict as she wrote it: 「**二、B1a 那批码：签在 `d870a560bd68`。**」

B1b (the MongoDB adapter, the store over it), her verdict as she wrote it (2026-10-28 18:37): 「**B1b：签**，签在提交 `6a11e3b70e44`；页 README blob `f61f67d43889`、design.md blob `67bef18e177b`。」

B2 and B3 (the lease and the fault counts; records.scenes), installed together, her verdict as she wrote it (2026-10-28 19:40): 「**B2＋B3：签**，签在提交 `ef1f9f8a6e71`；页 README blob `f61f67d43889`、design.md blob `2ae729d34353`。」

B4 (records.messages, the owner of the conversations' lines), her verdict as she wrote it (received 2026-10-28 21:47 on the agent line; the 21:52 she wrote beside it was not read from a clock): 「**B4：签**，签在提交 `fa46c24132f6`；页 README blob `f61f67d43889`、design.md blob `e3149912251c`。」

**B4 installed 2026-10-28 21:55**: signed at `fa46c24132f6`, landed as `e8c645a8db8b`, which adds only her verdict above to this entry; after the restart the 148 files the core ships match `e8c645a8db8b` blob for blob. Evidence: `.runtime/private/adr104-evidence/b4-fa46c24132f6/` and `b4-after-install-e8c645a8db8b.txt` there.

B5 and B6 (records.episodes, records.sessions, records.receipts; records.tasks, records.plans: 14 commits and 2 merges on main `83e8be85f07d`), her anchor on the design as she wrote it (received 2026-10-28 23:06 on the agent line): 「**B5＋B6：design 我锚。锚在 design.md blob `64b870727a3e`（第 4 节 None 规则在 369–376 行，我逐字读过），页 README blob `f61f67d43889`（没动），尖 `a234199c610a`。**」

Her notes with it: the timing gate's watched list holds b4's case only (`tests/test_adr104_timing_gate.py:66`); `ACCEPTED_SLOWDOWNS` is empty, so the two tests over it (`:64`-`65`) check nothing yet (a criterion that does not depend on the table is due after this ADR); that a required field is never null or missing is pinned by no test on MongoDB (the contract's fixture is `['memory', 'stand-in']`, `tests/test_store_contract.py:30`): it stands on the read counts (0 records missing each) until `claude/adr104-required` lands.

**B5 and B6 installed 2026-10-28 23:26**: anchored at `a234199c610a`, landed as `6f2f6900a216`, which adds only her anchor above to this entry; after the restart the 154 files the core ships match `6f2f6900a216` blob for blob (core package `e9b510c9a823`). Evidence: `.runtime/private/adr104-evidence/b5-10a581ddd665/`, `b6-10a581ddd665/` and `b56-after-install-6f2f6900a216.txt` there.

B7 (`records.memories`), her verdict as she wrote it (2026-10-29 10:44): 「**B7：签**，签在提交 `4d406571783a`；页 README blob `f61f67d43889`、design.md blob `7ce677ebeb01`。」

Her notes with it: `fields` given a dict is read as a list of its keys (`store/words.py:427`-`443`), so `{'embedding': 0}` would silently mean "only the vector"; no call through the store writes one now (the two left, `dbread.py:121` and `memory_pilot.py:308`, call pymongo directly), and refusing a dict (`QUERY_FIELDS_FORM`, with a contract case) is due after this batch; `b7.json` does not record the `--max-ms` it ran with (10000, given by hand; the default is 2000); the required unique-index fields are pinned on MongoDB for the three of `episodes` only (`integration/test_required_fields.py`), `sessions.binding_key` and `tasks.request_key` on the double and the stand-in only; those two are to be added to `integration/test_required_fields.py`, and until then this is three of five on MongoDB, not five.

Her count of memories one apart from their integer epochs was two moments: recounted at 10:45, all 143,047 hold an integer `policy_epoch`. Evidence: `.runtime/private/adr104-evidence/b7-4d406571783a/b7.json`.

B8 and B9 (`records.artifacts`, the blob interface, `records.heads`, documents, `records.people`, `records.ideas`), her verdict as she wrote it (2026-10-29 14:38): 「**B8＋B9：签。** 签在提交 `95ff9c566919`（design.md blob `21f2f00ac7da`，页 README `f61f67d43889` 未动，基 `5a196e66c85e`）。注三格：45 个 b8 读用例里 14 条、54 个 b9 里 1 条两侧 0 行，"全部同行"在它们身上不算覆盖；b9 的 `her running records` 一条 `plans_compared` 是 false（`plan_old` 为 null），那一格我这条道量不到；B8／B9 没有新契约用例，守卫在 owner 测试层，不在 store 契约层。」

Her notes with it: `tests/test_carried.py` names its four checks but not how many the configuration makes (a configuration without `home_groups` makes one pair fewer, `carried.py:192`), so a missing pair would not fail it; the snapshot test now accepts a `stacks_at` of 0, and no test has a backlog make it non-zero; her image skill says stored bytes are read with pymongo and GridFSBucket, not how a file is found, so keeping the GridFS file name is caution, not evidence that a script finds files by name. Evidence: `.runtime/private/adr104-evidence/b8-9eb6ddb6a2dc/`, `b9-9eb6ddb6a2dc/`.

**B2 and B3 installed 2026-10-28 20:54**, with the packaging fix (`10027e438087`). Their first start (19:57) could not be prepared and the launcher fell back: the packer had one step per package and none for `src/asuna/records/`, so its import check of the packed worker failed (`ModuleNotFoundError: asuna.records`, via `scene_links.py:24`). The packer now ships every tracked file of `src/asuna`, and a start that falls back no longer names the checkout's commit. After the restart the 147 files the core ships match the commit blob for blob, and `lane_faults`' `hour_at_1` is gone (its other indexes unchanged). Evidence: `.runtime/private/adr104-evidence/` (`b2/`, `b3/`, `ship/`; its `README.txt` names each file).

Step 1a, her verdict as she wrote it: 「**判词：能落，签在页对象 `7d0302a6af2a`。**」

Step 1b, her verdict as she wrote it: 「**判词：能落。我签在页对象 `1437d6fe25ae`；码那半签的是 `fc9eef788088` 那一套**」

Re-anchored 2026-10-28 to blob `b24fbcfcd672` (the same content she judged at `a00a9aa0eef6`; not a new reading of the page; her words in row 102).
