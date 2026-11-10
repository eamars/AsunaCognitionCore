# ADR-119: What the cleanup found and left: the owner's three decisions and §6's findings

Status: **Proposed** 2026-11-09. Opened by big sis (Claude Code) so that nothing ADR-118 found waits without an exit:
every item below has its own closing condition, and the ADR closes when every item is built or explicitly dropped
with a reason. Nothing is built before its design is written here and she has read the items that change what she
reads.

## 1. The owner's decisions on ADR-118 §7 (2026-11-09)

| # | Item | Closes when |
|---|---|---|
| D1 | Remove `memory_tiers.ENABLED` and its off branches | She has changed her `asuna-render-budget-per-place/budget_per_place.py:144` (it prints the switch); then the switch and its branches go, the two tests that turn it off go or test the one shape, and the suite is green. **Built 2026-11-10** (0fa7d6fa): the switch and every branch that read it are gone, with what only the off branches used (`rhythm.selections` and `promotion_candidates`, `context_budget.review_block`, the untiered tool budget); suite 962 passed, js 308 |
| D2 | `integration/test_data_child.py` off the real server | The data child's behaviour is tested without a real server (unit layer, in-memory adapter), the integration file keeps only adapter promises, and AGENTS.md's rule needs no exception. The child's deadline on a real server is no longer covered: say so here when built **Built 2026-11-10**: `integration/test_data_child.py` deleted. The unit file `tests/test_data_child.py` already covered the behaviour: the jobs in process on the in-memory adapter, a scripted child past its deadline, busy and not starting, and a real child process killed at its deadline. No longer tested: a real child opening its own Store on the configured server from the config it is handed, reading there and writing the label row. Her worker does that on every history search and digest; a child that cannot open its Store fails the call as `QUERY_UNAVAILABLE` (F2) |
| D3 | `routes.appraiser` and `routes.action.summaryEffort` on the settings card | Both show and save on the card through DSH's own facilities, shown in the isolated review profile, and the card's check covers them **Built 2026-11-10**: the action route has 后台摘要的推理强度 (`summaryEffort`, among the card's efforts: a new provider or model resets it like the others), and the affect appraiser is a route of its own on the card (情绪评估: model service, model, effort, output limit; 不用 when empty, with what it does). Shown in an isolated demo profile (its own DSH home and database, dropped after): both fields on the card, `summaryEffort: low` saved into the profile's settings, nothing applied, no model request. Save already checks both (`resolveRoutes` the appraiser route, `stageEfforts` the summary effort, ADR-118 L5); no new test |

Left as is by the owner: the four channel API clients (ADR-118 §7.2).

## 2. ADR-118 §6's findings, in order

| # | Item | Closes when |
|---|---|---|
| F1 | Errors that end silent where she reads (forward, outbound media lists, `scene_links._scenes`, `credentials.scrub`) | First, at her ask. Each read that fails says so in her wording; `credentials.scrub`'s failed refresh gets a designed rule (fail closed or keep the last set); a staged failure of each shows the new text **Built 2026-11-10** (619db9d115be, its tail 0853ac7f8e95): §3. The staged failures are unit tests; she reports the first real one she meets |
| F2 | `QUERY_UNAVAILABLE` for a child that cannot start | One sentence for "cannot start" in her wording; a staged start failure shows it **Built 2026-11-10** (her wording, line 0230): three sentences where there was one. `QUERY_CANNOT_START` for a child that will not start: a start is tried at most once a minute, and `lane_faults` keeps one row per signature and hour with its count, so repeats are counted, not each recorded; `QUERY_CLOSING` while the worker stops; `QUERY_UNAVAILABLE` now only for a child that died in the call. Before this landing `QUERY_UNAVAILABLE` meant any of the three: a record older than it cannot tell a lasting fault from a passing one. The staged start failure is `tests/test_data_child.py` (a child that fails to start answers `QUERY_CANNOT_START` and records `start_failed`) |
| F3 | The identity resolver's leftovers | She has seen the new result shape; what she asked to keep (ADR-118 §6) stays **Built 2026-11-10**: `identity_status`, `IDENTITY_CONTRACT`, the results' top-level `identity` (always complete) and the two unreachable 「身份解析没接上」 notes are gone; the rows' `who` and 「记录作者 X（身份块没通过校验：…）」, the digest's note on speakers without a verified block (now always said), `identity_fallback` and 「身份未校验」 stay |
| F4 | One time parser (44 places in 31 files) | One parser, one written form, one failure rule; a design here first because it touches every stored time she reads Design §4. **(a) built 2026-11-10**: `clock.moment`/`BadTime` read every stored instant; she reads an unreadable time as 「时间不详」 (`local_time.UNKNOWN`), an absent one as nothing (or 「时间不详」 where a sentence needs a time); computed sites raise. Kept non-raising, stated at each site: the intake path (`caught_up.stale`, `channels` await and reply ranking: a time never refuses a line), `media_life._older` (unknown is never old), `host_stops._moment` (ADR-113's handover). Where no zone is passed (`history_query._clock`, the digest's coverage window) a time shows on the UTC clock with 「（UTC）」 (`local_time.utc_face`). The intake path leaves no record telling an absent time from an unreadable one. No stored instant lacks its offset (§4), and (b) rewrites nothing stored. (b) dropped 2026-11-10: every stored time Python writes is already `+00:00`; the `Z` values come from the platform's times and the Host plugin's writes, and Python's own `Z` texts are query bounds and shown text, not stored. One form would mean rewriting intake and the plugin to fix an order that can differ only within one second; the page keeps that caveat. Her data, every record (4.1 million in 36 collections, the 121 time fields seen in each collection's newest 2,000): only the plans' wall-clock `rule.at` (350) and `last_update.from_rule.at` (149) carry no offset; a field found only in older records was not counted. **(c) built 2026-11-10**: the self-review's dates on her clock, and the owner page's mood row stamped in UTC (it wrote the machine's own offset) |
| F5 | One fake for the offline checks | The three case modules stand on `fake_collections`; designed and scheduled with her (her checks' content) **Built 2026-11-10** (with her, line 0243): `p2_summary_loop_cases` and `outbound_image_cases` no longer emulate Mongo queries; the record owners read their rows through `fake_collections` (the in-memory adapter, which `integration/store_contract.py` holds against MongoDB at every landing), and a case reads rows back by a whole query of plain field equality, every key checked, any Mongo operator refused (p2's fake also serves `p5_proactive_cases`). Case text unchanged except p2's `pending_rows`, whose `$exists: False` is written out. Before and after: p2 24/24, outbound 34/34, p5 19/19. The fakes are no longer an independent second implementation of matching: the contract run on a real server is what checks it |
| F6 | Constants on both sides (secret-key pattern, port 8766, 16,000-character limit, test prefix, manifest path) | Each has one source **Built 2026-11-10**: one Python source each (`config.CHANNEL_PORT`, `channels.MAX_TEXT`, `store.adapters.TEST_PREFIX`, `tools/pack_plugins.MANIFEST`; `asuna-launch.mjs` exports `PACKAGES_MANIFEST` to the JS tools). Where a side cannot import it (the plugin's `SECRET_KEY` and port default, the three channel clients' text limit, `floor.js`'s argv limit beside `sandbox.ARGV_CHARS`), it keeps its copy and `tests/test_shared_constants.py` fails when the copy drifts |
| F7 | The scanners (four private-word scanners; a default secret scan that passes on nothing) | A design here first: one scanner or a stated split; no scan passes when nothing was checked Design §5. **(a) built 2026-11-10**: `check_staged_secrets.py` exits 0 clean, 1 on a counted hit, 3 (`UNCHECKED`) when nothing was read or nothing it is asked to look for could be (in both modes; the secret mode refuses options); `--personal` always fails on a hit and `--strict` is gone; `release.py` goes by the exit code; the core skill's push-gate lines say so; the lead's push gate runs its scans from its own folder and stops on a git failure or an empty range. **(b) built 2026-11-10**: `asuna.private_words` is the one Python reader (the list with its categories, `text_of`: a NUL anywhere is binary, else UTF-8 with bad bytes replaced, `persona_names`: each persona package's folder and its model's names); `check_staged_secrets` (no persona name written in it any more), `release` and `publication_scan` read and match through it. It found the released QQ package's `resources-provenance.json` naming her, reworded. Two causes, apart (her correction): `check_staged_secrets`' deleted pattern was case-blind and caught the name in the core already; the release path missed it because `release.py` matched model names case-sensitively and never read the package folder (`publication_scan` matched case-sensitively too). A known hole: a name written in another form of the same character (the Japanese form of her name's second character, U+6E80) does not match; no tracked file holds one today. **(c) built 2026-11-10**: one table, `tests/fixtures/private_words_cases.json`, holds both readers (Python `tests/test_private_words_parity.py`, JS `private-words.test.js`): parsing a list and matching words; either side drifting fails. Her own copies are hers, held by her own check |
| F8 | Long functions (`context._prepare`, `native_worker.dispatch`, `client.js`, `AsunaCore`) | Each refactor proven identical at her layer, or dropped with a reason **Built 2026-11-10** (design and proof §8): `context._prepare` split into eleven ordered steps, proven line for line and by a built-twice comparison over 37 turns with 0 mismatches; `native_worker.dispatch`, `client.js` and `CognitionCore` (the row's `AsunaCore`) dropped with reasons |
| F9 | Paths that need a reading of her data first (revisions without `sections`, old scheduler links, `every_seconds`) | Her data read; each path removed or kept with the count that justifies it **Built 2026-11-10** (design §7, her reading line 0294): 0 of 1,869 document revisions without `sections`, 0 of 28 active plans on another scheduler session, her interval the default 1,440 min without the config key; the two legacy render branches, `_migrate_native_links` and the `every_seconds` read removed, a revision without sections refused by name |
| F10 | A plan whose dispatch fails is silent on her side (her line 0018, 2026-11-04); her plan view shows `next_fire_at` and `fire_count` empty for the two self-development plans though they fire | Same class as F1: a failed dispatch reaches her as a line in her wording, shown by a staged failure; the two plans show their real values **Built 2026-11-10** (design §6, her wording line 0277): a failed firing marks its conversation and her next turn there reads one line, saying whether the plan fires again; a logged firing never handed over is handed on by the rhythm watch after 300 s, once, and its turn says when it was due and why it came late; the two self-development plans carry `native_recurring` and `next_fire_at`, `fire_count` from `fire_count_since` (not back-filled). Whether the night stage runs inside her window is hers to measure |
| F11 | A silence after a body the turn-end check sent back said 「这一回合正文里一个字都没写」 (her agent line, 2026-11-10 13:22): the receipt counted only the repair stage, so her refused reply was lost while the receipt said nothing was written | **Built 2026-11-10** (her wording, line 0234): on a line whose body is sent at the turn's end, silence after a refused body says 「这一步正文里没写字。这一回合前面那段被打回了、还没发出去：就这样结束，它不会发出去。现在在正文里重写一遍才发得出去（写进 think 的不会发）。」 and echoes the refused text's first 40 characters. Where only `speak` sends, the worker already says what the whole turn sent (`sent`). The check that sends a body back is unchanged. Covered by `stage-view.test.js` "ADR-119 F11: silence after a body the check sent back…"; she reports the first real one |
| F12 | `summary_batch_id` read two ways (her finding, line 0246): the query of lines still to summarise (`records/messages.said`, `Exists(False)`) took a null as summarised, while the writer and every reader (`dialogue_summary`, `summary_attribution`, `retrieval`) take a falsy id as not; the catalog allows null, so only "nobody writes null" kept them agreeing | **Built 2026-11-10**: the query takes absent, null and empty as not summarised, the readers' rule; `tests/test_summary_batch_id.py` covers the four shapes |
| F13 | `check_staged_secrets.py --personal --all` counts 50 hits on main (2026-11-10, after F7 b: 43 account-number shapes, 2 time zones, 1 persona name), nearly all synthetic numbers in test fixtures and the scanner's own tests; three are in her image skill's files; with every persona's names read (F7 b) four more, persona names in two core tests | Each hit fixed, or allowed where it is a fixture's placeholder (`personal_scan_allow.txt` or the line's `personal-scan: ok` mark); hers are hers to judge; `--all` then exits 0 on main **Built 2026-11-10**: every hit judged, none personal: test fixtures' numbers now the placeholder form or built at runtime, scanner tests' account-shaped numbers marked, digit-only fake hashes made hex, persona names used as test data replaced (the persona paths a test reads marked); real constants (a millisecond hour, the platform's 30-day mute, the QQ bot intents mask and two error codes) and her two image seeds (her judgment) on `tools/personal_scan_allow.txt`; two daylight-saving tests moved off the deployment's own zone to another with the same switch dates. `--all` exits 0 on main. This machine has no denylist (`<data>/private/personal-denylist.txt`), so that dimension is not checked here: `--all` exiting 0 covers the private-words list, account-number shapes and persona names, not the denylist. The denylist is the owner's own list of literals; it is not drafted from her private-words list, and each list keeps its own words |
| F14 | Her daytime self-development interval has no way in (her reading, lines 0301 to 0303): `self_development.every_min` is read from her policy first but is not a `set_policy` parameter, and a live development plan is never retimed, so a changed interval (policy or persona model) never reaches the plan; no policy parameter can be cleared back to its default | She sets it with `set_policy` (360 to 10,080 min), a live plan is retimed once when the value changes (`rhythm.retimed`), a parameter written `null` returns to the persona model or the core default, and each set or clear answers the value now and where it comes from Design §9 **Built 2026-11-10** (design §9, her reading lines 0302 to 0310): `self_development.every_min` in `CORE_WRITABLE_KEYS` (360 to 10,080), retimed at once and by the watch only when it differs (`rhythm.retimed` with `from`/`to`), every native write of the plan uses the computed interval, `null` clears any parameter (the key popped), the answer names `now` and `from` |

## 3. F1 design (her wording, agent line 0222 to 0225, 2026-11-10)

The broken invariant: a reader that fails returns what "nothing there" returns, so she cannot tell an error from an
empty answer. Each reader below stops swallowing; where she reads, the failure is said in its own words, never in the
words of an empty answer.

| Where | Today | After |
|---|---|---|
| A forward inside a forward (`qqadapter/forward.py`) | skipped when it cannot be read; not read at all past two levels | a line in its place: 「↳（这里还套着一条合并转发，没读出来：<一句原因>；不再重试，没有可取的把手）」. The reason is one line from a fixed table (取不到、这条消息里要取的转发超过了一次能取的条数、QQ 拒绝了这次读取、返回里没有消息、套得太深，只读两层), never the exception text. Only a forward that was read is stored, so neither has a ref `recall` could read, and nothing reads it again |
| A forward that cannot be read at all (same file) | keeps `[合并转发（未解析）]`, no reason | 「[合并转发：没读出来（<一句原因>；条数不知道，不再重试）；没有可取的把手]」: its messages never came, so its count is unknown |
| The pictures a message may send (`outbound_media`: `edits_back_to`, `produced_images`, `image_artifacts`, `_linked_scene_ids`) | any error returns `[]`; the block disappears and reads as "no picture" | the readers raise; `context.py` keeps the block with `items: []` and the note 「能发的图这次没读出来（读库出错）——这里既不是「没有图」，也不代表有图能发；下一回合会再读。」, and records `outbound.offer_unread` (the error's type). `your_pictures_from_program` the same way (「你画的图这次没读出来（读库出错）——这里既不是「没有图」，也不代表有图；下一回合会再读。」). The scope checks that decide whether a picture may go still fail closed (not offered). The plan tool's "is this her picture" check fails the call instead of answering no |
| The vault's names (`credentials.listing`) | any error returns `[]`; `credentials_from_program` disappears and reads as "no credentials" | the same shape: the block stays, `items: []`, note 「保险箱这次读不到——这里既不是「没有凭据」，也不代表有哪一份能用；下一回合会再读。」 |
| `scene_links._scenes` | any error returns `[]`: `relationship_target` then takes this conversation's own relationship record, and a write can land in that forked record | raises: the step fails like any other store read in it (her turn's preparation fails and is recorded; `understand_person` fails as a tool error she reads). No block disappears |
| A turn that fails in its preparation (`chat.py`) | the input is marked FAILED and the turn was never kept, so the fault report, and the line her next turn there shows, never came | reported like any failed turn: her next turn in that conversation says 「你在这里 HH:MM 那一回合没跑成：是程序出了错（…）…」. The message is not delivered again; in a quiet group that line may wait long for a next turn. Each such failure is an `audit_events` row with `type` `chat.error`: the turn's id in `stream_id`, the conversation in `scope_key` (`scene:` and its id), the time, `payload.traceback`; a row whose `stream_id` is in no turn record is one that failed in its preparation. A hand-back that failed on its way to her turn writes one too |
| `credentials.scrub` | a failed refresh is ignored; a first refresh that fails passes values unscrubbed, with no record | scrubs with the last list read only while it is at most `SCRUB_LIST_STALE_SECONDS` (600) old, and records `credentials.scrub_stale` with the time that list was read; with no list, or one older than that, it refuses, and the caller says what was lost (below) |

What a refused scrub says, by what a second call does:

- an action-brain tool's result (`tasks.py`; a sandbox command most of all): the step has run; calling again runs it
  again: 「保险箱这次读不到，没法先遮住结果里的凭据，结果先没给你；这一步已经做过了，要结果得再做一次。」
- the action brain's report (`tasks.py`): 「保险箱这次读不到，没法先遮住报告里的凭据，这份报告先没交出去；要结果得重跑一次。」 (the task
  fails with that line; its report is not kept)
- doing it again is bounded (her shape): the same call refused a second time is settled, 「保险箱还是读不到，这一步的结果拿不到了。别再做这一步：接着做别的，报告里写明「保险箱读不到，这一步的结果没拿到」。」;
  three refused results in a row (the vault down) end the task with what it has, 「保险箱还是读不到，连着几步的结果都没给你。别再往下做了：已经拿到的结果照原样写进报告，再在报告里写一句「保险箱读不到，停在这一步」和做到了哪一步，交回去。」;
  a result scrubbed resets the row. The counts live in the worker, so a restart starts them again
- her own text to the action brain, a note or a question (`role_tools.py`): nothing was sent; sending again sends it:
  「保险箱这次读不到，没法先遮住这段话里的凭据，这次没交出去；过一会儿再调一次就行，不用改。」

Tests: a forward that cannot be read, one inside a forward refused and one past the depth limit (each line and its
reason, `test_forwards.py`); a picture read failing under `offer` raises (`test_outbound_unread.py`); a scrub with no
list and with a stale one (refused), a recent one (scrubbed, recorded with its time), and the vault's names unreadable
(raises; `test_credentials.py`).

## 4. F4 design: one time parser (2026-11-10)

**What is there** (survey of `src/asuna`, 2026-11-10; the earlier count of 44 sites was low): 64 parse calls on 62 lines
in 39 files, with eight behaviours on text that is not a time (raise 26, None 18, the raw string 5, '' 5, False 3, 0.0 2,
-inf 1, [] 1, plus a refusal and an omitted field). Python 3.12's `fromisoformat` reads a trailing `Z` itself, so the
`.replace('Z', '+00:00')` calls do nothing. Eight helpers already centralise part of it (`local_time._moment`/`stamp`,
`schedule_rules.line_stamp`/`_aware`, `affect.parse_ts`, `media_life._moment`, `places._at`, `history_query._parse`,
`restarts._aware`) beside about a dozen private copies.

**Her data** (field shapes only, the newest 2,000 records of each collection): 95 of 122 time fields hold only
`+00:00`. `Z` comes from outside Python (platform events, the Host plugin, publications): `messages.occurred_at` 1,936
`Z` to 64 `+00:00`, `crossing_words`, `memory_fires.latest`, `sink_receipts`, `plans.scheduled_at`. Times without an
offset are only the wall-clock `plans.rule.at` and `last_update.from_rule.at`, as intended. No stored instant lacks
its offset, so the sites that read an offsetless time as the machine's local time change nothing she has.

**The broken invariants and the design:**

1. *One reading of a stored instant.* `clock.moment(value)`: a `datetime` or ISO text (`Z`, any offset, none = UTC)
   to an aware UTC `datetime`; anything else, `None` included, raises `clock.BadTime` (a `ValueError`). Every parse
   site and every helper above calls it; the private copies go. A wall-clock time (a plan's `at`, her local query
   text in `dbread`, the fault hour key) is not an instant and keeps its own named parser.
2. *A time that cannot be read is never shown as another value.* Where she reads it (`local_time.stamp`/`for_model`,
   `schedule_rules.line_stamp` and the sites that word their own result), it says one thing in her wording (asked:
   「时间不详」), never the raw text, never an empty string, never a substitute such as 「刚才」. Where a time is computed
   on (an age, a duration, a sort key, a due check), `BadTime` propagates (F1's rule) unless the site states why
   another answer is right; 0.0, -inf, False and [] as answers for "unreadable" go.
3. *One written form for anything compared as text.* Stored instants are written with `clock.stamp()` (`+00:00`,
   microseconds); the strftime/`timespec` variants and `history_query`'s `Z` bounds use it. Text comparison of mixed
   forms misplaces a value only within the same second (`Z` sorts after `.` and `+`); stored `Z` values are not
   converted (no history conversion), new writes at ingress are normalised, and the page records that a bound can
   misplace a line written in the same second as the bound, for records older than this landing.
4. *Two defects found in the survey:* `self_review.py:264` shows her a UTC date (`strftime('%m-%d')` on a UTC time),
   not her zone's; `native_api.py:381` writes the machine's own offset. Both use her zone and UTC.

**Landings**, each its own restart: (a) the parser and every read through it, with 「时间不详」 where she reads;
(b) the written form and the ingress normalisation; (c) the two defects. Tests: the parser's cases (`Z`, offset, none,
bad, None), the one shown wording, and a bound comparison across the two forms.

## 5. F7 design: the scanners (2026-11-10)

**What is there** (survey 2026-11-10): six scanners, not four. `tools/check_staged_secrets.py` (a secret mode and
`--personal`), `tools/publication_scan.py` (her publications, through `floor.js`), `tools/release.py` (packed
tarballs), the lead's push gate (`scan_range.py` and `added_hits.py`), `tests/test_personal_words.py`, and her own
`pre_publish_scan.py` (hers). The private-words list is located, parsed and matched in four copies (`private_words.py`,
`check_staged_secrets.py`, `private-words.js`, hers), plus about twelve of her `check_skill.py`; text is read under
four different rules (where a file counts as binary, strict or replacing decode, how lines split, a size limit);
persona names are matched case-blind in one place and case-sensitively in two.

**The broken invariants:**

1. *A scan that checked nothing passed.* Exit 0 with nothing read: the secret mode with nothing staged or no secret
   in the settings; `--personal` and `--personal --strict` with nothing staged; `scan_range` when git fails or the
   range is empty; `added_hits` on an empty diff; `release.py` with the list missing; `publication_scan` always exits
   0 and `floor.js` lets a publication through "checked without a private list". After: every scanner states what it
   read (files, lines, list entries) and exits non-zero, apart from a hit's 1, when it read nothing or had no list
   (the one code `UNCHECKED = 3`). `publication_scan` is the exception, corrected: on a machine with no private list a
   publication goes on and its receipt says "checked without a private list" (stated, not silent); refusing it
   would stop her self-development wherever no list is configured. She treats such a receipt as not passed.
2. *A gate that only reports.* `--personal` without `--strict` reports hits and exits 0, and the core skill calls that
   command the push gate (`asuna-self-improvement/SKILL.md:57,171`). After: `--personal` always fails on a hit;
   `--strict` goes; `release.py` reads the exit code, not a parsed summary line.
3. *One fact, several readers.* `asuna.private_words` becomes the one Python reader (path, parse with categories,
   pattern, find) and gains the one text rule (`text_of(bytes)`: NUL anywhere is binary, strict UTF-8, `\n` lines);
   `check_staged_secrets`, `publication_scan`, `release`, the push gate and the test use it. Persona names: one
   function (`release.persona_names`), matched one way. `private-words.js` (the plugin cannot import Python) keeps its
   copy, and a test fails when it drifts (F6's shape). Her `pre_publish_scan.py` and `check_skill.py` copies are hers:
   she is offered the module, nothing of hers changes.

**Landings:** (a) invariants 1 and 2, with the skill's text and the refusal she reads; (b) invariant 3 in Python;
(c) the JS drift test. Tests: a scan of nothing exits 3 (each scanner), a hit exits 1, a missing list exits 3, and
each test is run on the old code first to show it fails there.

One landing at a time; tests only where a failure would be silent and costly.

## 6. F10 design: a due plan that does not reach her (2026-11-10)

**What is there** (survey 2026-11-10). A firing goes DSH scheduler → the scheduler session's pre-step hook
(`scheduler.js`, `schedule.js delivered`) → worker `schedule.deliver` → `Schedule._deliver_locked` → her turn. It can
end in three places, and none of them reaches her:

1. *It reaches the worker and fails there* (`_deliver_locked`'s `except`: the route revoked, the policy stale, the
   turn not enqueued). The error is kept only as the plan's `last_outcome` and a `schedule.dispatched` audit row.
2. *It never reaches the worker*: the scheduler session's turn ends before its hook (11-04: every scheduler turn
   ended "has no provider/model" from 21:08 to 22:49, no plan fired), or the callback is refused
   (`SCHEDULE_DISPATCH_NOT_FOUND` and the like). DSH has logged the firing; nothing on Asuna's side looks at it again
   until the next start (`reconcile` delivers every logged dispatch newer than the plan's `last_dispatch_seq`).
3. *The two self-development plans* (`plan-asuna-self-development`, `-night`) are written by
   `_ensure_development_plan`, which sets neither `native_recurring` nor `next_fire_at`; the firing path moves the
   next time on and counts `fire_count` only for a plan marked `native_recurring` (the rhythms' `_rhythm_plan` marks
   it). So both fire (30 and 4,278 `schedule.dispatched` rows on 11-10) with the two fields empty.

**The broken invariants and the change** (her reading and wording, agent line 0276 and 0277):

1. *A due plan that did not run is said where she reads, as a failed turn is* (ADR-076 R4, `faults.py`). A failure in
   case 1 marks the plan's conversation (`scenes.plan_fault`: the newest failure's time, cause, plan wording and
   whether the plan fires again, which plans failed, and how many since she was last told), apart from the
   turn-fault mark so the two do not overwrite each other. Her next turn there reads one line
   (`plan_fault_from_program`): 「你安排的计划「…」… 到点了没排上：程序没把它交上去（CAUSE），不是你做错了什么。」
   then 「这条计划还在，下次照旧。」 or 「这条不再响了。」, and 「从上次告诉你以来，这里没排上的计划一共 N 次。」 when
   N > 1. It says nothing about a report: the developer's inbox note (one per cause a day, counted) is written
   after the mark, and a failed write is audited (`schedule.fault_unreported`), not claimed. When the turn that showed
   the line commits, each plan it named gets a `schedule.fault_told` audit row (so she can count the times), and the
   mark goes down by what she was shown: a failure arriving while she reads stays, counted once. The deliberate
   outcomes (`OUTSIDE_NIGHT`, `NOT_DUE`, `STAGE_BUSY`, `LOOKING`, `NIGHT_OFF`) are answers, not failures, and are not
   said. These failures write no `chat.error`, so they are not in the count of turns whose episode is missing.
2. *A logged firing is handed on without waiting for a start.* The host's rhythm watch (every 300 s) delivers each
   logged dispatch that is newer than its plan's `last_dispatch_seq` and was due more than `HANDOFF_LATE_SECONDS`
   (300 s) ago, through the same `_deliver` a start uses (serialised by `deliver_lock`, a seq at most once), and
   records `schedule.handoff_late`. The plan's turn reads 「这条计划 DUE 到点，HANDED 才交到你手上：中间这一截程序没交过来
   （WHY），不是你拖的。」: WHY is 「代码 CODE」, the refused callback's code, when this process saw one after the firing
   was due, else 「定时那一拍没把它递过来，原因没记下来」 (a scheduler turn that ended before its hook leaves no record;
   her wording, line 0278); a time that cannot be read is 「时间不详」. A refused callback is picked up the same way, so case 2 needs no
   second path.
3. *One writer of a native recurring plan's shown fields.* `_ensure_development_plan` writes `native_recurring` and
   `next_fire_at` as `_rhythm_plan` does, and an already-live record is completed the same way at the next ensure.
   History is not back-filled (her ask, line 0276: the empty fields are the evidence of this defect): `fire_count`
   counts from the first firing after the change, and the record says from when (`fire_count_since`).

4. *The same defect on her own plans, and the rhythms' lifecycle* (her reading, lines 0284 to 0286). Her `every`
   plans were written `native_recurring: False` by `create` and `update` (only `daily` and `weekly` counted), so they
   too never moved their shown next run or counted; DSH repeats an `every` plan by itself, so `SELF_REPEATING` is
   `daily`, `weekly`, `every`. The next run of such a plan is DSH's own next target when it has moved on, else the
   later of now and this firing plus `every_seconds`; no clock rule is applied. Her plan tool refuses `update` and
   `cancel` alike on the four rhythms (`PLAN_RHYTHM`, since 2026-10-19), now in her wording:
   「「…」是你的节律（心跳、夜间沉淀、自我改进或整理安静的群）：这四条归程序，调它们用 set_policy（快慢、时间和夜里的窗口；
   总开关归主人）。」 The rhythm stays as it was. The two self-development plans belong to no ADR: they live while
   `self_development.enabled` holds. She tunes the night one with `set_policy` (`self_development.night_start_hour`,
   `night_hours`, `night_every_min`; `night_hours = 0` is `NIGHT_OFF` at each tick and keeps the plan), and the
   daytime one too since F14 (`self_development.every_min`, §9; until then it was not hers, her reading line 0301).
   The owner's
   switch now removes them as the other rhythms' switches do (`_retire`, one `rhythm.disabled` line with its
   reason); a plan made again after that starts a new `fire_count_since`. Her `night_hours = 0` keeps the plan only
   because `ensure_night_development` never reads `night_hours` (each tick does): the test pins the outcome, not a
   designed rule.
5. *What `fire_count` counts* (her reading, line 0288). It goes up at every firing of an `ACTIVE` native recurring
   plan whatever the outcome: it says how often the plan fired, not how often anything ran. The night plan's first
   firing after the change counted 1 with `OUTSIDE_NIGHT`. Whether the night stage runs inside her window is read
   from the outcomes, never from this count.

**Not closed by this:** whether the night stage really runs inside her window (an outcome other than `STAGE_BUSY` or
`OUTSIDE_NIGHT` between 01:07 and 05:57) is her own measurement and stays hers.

**Landing:** one, with a restart. Tests (unit, in-memory adapter): a staged dispatch failure marks the conversation
and her next turn reads the line once; a logged dispatch the callback never brought is delivered by the watch once;
the development plans carry `native_recurring` and `next_fire_at`. Each is run on the old code first to show it fails.

## 7. F9 design: three old paths, read against her data (2026-11-10)

Each path stays only if her data still reaches it. Read on her live database 2026-11-10 18:30, structure only (counts
of fields, no content):

| Path | Collection and field | What would still need it | Count | Decision |
|---|---|---|---|---|
| `render._document_text` returns `content['body']`, and `carried.sections` returns nothing, for a document revision without `sections` ("pre-conversion legacy") | `state_revisions` of `doc:*` entities, `content.sections` | a head, or a revision an episode's ref names, without `sections` | 0 of 40 document heads, 0 of 1,869 document revisions | remove both branches; a document without sections then fails where it is read instead of rendering a body or nothing |
| `schedule._migrate_native_links` at every start: a plan bound to another scheduler session is re-linked or re-armed ("one explicit cutover") | `plans.native_scheduler_session` (the current one is `asuna-scheduler-` + a hash of the database name) | an `ACTIVE` or `CREATING` plan on another session | 0 of 28 active plans; 2 ended plans have none | remove; the cutover it served is done |
| `persona_model.self_development_minutes` reads `self_development.every_seconds` from the local config ("compat until P7") before the persona model | `config/local.json` and `config/local.example.json`, `self_development.every_seconds` | a deployment whose interval comes only from that key | her live config holds 86,400 (1,440 min); her policy and her persona model set no `self_development.every_min`; the core default is 1,440 min | remove the read and the key from both files: her interval stays 1,440 min (the default) |

**Her reading** (agent line 0294):

1. *A revision without sections cannot be written today*: every edit (`edit`, its `set_tags`, `adopt_seed`) copies
   the head's content and changes fields inside its `sections` list, a new document starts with `sections: []`, and
   `documents.py` is the only writer of document revisions. Were one ever read, `render.readable_sections` refuses
   it as `DOC_SECTIONS_MISSING: 「TITLE」（KIND）这份文档的修订里没有 sections`, naming the document, not a bare
   stack.
   No test covers this: a revision without sections can only come from a hand edit of the database or an
   outside import, and the runtime refusal is what stops it (her reading, line 0295).
2. *No migration is left for a new scheduler session.* The scheduler session is `asuna-scheduler-` plus a hash of
   the database name: the day the database is renamed, nothing moves the old plans' links; they are re-armed by
   hand.
3. *The local config line removed*, as it was: `config/local.json`, `self_development.every_seconds`, value `86400`
   (inside `"self_development": {"enabled": true, "every_seconds": 86400}`). Rollback is that key back with that
   value and this landing reverted. Without that key a deployment has no single setting for the daytime interval:
   it is per persona (`self_development.every_min` in a persona model, or her `set_policy` since F14), else 1,440 min; a
   deployment that had set another value in its local config falls back to 1,440 (here 86,400 s = 1,440 min).
4. *What the removed render branch would have returned* (her count, line 0297): no document revision carries a
   `content.body` (0 of 1,869; every one is `{kind, title, sections, source}`), so the branch rendered nothing,
   not another text; `sections` is never an empty list.

**Landing:** one, with a restart. Test: none new; each removal is checked by the counts above, read again on her
data just before the landing, and by the suite (a test that leaned on a removed path is changed with it, named in
the landing).

## 8. F8 design: the long functions (2026-11-10)

**What is there** (survey 2026-11-10). The row names four; the fourth is `CognitionCore` (there is no `AsunaCore`).

| Function | Size | Shape | Decision |
|---|---|---|---|
| `context._prepare` (`context.py`) | 888 lines | one pass that builds her turn's `system`, `context` and `manifest` in about twenty blocks sharing some fifteen locals; a few blocks write (memory-tier lapses, three audits, `shown_stops`, `manifest.told`) | split |
| `native_worker.dispatch` | 369 lines | a linear chain of 36 `if method == ...:` statements (no `elif`, no lookup table), each branch's body written in place, ending in `UNKNOWN_BUSINESS_METHOD` | dropped: turning it into a table-driven dispatch is a rewrite of behaviour, not a move, and changes nothing she reads (her reading, line 0303) |
| `client.js` | 1,467 lines | the settings card and other owner UI: a word table, helpers, `apply(ctx)` registrations | dropped: nothing in it reaches a model; a split into files needs DSH's client loader (the owner's); no unit test covers the card, so a proof would be a manual session |
| `CognitionCore` (`index.js`) | 1,377 lines, about 60 methods | the longest, `attachPreset` (197 lines), is an ordered list of about 20 registrations whose order DSH depends on, with model-facing prompt sections | dropped: already a readable list; extracting from it gains little and touches what feeds her prompt |

