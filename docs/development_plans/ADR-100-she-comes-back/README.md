# ADR-100: She comes back

Status: built 2026-10-27.

## What happened

On 2026-10-27 she was down twice while the DSH Host ran on and looked healthy: from 06:29:45 to 08:42 NZDT, and
again from 08:44:22 until the owner started her once more. No log line said why.

- **Trigger.** The owner's computer loses its Ethernet link for about four seconds, a few times a day (37 times in
  the 14 days to 10-27, Windows System log, adapter event 14). Each drop resets the open MongoDB connections:
  pymongo raises `AutoReconnect` (`WinError 10054`).
- **Where it hurts.** A drop while she is fully up costs at most the turn that was running. The drops at 02:03 and
  03:39 that night caused no error at all. A start is different. After the Python worker reports
  `runtime.ready`, the core plugin's `ready()` still makes worker calls for about a minute and a half. Both drops
  that day fell inside that window: 97 s after her own publication's worker restart (06:28:08), and 96 s after the
  owner's start (08:42:46).
- **Why she stayed down.** `ready()`'s failure handler closed the worker and kept the rejected promise in
  `initializing`, so every later `ready()` returned the same failure and nothing tried again. The worker's evidence
  shows the closing: `host.input_closed`, then `DSH_HOST_DISCONNECTED` for the turn that was running.
- **Why nothing said so.** At 06:29 the failure went through `logger.warn(String(error))` as `Error: AutoReconnect…`.
  The log sink kept only lines that start with `Asuna`, so the line reached no file. At 08:44 a direct stderr write
  happened to show it.
- **A second fault, found on the way.** A worker that exits was never restarted on its own. Since 10-13
  (`5cd5e112`) the class has a method `disposed(agent)`, so `workerFailed`'s check `!this.disposed` was always false.
  Its cap `lifecycle.restarts < 3` also counted every in-place restart, so any three, her publications included,
  would have ended crash restarts even with the check working.

The broken invariant: **a fault that passes must not leave her down while the Host runs on, and a fault must not be
silent.**

## Decision

1. **A failed start is tried again.** `ready()` clears `initializing` when the failed attempt is still the current
   one: its callers see the failure, and the next call starts afresh. `startAgain` writes `Asuna worker could not start
   (attempt N): <error>; trying again in X s` and schedules the next try after 5, 15, 45 and 135 s, then every
   300 s (`START_RETRY_SECONDS`), never giving up. A tick does nothing while a start or restart is under way or once
   the plugin is unloaded. A successful start clears the count. A profile still waiting for its settings
   (`unconfigured`) is not retried.
2. **A worker that exits is restarted, with the same delays.** `workerFailed` takes its delay from the count of
   failures in a row instead of a cap on all restarts. A restart that fails logs `Asuna worker restart failed`.
3. **The plugin's unload flag is `unloaded`**, so it cannot shadow the agent-disposal handler `disposed(agent)`.
4. **The log sink keeps every line an Asuna package's logger writes** (the logger's name starts with `asuna`),
   whatever its text, as well as any line that starts with `Asuna`. A line that does not start with `Asuna` carries its
   logger's name in brackets. The worker's stderr (its tracebacks) now reaches `restart/host.log` too.

A turn that is running when the link drops can still fail; its inputs that had not started are replayed by the next
start. With a few drops a day, we accept that. A watchdog in the supervisor, outside DSH, would also catch causes we
have not met yet. It waits until one appears.

## Evidence

The evidence is in this ADR: the times above, and the worker reports `.runtime/reports/native-host-5eb5d150a1`
(06:28–06:29) and `.runtime/reports/native-host-ee5de0aa9e` (08:43–08:44), which the runtime keeps as its own
reports. No other file is kept.

## Tests

`packages/cognition-core/test/start-retry.test.js` (a failed start retries further apart each time; a caller after a
failure starts afresh; a tick during a start, a restart or after unload does nothing; an unconfigured profile is not
retried; a worker that exits is restarted although other restarts happened, and not after unload). Run against the
code before this ADR, these tests fail, except the unconfigured case.
`packages/cognition-core/test/log-sink.test.js` (an Asuna logger's unprefixed line is kept with its name; another
plugin's line is not).
