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
| F1 | Errors that end silent where she reads (forward, outbound media lists, `scene_links._scenes`, `credentials.scrub`) | First, at her ask. Each read that fails says so in her wording; `credentials.scrub`'s failed refresh gets a designed rule (fail closed or keep the last set); a staged failure of each shows the new text |
| F2 | `QUERY_UNAVAILABLE` for a child that cannot start | One sentence for "cannot start" in her wording; a staged start failure shows it **Built 2026-11-10** (her wording, line 0230): three sentences where there was one. `QUERY_CANNOT_START` for a child that will not start: a start is tried at most once a minute, and `lane_faults` keeps one row per signature and hour with its count, so repeats are counted, not each recorded; `QUERY_CLOSING` while the worker stops; `QUERY_UNAVAILABLE` now only for a child that died in the call. Before this landing `QUERY_UNAVAILABLE` meant any of the three: a record older than it cannot tell a lasting fault from a passing one. The staged start failure is `tests/test_data_child.py` (a child that fails to start answers `QUERY_CANNOT_START` and records `start_failed`) |
| F3 | The identity resolver's leftovers | She has seen the new result shape; what she asked to keep (ADR-118 §6) stays |
| F4 | One time parser (44 places in 31 files) | One parser, one written form, one failure rule; a design here first because it touches every stored time she reads |
| F5 | One fake for the offline checks | The three case modules stand on `fake_collections`; designed and scheduled with her (her checks' content) |
| F6 | Constants on both sides (secret-key pattern, port 8766, 16,000-character limit, test prefix, manifest path) | Each has one source |
| F7 | The scanners (four private-word scanners; a default secret scan that passes on nothing) | A design here first: one scanner or a stated split; no scan passes when nothing was checked |
| F8 | Long functions (`context._prepare`, `native_worker.dispatch`, `client.js`, `AsunaCore`) | Each refactor proven identical at her layer, or dropped with a reason |
| F9 | Paths that need a reading of her data first (revisions without `sections`, old scheduler links, `every_seconds`) | Her data read; each path removed or kept with the count that justifies it |
| F10 | A plan whose dispatch fails is silent on her side (her line 0018, 2026-11-04); her plan view shows `next_fire_at` and `fire_count` empty for the two self-development plans though they fire | Same class as F1: a failed dispatch reaches her as a line in her wording, shown by a staged failure; the two plans show their real values |

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

One landing at a time; tests only where a failure would be silent and costly.