**The split of `_prepare`.** `_prepare` stays as the ordered list of calls: `_turn_frame` (scene, class, place,
rendered system, the identity heads), `_history_rows`, `_task_and_plan_rows`, then appenders in today's order:
scene blocks, home offers, notes and the scheduled plan, group continuity, tools, affect, turn cues, and `_finish`
(size, wake reason, relabel, `order_context`, the final sha, `manifest.carried`). The shared locals travel in one
small frame object. Nothing is renamed or reworded: no literal she reads and no field changes (her rule, line
0298); key insertion order is part of what she reads (`order_context` keeps unlisted keys in insertion order), so
blocks run in exactly today's order, the three context-sha writes stay, and the names shadowed today (`people`,
`read`) keep their meaning where they are used.

**The proof, at her layer.** A pytest plugin outside the tree (`-p`, nothing tracked changes) wraps
`ContextBuilder.prepare` during the whole suite: at each call it freezes the clock and seeds ids, copies the
in-memory database, runs main's `_prepare` (loaded from `git show main:src/asuna/context.py`) on the copy and the
new one on the real store, and compares `system`, the canonical `context`, the `manifest` and every record the two
runs wrote. Process-level throttles (the tier tick, `anchors_shown`) are saved and restored between the two runs.
The report states how many turns were compared and which `*_from_program` blocks never appeared in them: those are
the blocks this proof did not see, named, not claimed. One existing test changes with it:
`tests/test_adr113_restarts.py:216` matches four lines of `context.py` by their indentation.

