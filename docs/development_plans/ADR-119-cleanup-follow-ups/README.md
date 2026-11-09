# ADR-119: What the cleanup found and left: the owner's three decisions and §6's findings

Status: **Proposed** 2026-11-09. Opened by big sis (Claude Code) so that nothing ADR-118 found waits without an exit:
every item below has its own closing condition, and the ADR closes when every item is built or explicitly dropped
with a reason. Nothing is built before its design is written here and she has read the items that change what she
reads.

## 1. The owner's decisions on ADR-118 §7 (2026-11-09)

| # | Item | Closes when |
|---|---|---|
| D1 | Remove `memory_tiers.ENABLED` and its off branches | She has changed her `asuna-render-budget-per-place/budget_per_place.py:144` (it prints the switch); then the switch and its branches go, the two tests that turn it off go or test the one shape, and the suite is green **Built 2026-11-10**: the switch and every branch that read it are gone, with what only the off branches used (`rhythm.selections` and `promotion_candidates`, `context_budget.review_block`, the untiered tool budget); suite 962 passed, js 308 |
| D2 | `integration/test_data_child.py` off the real server | The data child's behaviour is tested without a real server (unit layer, in-memory adapter), the integration file keeps only adapter promises, and AGENTS.md's rule needs no exception. The child's deadline on a real server is no longer covered: say so here when built |
| D3 | `routes.appraiser` and `routes.action.summaryEffort` on the settings card | Both show and save on the card through DSH's own facilities, shown in the isolated review profile, and the card's check covers them |

Left as is by the owner: the four channel API clients (ADR-118 §7.2).

## 2. ADR-118 §6's findings, in order

| # | Item | Closes when |
|---|---|---|
| F1 | Errors that end silent where she reads (forward, outbound media lists, `scene_links._scenes`, `credentials.scrub`) | First, at her ask. Each read that fails says so in her wording; `credentials.scrub`'s failed refresh gets a designed rule (fail closed or keep the last set); a staged failure of each shows the new text |
| F2 | `QUERY_UNAVAILABLE` for a child that cannot start | One sentence for "cannot start" in her wording; a staged start failure shows it |
| F3 | The identity resolver's leftovers | She has seen the new result shape; what she asked to keep (ADR-118 §6) stays |
| F4 | One time parser (44 places in 31 files) | One parser, one written form, one failure rule; a design here first because it touches every stored time she reads |
| F5 | One fake for the offline checks | The three case modules stand on `fake_collections`; designed and scheduled with her (her checks' content) |
| F6 | Constants on both sides (secret-key pattern, port 8766, 16,000-character limit, test prefix, manifest path) | Each has one source |
| F7 | The scanners (four private-word scanners; a default secret scan that passes on nothing) | A design here first: one scanner or a stated split; no scan passes when nothing was checked |
| F8 | Long functions (`context._prepare`, `native_worker.dispatch`, `client.js`, `AsunaCore`) | Each refactor proven identical at her layer, or dropped with a reason |
| F9 | Paths that need a reading of her data first (revisions without `sections`, old scheduler links, `every_seconds`) | Her data read; each path removed or kept with the count that justifies it |
| F10 | A plan whose dispatch fails is silent on her side (her line 0018, 2026-11-04); her plan view shows `next_fire_at` and `fire_count` empty for the two self-development plans though they fire | Same class as F1: a failed dispatch reaches her as a line in her wording, shown by a staged failure; the two plans show their real values |

One landing at a time; tests only where a failure would be silent and costly.
