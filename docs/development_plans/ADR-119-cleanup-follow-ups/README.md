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
| F6 | Constants on both sides (secret-key pattern, port 8766, 16,000-character limit, test prefix, manifest path) | Each has one source |
| F7 | The scanners (four private-word scanners; a default secret scan that passes on nothing) | A design here first: one scanner or a stated split; no scan passes when nothing was checked |
| F8 | Long functions (`context._prepare`, `native_worker.dispatch`, `client.js`, `AsunaCore`) | Each refactor proven identical at her layer, or dropped with a reason |
| F9 | Paths that need a reading of her data first (revisions without `sections`, old scheduler links, `every_seconds`) | Her data read; each path removed or kept with the count that justifies it |
| F10 | A plan whose dispatch fails is silent on her side (her line 0018, 2026-11-04); her plan view shows `next_fire_at` and `fire_count` empty for the two self-development plans though they fire | Same class as F1: a failed dispatch reaches her as a line in her wording, shown by a staged failure; the two plans show their real values |
| F11 | A silence after a body the turn-end check sent back said 「这一回合正文里一个字都没写」 (her agent line, 2026-11-10 13:22): the receipt counted only the repair stage, so her refused reply was lost while the receipt said nothing was written | **Built 2026-11-10** (her wording, line 0234): on a line whose body is sent at the turn's end, silence after a refused body says 「这一步正文里没写字。这一回合前面那段被打回了、还没发出去：就这样结束，它不会发出去。现在在正文里重写一遍才发得出去（写进 think 的不会发）。」 and echoes the refused text's first 40 characters. Where only `speak` sends, the worker already says what the whole turn sent (`sent`). The check that sends a body back is unchanged. Covered by `stage-view.test.js` "ADR-119 F11: silence after a body the check sent back…"; she reports the first real one |

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

One landing at a time; tests only where a failure would be silent and costly.