**Landing:** one, with a restart; the comparison's report (turns compared, mismatches 0, blocks unseen) goes with
it. A mismatch stops the landing.

**Built 2026-11-10** (her reading, lines 0300 to 0304; branch `claude/adr119-f8`). `_prepare` is the ordered list of
eleven calls (`_turn_frame`, `_history_rows`, `_task_and_plan_rows`, `_scene_blocks`, `_home_offers`,
`_notes_and_plan`, `_group_continuity`, `_tools`, `_affect`, `_turn_cues`, `_finish`); the shared locals travel in
one frame. The dead first `context_sha256` write was kept (a strict move; it is overwritten before any read).
`tests/test_adr113_restarts.py`'s source check now also holds the `manifest.told.host_stops` hand-over, the half its
name promises. Proof, three ways:

1. *Line for line.* Every one of the old body's 746 non-blank, non-comment lines is in the new helpers, in the
   same order when the helpers are read in call order, except one: the pure string `target_note`, now just before
   its one use. The 57 lines added are the frame's reads and writes and seven repeated module imports. No helper
   reassigns a name that a later helper reads from the frame without writing it back (checked by the syntax
   tree). This covers every block, the unseen ones too.
2. *Built twice, compared.* The whole suite and a module of synthetic volume ran with every `prepare` built by
   main's code and by the branch's from the same in-memory database, clock, ids and process state: 37 turns
   (home private 3, group 9, agent line 1, scheduled plan 3, task result 1, note wake 3, heartbeat 4, other 13),
   0 mismatches in content, key order, store writes (24 turns wrote 132 records), raises or process state. Main
   against main over the same 37 turns: 0 (the harness adds no noise); three planted changes (a string, a moved
   manifest key, an extra audit) were caught on all 15 turns of a smaller run.
