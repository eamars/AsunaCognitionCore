# ADR-022: Catching up QQ messages missed in a gap

Status: **Accepted and built** 2026-10-08. Design by 小满 (her research of 2026-10-07 and handoff of 2026-10-08);
the owner accepted her demand as it stood; built by Claude.

## 1. Context

On 2026-10-08 the Host was down from 09:08 to 11:15 (local): it ran as a child of the Claude desktop app, which
restarted. QQ does not replay events, so every message of those two hours was lost to her: she was "blind" and
only found the gap afterwards. Earlier gaps (adapter restarts, NapCat restarts) lost messages the same way.

Her research (`napcat-catchup-plan.md` in her workspace, read-only probes against the live NapCat 4.18.0):

- There is no catch-up endpoint and no replay switch in NapCat (probed names answer retcode 1404; the docs and the
  OneBot config schema have none). History is the only way: `get_group_msg_history`, `get_friend_msg_history`.
- A history row has the same fields as a pushed message event, so it can go through the existing inbound path.
- No time parameter: a page starts at a `message_seq` anchor (included) and goes newer; seqs are not contiguous.
  Rows come oldest first; `time` is UTC epoch seconds. A friend's history includes her own lines.
- Push and history give the same `message_id` (47 of 47 in one group on 2026-10-07, and one `get_msg` check),
  so the host's event id dedups a caught-up line against the pushed one. `message_seq == real_id == message_id`.
- The old home's own catch-up (2026-09) taught: the cursor must be a time, not a message number (ids are not
  monotonic); a reply must be fed after the line it quotes; a long-running process's memory is a snapshot, so the
  durable store is the authority on what was seen.

## 2. Decisions

- **D1 — Where:** the adapter fetches; the host only learns that a line is late. Only routes the owner names in
  `adapter.catchup.routes` (route ids, `auto-group-<id>` / `auto-dm-<id>` for automatically admitted targets, or
  `"all"` for the configured routes); off by default. Reading history is a real widening of what the
  adapter reads (until now `get_msg` was limited to its own sent message), so it stays inside authorized routes.
- **D2 — When:** once the adapter is READY, and whenever the event socket comes back after a drop.
- **D3 — From where:** a per-route cursor (time, with the platform seq) of the newest message accepted on that
  route, pushed or caught up, in the adapter's data folder (`catchup/cursors.json`, atomic write, flushed every
  30 s and at shutdown). Paging goes forward from the cursor's seq; without a cursor, the newest page. Never
  further back than `lookback_hours` (1–6, default 6). At most 5 pages of 100; beyond that the run says it was
  truncated.
- **D4 — How:** rows are fed oldest first through the same gate, spool and identity lookups as a push, marked
  `raw.asuna_catchup` (`reason`, `fetched_at`). `disable_get_url` is always on (an old picture's link has
  expired). Her own lines are dropped.
- **D5 — What she sees:** the host keeps the mark (`kept_raw`). A caught-up line was said at its `occurred_at`:
  the line she reads shows that time with 补读, and the history window and the relevance gate count from it
  (`caught_up.said_at`). An @ of her or a reply to her in a caught-up line older than 5 minutes does not wake her
  directly: it is `catchup_mention`, through the relevance gate, and a full turn is told the line is old and to
  look at what happened since. An awaited answer is never taken from a stale caught-up line.
- **D6 — What was not needed:** her old home kept a separate "already woken" ledger. Here each platform message is
  one host event and one episode, decided once at ingest, so a line cannot wake her twice.

## 3. As built

- Adapter 0.7.0: `qqadapter/catchup.py` (`Catchup`: `note`, `request`, `loop`, `run`), `Config._catchup`,
  `OneBot.on_up`, `service.Adapter` wiring; self-test `catchup_*`.
- Host: `src/asuna/caught_up.py`; `channels.kept_raw` and `group_context`; `attend.GATED['catchup_mention']`
  and `recent`; `context.catch_up`, history stamps and `caught_up_from_program`; `People.transcript`.
- Tests: `tests/test_catchup.py`.

## 4. Rollout (her plan)

First the owner's DM route, then the quietest group; watch the host's duplicate counts and the adapter's
`inbound_rejected.jsonl` (a pushed and a historical rendering that differ would be refused as a content conflict,
harmless but visible). Not yet verified: a DM's history against its pushes, and whether NapCat pushes lines this
account sent from another client.
