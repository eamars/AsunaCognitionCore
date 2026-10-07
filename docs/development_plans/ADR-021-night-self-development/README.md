# ADR-021: Night self-development in stages

Status: **Accepted in part** 2026-10-08. Night stages (D1–D3) built 2026-10-08. Putting a change that needs a Host
restart into effect without the owner (D4) is **open**: a first design (the Host asks the launcher to restart it when
idle) was withdrawn the same day, before it was committed, because it did not answer supervision, health or Docker
(§4).

## 1. Context

On the night of 2026-10-07 小满 planned seven half-hour slots (fix, verify, fix, verify…) as ordinary reminders. None
of them could carry the development tools: only her daily self-improvement turn and the owner asking in a private chat
grant them (ADR-011 §6.1, `grants.development_granted`). Her action brain reported 「这一拍仍然没有开发回路」 twice and
the work waited for Claude. The owner, who had already told her that stacking work is risky, asked for a more frequent
self-development schedule at night that allows multi-stage work and evaluation.

## 2. Decisions (owner, 2026-10-08)

- **D1 — Night stages.** Inside a window on her clock a self-improvement turn comes every N minutes. Each is a real
  self-improvement turn (the development grant, her ideas, her recent tasks and publications). Default 01:00–06:00,
  every 30 minutes.
- **D2 — One thing per stage, decided by her.** A stage does one change, checks the last one, or nothing. The
  program never stacks: a stage is skipped (and the reason recorded on the plan) while a self-improvement turn or its
  task is still at work, or while one of her publications is not running yet.
- **D3 — Hers to tune.** The window and pace are her policy keys within limits; the owner can switch the stages off
  (`self_development.night: false`).
- **D4 — A change that needs a Host restart is put into effect when she is idle.** Open (§4).

## 3. As built

- `ScheduleService.ensure_night_development` registers one native recurring tick every 10 minutes
  (`plan-asuna-self-development-night`, `NIGHT_TICK_SECONDS`); `_night_stage` decides at each tick: `NIGHT_OFF`,
  `OUTSIDE_NIGHT` (her rhythm zone, `self_development.night_start_hour` + `night_hours`), `NOT_DUE`
  (`night_every_min` since `last_stage_at`), `STAGE_BUSY` / `PUBLISH_NOT_RUNNING` (`night_stage_busy`), else
  `ENQUEUED`. A change of her keys applies at the next tick; there is no record to re-arm.
- The stage is `offer_self_development('self-development:night:<occurrence>', stage=…)`; her context gains
  `night_stage_from_program` (window, pace, last stage of the night, the rules) (`rhythm.night_stage_block`).
- Publication receipts are the source for "not running yet": `publication.activated` marks them ACTIVE, and a
  newer publication of a project marks older ones SUPERSEDED. One receipt from 2026-10-04, older than that marking,
  still read HOST_RESTART_REQUIRED and was marked SUPERSEDED by hand.
- Python publications already take effect without the owner: the worker is replaced when idle and the host offers her
  a self-improvement turn once the change runs (`host._complete_activations`). Until D4 is settled, a stage that
  publishes a JS, composition or dependency change stops the later stages until someone restarts the Host.

## 4. D4: why the first design was withdrawn, and what a design must answer

The withdrawn design: once a minute the plugin wrote a restart request beside `activation.json` when one of her
publications was HOST_RESTART_REQUIRED and nothing was running; the launcher watched for it, stopped DSH, installed
the selection and started DSH again in a loop. The owner's questions (2026-10-08) it did not answer:

- **Who brings the Host back.** On Windows the launcher runs in a console or a preview server and nothing supervises
  it: a Host that fails to start after the restart leaves her down until a person notices. In Docker the container
  survives the restart (the launcher is its main process), but a Host that fails to start ends the container, and
  `restart: unless-stopped` re-runs the entrypoint with its own checkout sync, a second path the design had not
  considered.
- **Health while it happens.** The Docker health check only fetches the page; during a restart and after a failed
  one nothing reports what the Host is doing, why, or that a published change is the reason.
- **Proof it came back with the change.** The design trusted the next start; the existing fallback (a selection that
  never confirms running for two starts is replaced by the previous ACTIVE one) was never exercised by it.

Directions to evaluate before deciding:

1. **No process restart:** DSH's plugin manager can apply a plugin change in place when its hot-reload service
   (`dsh-hmr`) is mounted (`application: "applied"` instead of `"restart-required"`). If the core plugin can be
   reloaded that way, her change takes effect without the Host going down.
2. **A supervisor that owns the Host's life:** restart on request and on failure with a bounded backoff, a durable
   state of its own (running, restarting for a publication, failed and why, rolled back) that the Web card and the
   Docker health check read, and the rollback to the previous ACTIVE selection exercised in tests; the same
   supervisor in Docker and on Windows.
3. **The owner restarts:** stages that need a Host restart stop the night; the owner restarts in the morning, and the
   Web card says a restart is waiting and why.