3. *Not seen by the comparison:* 41 of the 80 `*_from_program` blocks never appeared in a compared turn (among
   them credentials, errands, places, notes, night stage, faults, stickers, switches, peer asides); five
   truncation branches were not reached (progress notes, recent experience, the ideas "more" line, the quote
   list's 「等」, recent thoughts). These rest on proof 1 alone. The volume module's counts show only that a
   branch ran, never a reading of her data. Files on disk were not compared.

**Evidence kept** (her ask, line 0313): `<data>/private/evidence/adr119-f8/`, 48,325 bytes: the harness
(`f8_compare.py`, a pytest plugin loaded with `-p`, and `test_f8_volume.py`), its three reports (`report_ab.txt`
main against the branch, `report_aa.txt` main against main, `report_mutation.txt` the planted changes),
`volume_branches.json`, and `SHA256SUMS`. Installed 2026-11-10 19:36 as `7b31cdc216b4`; the installed
`context.py` has the commit's blob (`0fe96bd8f33f`).

## 9. F14 design: her daytime interval, and clearing a parameter (2026-11-10)

Her choice (agent line 0302, 0303): the interval through `set_policy`, and one rule for clearing every parameter.

1. *The parameter.* `self_development.every_min` joins the core's `set_policy` parameters (`CORE_WRITABLE_KEYS`,
   for every persona; not a package's own `policy_keys`): integer, 360 to 10,080 minutes, its spec shaped as
   `heartbeat.every_min`'s. The 360 bound is `set_policy`'s alone: a persona model's own default may be lower (the
   schema's minimum, 60, stays; it is every persona's). The owner's switches (`self_development.enabled`,
   `night`) stay out of it. `set_policy` is a home, owner-private turn's tool (`POLICY_SET_REQUIRES_OWNER_PRIVATE`
   elsewhere); its description says so beside the `null` sentence.
