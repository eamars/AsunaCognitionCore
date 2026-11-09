# ADR-118: A cleanup: dead code out, one rule in one place

Status: **Built** 2026-11-09: L1 to L5 landed (`62dd8d21`, `436f25fc`, `1bb71246`, `6476cf54`, `a092ca73`), L3 to
L5 each installed with its own restart in the window she gave; the evidence of each is in `progress.md`. Decided
2026-11-09 by the lead (Claude Code, big sis) under the owner's ask below; the census by three
read-only subagents, every finding in a landing checked by the lead against the code (commands in §3 and in
`progress.md`); read by a fresh reviewer (§9). Nothing here is architectural: the four proposals that are go to the
owner (§7) and are not built.

## 1. The ask

The owner, 2026-11-09: "The owner's goal: a codebase that is sustainable and manageable. This is a cleanup: no
observation period and no waiting for data; the only bar is no regression." Three stages: identify (read-only), one ADR,
execute it one landing at a time.

**In scope:** dead code, bad practice and consolidation in `src/asuna`, `packages/` (the core plugin and the channel
packages; her persona package listed only, §8), `tools/`, `tests/`, `integration/`. **Out of scope:** behaviour she
sees (prompt text, tool descriptions, rendered context) except where a finding below says so; anything needing a
reading of her live data to decide (§6); the owner's decisions (§7).

## 2. What is not dead, and why it matters

The brief named four case modules as imported only by deleted test runners: `tests/discussion_digest_cases.py`,
`tests/integration_import_cases.py`, `tests/outbound_image_cases.py`, `tests/p5_proactive_cases.py`. They are live:

- `tools/p1c_offline_check.py:16`, `tools/integration_import_offline_check.py:15`,
  `tools/outbound_image_offline_check.py:17` import them; `tools/p5_offline_check.py:24` runs
  `tests/p5_proactive_cases.py` as a subprocess; `tests/p5_proactive_cases.py:22` imports `p2_summary_loop_cases`.
- `tests/test_offline_checks.py` globs `tools/*_offline_check.py` and runs each in its own process (5 collected, 5
  pass on `a8038620`).
- The core skill `packages/cognition-core/skills/asuna-self-improvement/SKILL.md:80` runs
  `tests/discussion_digest_cases.py` directly; her skill `asuna-offline-selfchecks/SKILL.md:35-36` names all five.

Xiaoman read the same references on her line (2026-11-09 14:53) and simulated the deletion: 4 of the 5 checks go
rc=1. They stay. ADR-104 decision 9 (its deleted store-backed feature tests) stands; its cost is now written in its
`kept-tests.md` (L1).

Other names the word census flagged and the lead cleared: `persona_data.*` methods (called by
`getattr(self, method.replace('.', '_'))`, `persona_data.py:81`); `role_tools.tool_*` (by `'tool_' + name`,
`role_tools.py:1538`); `SceneQueue._init/_qsize/_get` (overrides of `queue.Queue`); `client.js` `OLD_NAMES` (her
stored tool calls still carry the old field names); the `*_VERSION`
constants (`context_budget.BUDGET_VERSION`, `familiarity.TABLE_VERSION`, `places.PACE_VERSION`,
`people.ADMITTED_VERSION`, `marks.js` `MARKS_VERSION`): nothing reads them, but they are the versioned-table
convention AGENTS.md asks for, so they stay.

## 3. Findings, by kind