2. *The retime, once per change.* Her `set_policy` of the interval ensures the daytime plan at once (the tool
   ensures today only after a `heartbeat.` or `rhythm.` key; `self_development.every_min` joins them, through
   `ensure_self_development`). If the policy is written but the retime fails, the answer says both: the value is
   set, the plan is not yet moved, with the code (`NATIVE_SCHEDULE_UPDATE_FAILED` or
   `NATIVE_SELF_DEVELOPMENT_CREATE_INCOMPLETE`), and the rhythm watch tries again within 300 s, since the plan's
   interval still differs; the rhythm
   watch (every 300 s) and each start ensure it too, for a change in the persona model. When the interval it
   computes (policy, else persona model, else `SELF_DEVELOPMENT_DEFAULT_MIN`, 1,440) differs from the live plan's
   `rule.every_seconds`, the native record is updated in place (`/schedule/update`, as `_rhythm_plan` retimes her
   heartbeat), the plan's `rule` and `next_fire_at` follow, and one `rhythm.retimed` audit row (`audit_events`, on the plan's stream) records `from` and `to`: the
   development plan's own, written in `_ensure_development_plan`, without the heartbeat's `drift` key (a retime
   here happens only when the value differs, so it would always be false and say nothing).
   An equal value does nothing. Every path that writes the native record uses the computed interval: today a
   live plan returns early and a missing native record is rebuilt from the plan's old `rule.every_seconds`
   (`_ensure_development_plan`); both take the new one. The plan record (in the `plans` collection),
   its `fire_count` and `fire_count_since` are Asuna's and stay through a retime (DSH keeps the task's id when it rebuilds it), so the
   count goes on; `rhythm.retimed` marks where the interval changed. *Where the next run falls:* DSH rebuilds an `every` task whose timing changes from
   the moment of the change (`createEveryScheduleRecord`: now plus the interval) and takes no anchor, so the next
   run is the moment of the change plus the new interval. With her plan as read on 11-10 (last run 18:18:44, next
   11-11 18:18, 1,440 min): set to 360 at 19:02, the next run is 11-11 01:02; set to 10,080 at 19:02, it is 11-17
   19:02 and tomorrow's 18:18 does not come. A shorter interval never fires at once for the time already passed.