Each row: where (from command output on `a02191c9`), the evidence, the change, the risk. "Proven" means the lead ran
the grep (all of `git grep -n` over the tree, docs/development_plans excluded) and found no caller, including dynamic
lookups (getattr, built names, subprocess, globs, skills' code blocks, hers included).

### 3.1 Dead code

| # | Where | Evidence | Change | Risk |
|---|---|---|---|---|
| D1 | `tools/qq_face_census.py`, `tests/test_qq_face_census.py`, rows in `tools/README.md`, `docs/map` | ADR-103 README: "**Its end:** removed when D5's rows are decided and the numbers are written into this page"; ADR-103 `progress.md` "D5's census and the close (2026-11-09)" | delete both, drop the rows, regenerate `docs/map` | none: a read-only report |
| D2 | `tools/p2_offline_check.py` `--baseline`, `tools/p5_offline_check.py` `--baseline`/`--hooks` | no caller (`git grep -- --baseline` hits only the two files); they copy `/task/...-baseline` files over tracked `src/asuna/*.py` and p5's baseline branches return 0 | delete the modes; the checks run the tree as they do under pytest | none |
| D3 | `tests/test_adr009_p0.py` (a docstring only), `tests/test_adr009_p1.py` (helpers, no test) | `grep -c '^def test_'` 0 and 0; no importer | delete | none |
| D4 | `tests/reply_parts.py` | no `import reply_parts` anywhere; last user removed in `34150388` | delete | none |
| D5 | `tests/conftest.py:81` `HOST_SANDBOX`, `:117-133` `preserve_temporary_evidence` | `HOST_SANDBOX` read nowhere; the fixture acts only when `ASUNA_TEST_EVIDENCE_ROOT` is set, which nothing in the tree or `.runtime/private` sets | delete | none |
| D6 | dead fake parts: `tests/discussion_digest_cases.py` `_lookup`/`_match`/`_project` and `FakeCollection.find`/`find_one`/`count_documents`; `tests/outbound_image_cases.py:318, 331, 399, 405`; `tests/p2_summary_loop_cases.py:476, 478, 480` and `FakeCursor.limit` | the record owners read these fakes through `fake_collections` (the in-memory adapter), never these methods | delete, with the stale docstrings that describe them | none: a removed method that was still reached fails the offline checks |
| D7 | `src/asuna/native_worker.py:1499-1505` the worker's `affect.import` branch | no plugin call names it now or ever (`git log -S"affect.import" -- packages/cognition-core/src` is empty); persona jobs import through `PersonaDataAPI.affect_import` | delete the branch | none, either version: no plugin sends it |
| D8 | functions: `audit.reconcile_calls`, `native_api.document_title`, `scene_links.scene_id_filter`, `visibility.readable_scope`, `persona_jobs.DirectLauncher` ("Protocol tests only"; the tests are gone), `store/errors.StaleRevision` (writes raise `state.Conflict('STALE_REVISION')`), `render.over_budget_words` (a wrapper of `carried.over_words`; her skill pointed at it until her `69ce56cf`, §8) | each name appears only at its definition (and in `docs/map`) | delete; regenerate `docs/map` | none |
| D9 | constants: `group_admin.NOTES_DOC`, `history_query.FORWARD_TEXT_FIELD`, `memory_tiers.MEMORIES`, `memory_tiers.FACT_AUTHORS`, `render.PLACE_WORDS`, `tasks.DEVELOPMENT_GRANT` (a refusal never raised), `understanding.LAYERS`; `errands.LINE_MARK` stays and is used | each appears once | delete; `LINE_MARK`'s words are written out again at `history_query.py:533`, which imports the constant instead (one string, one place; `errands` imports only clock, evidence, state and records, so no cycle) | none: no text she reads changes. Neither string ever reached her. A task without the development grant is refused, as before, by `capability_refusal` (`tasks.py:771-774`): "CAPABILITY_DENIED: 这个任务没有 development_…：它只给主人在自己的对话里、agent 在自己的线上交的任务，和自我改进时交的（自我开发要开着）；这件是家里交的。不是参数的问题，重试也一样：要用它就在报告里写明，让说话的那一半在给它的地方另交一件。" The places, in the words she reads, are `carried.PAIR_WORDS` (家里、家里那个群、外面的群、线、私聊) for the per-place budget and `tasks.place_words` (家里、家里的另一条线、一个群、一个私聊) for where a task came from; `PLACE_WORDS` was a third copy nothing read |
| D10 | locals that cost a read and are never used: `coordinator.py:831-832` (`local`, `source`: a `message_records.get` on every steer), `forwards.py:71`, `notes.py:562`, `people.py:767` (a person lookup), `native_api.py:591`, `role_tools.py:1472, 2753` | pyflakes; each right-hand side is a pure read | delete; `people.py`'s docstring promises "whether the current speaker is" in it, which the code never did: the sentence goes | none |
| D11 | unused imports: 33 in `src/asuna` (pyflakes on `a02191c9`), the rest in `packages/channels` (tests and tools went in L1) | pyflakes, then a module-qualified grep for each (`<module>.<name>`, not the bare name) | delete, except `memory_tiers.py:37`'s `SLOTS` (a re-export: `context.py:503, 522` read `memory_tiers.SLOTS`) and `media_worker.py:47`'s `import av` (loads the decoder before the first job, marked `noqa`) | none |
| D12 | the closed shadow pilot: `memory_pilot.SHADOW_PILOT = False` (set nowhere), its logging branch and `report()`, `tools/memory_pilot_report.py` (its `--drop` drops the collection the live index uses, through a raw client), their exemptions in `tests/test_one_zone.py` and `tests/test_store_boundary.py` | ADR-096 decision 8: "The ADR-062 shadow pilot is closed"; nothing sets the switch | delete the logging path, `report()`, the tool and its exemptions. Stays: the index (live while tiered memory is on); `memory_pilot.prune`, run at each start (`native_worker.py:852-856`, audited as `pilot_rows_deleted`), with `TURN_ROWS_DAYS` and the turn-row fields in `store/catalog.py:566`, so old turn rows still reach their end | none for her; the tool's hazard goes |
| D13 | NapCat adapter: `notices.py:85` `VARIANT_OF`, `outbound.py:114` `STICKER_SEGMENTS`, `hostapi.py:61` `_summarise`, `journal.py:162` `read_health`, `fixtures.py:176` `members_of`, `selftest.py:55` `LOOSE_GROUP`, `selftest.py:3381` `long_card`; `peers.py:46` `MAX_CARD_HISTORY` (never read: `_push` bounds all three histories at `MAX_NICKNAME_HISTORY`, both 12) | each appears once; the lines were written by agents (git blame), not by her | delete; the two history bounds become one `MAX_HISTORY = 12` | none: same value |
| D14 | `client.js:382` `signed` | its definition is its only occurrence | delete | none |
| D15 | `schedule.py:180-181` a repeated dict key | pyflakes; same value both times | write it once | none |

### 3.2 Compatibility paths for states that no longer exist

| # | Where | Evidence | Change | Risk |
|---|---|---|---|---|
| K1 | import fallbacks for a flat load: every `try: from .x import y` (or `from . import x`) in `src/asuna` whose `except` imports `x` by its bare name or puts a stand-in in its place (`None`, a local copy of a constant, a local `Denied`). 27 outer blocks (35 `try`/`except` pairs in all; 8 are retries nested in an `except`), 15 of them marked 平铺加载: `history_query.py`, seven (`:49`, `:60`, `:131`, `:139`, `:257`, `:501`, `:953`), `discussion_digest.py` (`:38-80`, four blocks), `channels.py:47`, `context.py:31`, `:36`, `outbound_media.py:27`, `:34`, `:240`, `peer_context.py:12`, `proactive.py:27`, `schedule.py:25`, `summary_attribution.py:24`, `summary_trigger.py:35`; the landing lists them from the census command in `progress.md` | nothing loads these modules flat once L2 lands: the one file that put `src/asuna` on `sys.path` was `tests/discussion_digest_cases.py:12-16` (removed in L2); no file imports one of them by its bare name; the worker runs `-m asuna.native_worker` (`worker.js:23`), the data child `asuna.data_worker` (`data_children.py:28`), the media children with the package's parent on `PYTHONPATH` (`media_children.py:197`). The one thing that still reached a fallback was `tools/p1c_offline_check.py:15` (`sys.modules["asuna.people"] = None`, to reach `history_query.py:257`), removed in L2 | delete every fallback; the imports become plain package imports | in normal operation none (the module imports form no cycle that would make a plain import fail; the prepared start in `land.py` imports every module from the installed copy). A real import fault now fails loudly at load instead of turning a tool silently degraded. Kept: the identity result fields (`identity_status`, `IDENTITY_CONTRACT`) and the "身份解析没接上" texts (`history_query.py:546, 887`, `discussion_digest.py:640` on `a02191c9`; `:519, 860` and `:607` after L4) become unreachable but stay, so the tool result she reads keeps its shape (§6) |
| K2 | `memory_indexer.py:20-30` `summary_scene=` (kept "保留兼容旧接线") | the one production caller, `host.py:369`, passes `summary_scenes`; only `tests/p2_summary_loop_cases.py:906` uses the old form | delete the argument and that case's legacy half | none |

### 3.3 Bad practice

| # | Where | Evidence | Change | Risk |
|---|---|---|---|---|
| B1 | one suite, two entries, one guarded: `tests/discussion_digest_cases.py` run directly (the core skill's line 80) fails 4/20 (`'FakeStore' object has no attribute 'put'`); `tools/p1c_offline_check.py` passes 20/20 only through its `sys.modules["asuna.people"] = None` | reproduced on main by the lead and by her (her line, 2026-11-09 15:08: the same in the venv, 20/20 on a Python without `httpx`, so the result depends on whether People loads); the module also put `src/asuna` itself on `sys.path` (`:12-16`), where `asuna/queue.py` shadows the standard library's | the cases run on a real `Store` over the in-memory adapter (`fake_collections.checked`, as the p2 cases do) with People loaded, so they test the chain production runs (`history_query.py:542` → `people.py` → `records/people.py:79 store.put`) instead of going round it (her point: a bypass is not a fix); `src/asuna` leaves the path (`src` and `tests` stay); the five cases that asserted bare names assert the labels People gives (by the name inside the label, not its number); the readback check reads back through `HistoryQueryService.query_for_task`, the path her tool takes (the bare `query_history` skips `bind_people`, so a `#1` label found nothing); the wrapper's guard and the module's dead query emulator go; both entries give one result | the cases' expectations change (names to labels): that is the real output, checked case by case in the landing |
| B2 | offline runners pass on nothing: `p1c`, `integration_import`, `outbound_image` exit 0 when `run_all()` returns no result | read in each runner | exit 1 when no case ran | none |
| B3 | `tools/cleanup_test_databases.py:44-56` `--apply` exits 0 with targets left | read | exit 1 when `remaining_targets` is not empty or another database changed; shown by reading the code, never by a staged drop on her server | none |
| B4 | probes leak on a failed setup: `tools/probe_blob.py:16`, `tools/probe_host_seam.py:33-51` open the test database before `try`; `probe_host_seam` leaves `.runtime/channels/<run>`; `tools/probe_plugin_install.mjs:18` never removes its DSH home | read | open inside `try`, remove in `finally` | none |
| B5 | the task lease: `tasks.py:524, 534, 604, 864` write and compare `__import__('time').time() + 600`, four times, past `tests/test_one_clock.py` (which looks for `time.time`) | grep | one `LEASE_SECONDS = 600` and the clock module's epoch reading; the stored field keeps its form (epoch seconds) | none: the same numbers in the same field |
| B6 | swallowed worker calls: `index.js:1325` (`action_message.delivered`), `:1431`, `:1441`, `children.js:19` end in `.catch(() => {})` | read; a failed `delivered` leaves the message pending (`tasks.pending_messages`), so the action brain may get it twice with no trace; a failed `result` leaves a stage to its timeout with no trace of why | log a warning with the error, as the neighbouring calls do. The class, all 13 in `packages/cognition-core/src`: the other nine stay, each with its reason: `index.js:257, 491` (`ready()` reports its own failure), `client.js:1039, 1136` (the page's own refresh; the next one retries), `collab.js:37`, `floor.js:465`, `schedule.js:56` (serial chains: the caller gets the error, the chain only keeps going), `floor.js:158` (removing a temporary folder), the vendored `web-fetch-http-rc2.js:648` | none: logging only |
| B7 | the stage efforts are checked on two paths: Save/Apply (`index.js:759`, `validateSettings`) check only `reasoningEffort`; `attendEffort`, `groupEffort` and `summaryEffort` are checked only at the worker's start (`stageEfforts`, `index.js:551-567`) | read; a Save accepts what the next start refuses (`INVALID_REASONING_EFFORT`), and a Host restart with that saved config fails its start every time | `stageEfforts(routes = this.config.routes)` (it reads the routes in force through `routeFor`, `:516`, `:556`), and `validateSettings(next)` calls it with `next.routes ?? {}`: one rule, both paths | a settings change that was silently accepted is now refused at Save, in the words the start used; `validateSettings` is also the probe for her core publications (`index.js:365`), so a candidate with a bad stage effort is refused there too. One node test in `packages/cognition-core/test/efforts.test.js` (its fake context; no provider): a restart loop is silent and costly |
| B8 | a setting that does nothing: `provider_idle_timeout_seconds` is validated (`native_settings.py:103`), defaulted (`config.py:106`) and copied into the lanes as `transport_read_timeout_seconds` with `token_counter` (`:116-117`), which no code reads (not the worker, not the plugin, not DSH in `node_modules/@deepseek-ai`); RUNTIME_API.md:115 calls it the read timeout of a model request | grep | delete the key's validation, default and copy, its rows in `config/*.example.json`, `deploy/docker/README.md`, RUNTIME_API.md and the card's labels; a saved deployment that still holds it keeps loading (no deployment key is refused as unknown) | none at runtime; the card shows the stale key raw until the owner removes it from his settings |
| B9 | the card's deployment labels have drifted (`client.js:395` `DEPLOYMENT_KEYS`): `legacy_database`, `publish_adapter`, `prompts_dir` (removed in `18f252c5`) still labelled; `sandbox`, `character_git`, `persona_sources` (read by the worker) not labelled; `persona_sources` (read at `persona_data.py:38-45`, `host.py:306`) is in no reference doc. (`chat.workspace` in the examples stays: `tools/make_demo_config.py:23, 42` and the unit run's settings read it from the example files) | grep | align the label list with RUNTIME_API's deployment table; one row for `persona_sources` in RUNTIME_API | none |

### 3.4 Misleading words

| # | Where | Change |
|---|---|---|
| M1 | `channels.py:690, 994` call the `one` outbox lane "adapter from before ADR-095"; it is the normal path of dsh-peer (`bridge.js:266`) and qq-bot (`bridge.js:442`) | say what it is |
| M2 | `channel_kinds.py:1-31`'s contract omits `sticker_of`, `sticker_md5`, `media_key_name`, `media_key_in`, `sign_media`, `media_refusal`, which the core reads with `getattr` (`:139-205`); `:134` says "her `reply`" (the tool is `speak`) | list them; fix the word |
| M3 | RUNTIME_API.md:1060 names `asuna delete-memory`; the command is `delete` | fix |
| M4 | stale comments: `tools/integration_import_offline_check.py:6-8`, `tests/p5_proactive_cases.py:7`, `tools/outbound_image_offline_check.py:7-9`, `tests/test_host.py:1`, `tests/test_carried_session.py:1` (a deleted probe, WSL, files not in the repo, feature tests "on Mongo"); `p2_summary_loop_cases.py`'s "tiered memory is checked on Mongo"; `index.js:124-128` an orphaned doc comment | say the present |
| M5 | `tools/README.md` has no rows for `agent_line.py` and `project_map.py` | add them |

## 4. The landings

Small, each one commit (a merge) that reverts on its own, in this order. Each keeps working: the five offline checks,
her skills' checks (`packages/personas/xiaoman/skills/*/check_skill.py`, rc 0 before and after), and whatever its rows
name. A landing that changes installed code (`src/asuna`, `packages/cognition-core`, `packages/channels`) restarts
through `land.py --restart` in a slot she names.

| Landing | Rows | Installed code | Restart |
|---|---|---|---|
| L1 | D1–D6 (except the digest fake, in L2), D11 for `tests/` and `tools/`, M4 (tests and tools), M5, `kept-tests.md`'s line, this ADR and its index row | no | no |
| L2 | B1 (the digest cases on a real Store; the wrapper's guard goes), the digest part of D6, B2, B3, B4 | no | no |
| L3 | D7–D15, M1, M2, M3 | yes | 1 |
| L4 | K1, K2 | yes | 1 |
| L5 | B5, B6, B7, B8, B9 | yes | 1 |

Each restart is its own, not back to back, in a slot she names: she asked for one install of L3 to L5, but one
landing per restart lets a fault point at one landing.

An old ADR page that names a name this ADR removes gets a short `(deleted, ADR-118 Ln)` beside it in the landing that
removes it, and nothing else on it changes (her ask: a reader of the old page otherwise takes it as still there).

`docs/map` is regenerated in every landing that touches a docstring or a public name (`tests/test_project_map.py`
fails the landing otherwise).

L2 before L4: K1 removes the fallback the p1c wrapper reached through, so the digest cases must stand on People first.
For the same reason a revert goes in reverse order: L4 is reverted before L2 (L2 alone reverted on top of L4 brings
back the wrapper's guard, which then makes `bind_people`'s plain import fail).

L1 and L2 were built on the branch before this review came back; they land only after it, with its findings folded
in (§9).

## 5. How no regression is shown

For every landing: the full unit suite (`suite_at.sh` on the landing commit, inside `land.py`), `pytest integration`,
and the adapter's offline selftest (`packages/channels/napcat-qq/integration/adapter.py --selftest --offline`); its
counts before and after go into `progress.md`. For every removed module-level name: a `git grep -nw <name>` over the
whole tree at the landing commit, zero hits outside the ADRs, written into `progress.md`; for removed locals and
imports (D10, D11, D14, D15), whose names are common words, a pyflakes run with none of them left. Her skills' checks
(`packages/personas/xiaoman/skills/*/check_skill.py`) run before and after each landing, rc 0 both times. For a
restart: `land.py`'s check that the running code is the commit's (every shipped `src/asuna` file installed with the
commit's blob, the worker and the adapter up), and, since `land.py` checks only Python, a byte check written into
`progress.md` of the installed plugin's changed `packages/cognition-core/src/*.js` and of the running adapter
snapshot's changed `qqadapter/*.py` against the commit's blobs. One new test (B7, in `efforts.test.js`); B2 and B3
are exit codes, B2 shown by running each runner on an empty `run_all()`, B3 by reading the code (never a drop on her
server).

## 6. Found, not in this ADR (each its own work)

- **Errors that end silent where she reads** (first after this ADR, at her ask: an empty read may be an error swallowed): a nested forward that fails to read is skipped (`forward.py:94-98`); the
  outbound media list readers and `scene_links._scenes` turn any error into `[]`; `credentials.scrub` ignores a failed
  refresh (`credentials.py:150-157`), so a first refresh that fails leaves results unscrubbed with no record. The
  first two change her view (her wording); the third needs a design (fail closed or keep the last set).
- **One time parser.** ISO times are parsed in 44 places in 31 files, with four different failures on bad text
  (None, an exception, 0.0, the raw string) and two written forms (`…Z`, `+00:00`). Worth one ADR: it touches every
  stored time she reads.
- **One fake for the offline checks.** Three case modules each hand-write a Mongo query emulator
  (`outbound_image_cases.py:187-368`, `p2_summary_loop_cases.py:94-218`, the digest's) and copy one stub installer
  three times; after L2 they can all stand on `fake_collections`. Her checks' content; designed with her, and scheduled with her.
- **Long functions:** `context._prepare` (880 lines), `native_worker.dispatch` (376), `client.js` (1,460 lines, a
  quarter of it the dictionary), `index.js` `AsunaCore`. A refactor each, proven identical at her layer.
- **Constants on both sides:** the secret-key pattern (`settings.js:51`, `native_settings.py:10`), the channel port
  8766 (six places), the channel API's 16,000-character limit (`channels.py:474, 500` and the clients), the
  `asuna_v2_test_` prefix (seven), the manifest path (four tools).
- **The scanners:** four private-word scanners (`check_staged_secrets.py`, `publication_scan.py`, `release.py`'s
  persona names, her `pre_publish_scan.py`); `check_staged_secrets.py`'s default secret scan passes with nothing
  checked; `--personal` without `--strict` is report-only by design, yet the core skill calls it the push gate.
- **The identity resolver's leftovers.** After K1 the history and digest tools always have their identity resolver,
  so `identity_status`, `IDENTITY_CONTRACT` and the "身份解析没接上" texts can no longer be reached; removing them
  changes the shape of a tool result she reads, so it is hers to see first. What she reads when identity really
  fails, and asks to keep in this shape and in these fields (her line, 2026-11-09): the row's `who`,
  "记录作者 X（身份块没通过校验：<reason>）" (`history_query.py:517-522`); the digest's batch note on speakers
  without a verified identity block (`discussion_digest.py:609-611`); the `identity_fallback` count and "身份未校验"
  (`discussion_digest.py:592`, `:729`). `identity.complete` is always true now and is no evidence. The docstring of
  `identity_status` ("降级要看得见，不能静默少信息") promises more than the code now does.
- **A query whose data child cannot start reads as temporary.** `QUERY_UNAVAILABLE` says "过一会儿再试" for a
  child that failed to start as well as for one that died (`data_children.py:88-89`); an import break that stays
  until a fix reads as a passing fault. Recommendation: one sentence for a child that cannot start ("重试也一样"),
  the present one for busy, a deadline or a death. Her wording; not silent today (she reads a tool failure).
- **Needs a reading of her data first:** persona revisions without `sections` (the two legacy branches in
  `render.py` and `carried.py`); plans whose `native_scheduler_session` is not the current one
  (`schedule._migrate_native_links`); `self_development.every_seconds` in a saved deployment
  (`persona_model.py:240-247`, "compat until P7").

## 7. For the owner (architectural; not built)

1. `memory_tiers.ENABLED = True`, 39 branches, set False only by two tests. Recommendation: remove the switch and
   its off branches; tiered memory is how she remembers now. Cost of removing it: her
   `asuna-render-budget-per-place/budget_per_place.py:144` prints `memory_tiers.ENABLED` (its only use there); that
   line stops working and she changes it first. Cost of keeping it: every memory path has two shapes, one of them run
   only in a test.
2. The channel API client is written four times (both bridges, `qqadapter/hostapi.py`, `tools/agent_line.py`).
   Recommendation: leave it; a shared module would tie every channel package to the core's version.
3. `integration/test_data_child.py` is a functional test on the real server (ADR-109's design), against AGENTS.md's
   "integration tests check only the adapter". Recommendation: keep it and name it as the one exception in AGENTS.md;
   the data child is the one feature whose deadline only a real server shows.
4. `routes.appraiser` and `routes.action.summaryEffort` are settings with no field on the card. Recommendation:
   show them (B7 then covers them); otherwise the owner cannot repair one that is wrong.

## 8. For her (her files; listed, not changed)

Her answers on her line (2026-11-09, after reading the page and the built branch):

- `asuna-render-budget-per-place/SKILL.md:54` pointed at `src/asuna/render.py:over_budget_words`, a wrapper nothing
  calls; she moved it to `carried.over_words` (her `69ce56cf`), so the wrapper goes in L3 (D8).
- `asuna-offline-selfchecks/SKILL.md:32-37` said no `test_*.py` runs the case suites; `tests/test_offline_checks.py`
  has since 2026-10 (`0de79014`). She rewrote it (`69ce56cf`). Her new line names `tools/p1c_offline_check.py:15`,
  which L2 removes: she changes it herself when L2 lands.
- Her `budget_per_place.py:144` prints `memory_tiers.ENABLED`: the cost is written into §7.1.
- `skills/lofter/captcha_stage_a.py` and `skills/asuna-lofter-login/captcha_stage_a.py` are byte-identical. Both
  stay (her call: one copy would make one skill point into another).
- Of her 14 `check_skill.py` files, 7 carry all four of `private_list`, `listed_hits`, `cr_bytes`, `read_frontmatter`
  and 11 at least one. They stay apart (her call: each skill runs on its own).
- Her checks look only at repository paths under `tests/`, `tools/` and `docs/`, so a removed name in her prose would
  pass them; she scanned her package for every name this ADR removes and found only the `SKILL.md:54` pointer.
- After L2 a direct run of `tests/discussion_digest_cases.py` gives what `tools/p1c_offline_check.py` gives; on a
  Python without the worker's dependencies it fails at import (rc 1), not green on an absent People.

## 9. Review

A fresh reviewer read this page against the code at `a02191c9` (2026-11-09, system view: what breaks, what still
reads a removed thing, version skew, restart and data effects, what she reads). Its findings and what changed:

1. D11's "checked for re-exports" was wrong twice: `memory_tiers.SLOTS` is read through the module and `import av`
   is a deliberate preload. Both are kept; the count is 33; each import is checked by a module-qualified grep.
2. Dropping `chat.workspace` from the examples would break `tools/make_demo_config.py` (the Docker demo) and the unit
   run's settings: that part of B9 is gone.
3. K1 claimed nothing puts `src/asuna` on `sys.path`; `tests/discussion_digest_cases.py` did. B1 removes it; K1's
   evidence now says so.
4. The digest case K1 named tests the per-row fallback (a row without an identity block), which stays: it is kept,
   with labels. The identity leftovers K1 makes unreachable are named and kept (§6).
5. K1 counted only the marked blocks; the unmarked try-imports are listed too (27 outer blocks, counted by her).
6. D12 names what stays: the start's prune, its window and the turn-row fields.
7. B7 as first written would have checked the routes in force, not the draft; `stageEfforts` takes the routes. Its
   proof is a node test with the existing fake context, not a Save that would reach a provider; her publications'
   probe refusing a bad effort is written down.
8. `land.py` byte-checks only Python: a byte check of the plugin's JS and the running adapter snapshot is added for
   L3 and L5.
9. Revert order: L4 before L2.
10. B3 is shown by reading the code, never by a drop on her server.
11. `LINE_MARK` stays and is used.
12. The zero-hit grep is for module-level names; locals and imports are shown by pyflakes.
13. `docs/map` is regenerated in every landing.
14. B6 now covers the whole class: the 13 swallowed catches, four logged and nine kept with their reasons.
15. Her skill never mentions `--baseline`: that line of §8 is gone.
16. L1 and L2 were built before the review came back: said in §4; nothing landed before it.