3. *Clearing.* For every `set_policy` parameter (the core's `CORE_WRITABLE_KEYS`, the private `PRIVATE_KEYS` and
   a package's `policy_keys`: whatever `key_spec` accepts), `value: null` removes the key from her policy (the
   key leaves the stored params; no `null` is written, so the source never reads `policy` for a cleared one), so it is read again from
   her persona model, else the core default; `null` is the only clearing value. Every other value is checked by
   the parameter's type and range as today, so `0`, an empty string or `false` for the interval is refused by
   name (no value can be kept while having no effect). For a boolean, `false` sets the value and `null` clears it:
   `rhythm.public_clock` set to `false` answers source `policy`, cleared answers `false` from `core`. Clearing one
   that was never set answers 「本来就没设，无改动」 and is not a failure. After a clear, the parameters whose core default is empty read, when her persona model gives none:
   `self_development.every_min` → 1,440 min (`SELF_DEVELOPMENT_DEFAULT_MIN`; `CORE_DEFAULTS` holds `None`); `rhythm.sleep_window` → no
   sleep window; `rhythm.public_clock` → false. Every other parameter has a core default and returns to it (or to
   her persona model's value).
4. *The answer names the source.* A set or a clear answers one line: the value now and where it comes from
   (`policy`, `model`, `core`).
5. *Words.* The rhythm refusal's 「快慢」 and the page's sentences on her interval are made true in this landing,
   not before: the daytime interval becomes hers to set.

**Landing:** one, with a restart, after F8's. Tests: the range refused outside 360 to 10,080, and `0`, `''`,
`false` refused by name; a change retimes the live plan once, its `next_fire_at` the change plus the new interval
(shorter and longer), and an equal value does not retime; `null` clears and a second `null` answers
「本来就没设，无改动」; the interval cleared answers its value from `model` or `core`; `rhythm.public_clock` set
`false` answers `policy`, cleared answers `core`; a set of the interval retimes at once (not at the watch). Each run on the
old code first.
