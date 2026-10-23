---
name: asuna-cache-readout
description: Numbers-only readout of a profile's model traffic from its DSH sessions - input (and the part read from cache) and output tokens by brain and by place, and one row per compaction (trigger, how it ended, the summary request's cache share, what it folded, the next request, whether a turn waited). Use it to diagnose slow or costly turns, to check a change to prompts, tools or compaction after it is installed, or whenever a question is "how much was read from cache". It never prints message text, paths or ids.
---

# asuna-cache-readout

A coding agent's readout of what goes into the models, what comes out, and how much of the input was read from cache.
It reads the native profile's DSH session logs, live and archived (`<data>/adr008/home/sessions` and
`<data>/adr008/archive/sessions`, or `<data>/adr008/profiles/<profile>/…` for another profile), and prints counts only.

## Run

```bash
python -I .agents/skills/asuna-cache-readout/cache_readout.py hits
python -I .agents/skills/asuna-cache-readout/cache_readout.py hits --by place --hours 24
python -I .agents/skills/asuna-cache-readout/cache_readout.py compactions --since 2026-01-02T03:04
python -I .agents/skills/asuna-cache-readout/cache_readout.py compactions --brain all --last 50
python -I .agents/skills/asuna-cache-readout/cache_readout.py --selftest
```

Use the project's `.venv` Python (it has `zstandard`). From a worktree, pass the live checkout's data folder with
`--data`. Without `--since` or `--hours` the window starts at the last restart (`back_at` in
`<data>/restart/last.json`), the window for "did the change I just installed work". Times are the machine's local
time. Tokens print in millions with three decimals; `--unit k` or `--unit tokens` changes that. A session folder with no
session files at all is an error (exit 2), never a table of zeros; so is any one folder named with `--sessions` that
holds none.

## The default table

```
Unit: M tokens
Brain, request | Requests | Input | of which cached | Output
Character, turn steps | 53 | 6.739 | 6.273 (93.1%) | 0.032
Character, compaction summary | 1 | 0.173 | 0.172 (99.4%) | 0.009
Action, turn steps | 69 | 6.680 | 6.283 (94.1%) | 0.076
Action, compaction summary | 0 | 0.000 | 0.000 | 0.000
Gate, turn steps | 5 | 0.020 | 0.000 (0.0%) | 0.001
Background summaries, turn steps | 4 | 0.002 | 0.000 (0.0%) | 0.002
Scheduler, turn steps | 0 | 0.000 | 0.000 | 0.000
All | 132 | 13.614 | 12.728 (93.5%) | 0.120
```

These seven rows always print, in this order, at 0 when the window has none, so a row never silently disappears; any
other brain or request the window holds is added after them. `--by place` prints one row per brain, request and place,
the largest input first.

## What it reads, and what it prints

It decompresses and parses every event in memory. It uses only each session's header (`agentPreset`, `cwd`,
`createdAt`), event types and times, `usage`, compaction fields (`compactionId`, `turn`, `sourceCommandId`,
`shadowedTokenCount`, whether `error` is set) and a message's `id`. It prints only counts, times, brain names and places.
A place prints a folder name's short lowercase words (route words such as `group` or `local`) and `#` for every
other part, so ids never print; a route folder named with a lowercase name would show it. A file that cannot be read is
counted, never named. Do not add a column that prints text.

## Definitions

- **input** = everything sent to the model in a request (system prompt, tools, history, the new message):
  `inputTokens + cacheReadTokens + cacheWriteTokens` (DSH's `inputTokens` is the part not read from cache; its token
  meter uses the same sum). **of which cached** = `cacheReadTokens`, its share of input in brackets. Providers that
  cache automatically report no written tokens; when some are written, a line under the table says how many (they are
  counted in input).
- **Each request once.** A forked or seeded session copies earlier events with their ids and times; an assistant
  message counts once by its message id, a summary and a compaction once by the compaction id, in the session where
  they first appeared (sessions in `createdAt` order).
- **brain**: a session whose preset is one of the core plugin's presets (`packages/cognition-core/cordis.patch.yml`:
  action, summary, appraiser, attend, scheduler, recovery) is named by it; any other preset is counted as the
  persona's `character` brain. `attend` is the relevance gate, `summary` the background summaries.
- **place**: the session's working folder under the data folder, `work/<name>` or `channels/<route>` (`/sender` when
  the route gives each member a folder). The character brain's conversations work in `work/<platform>`:
  `work/local-user` is the home Web chat, `work/agent` the agent lines, `work/qq` the QQ conversations together. Other
  brains work where their errand does, often `work/local-user` too. One character session is not split per conversation.
- **request**: `turn steps` are the model calls of turns (assistant messages); `compaction summary` is a compaction's
  summary request.
- **trigger**, as DSH records it on `compaction/start`:
  - `in turn`: the record carries an open turn's number (DSH compacted mid-turn because the context ran over).
  - `turn end`: neither a turn nor a command (the cognition-core plugin's compaction once a turn has ended).
  - `commanded`: the record carries a `/compact` command's id. The Host issues these itself (condensing quiet
    conversations), so `commanded` does not mean a person typed it.
- **end**: `ok`, `failed` (the end carries an error), or `not ended` (still running, or a close that failed; not
  claimed for a file that could not be read to its end).
- **folded**: the tokens the compaction replaced (`shadowedTokenCount`). **next input / next cached**: the first request
  after it. After an `ok` compaction it starts a new prefix, so its cached share is low by nature; after a failed one the
  old prefix stands and stays cached.
- **next turn waited**: a turn began within 5 seconds of the compaction's end, so it was probably queued behind it.
  `-` for an in-turn compaction, which holds its own turn for its whole duration.

## Reading it

- A turn-end or commanded summary request should read nearly all of its input from cache: it sends the conversation's
  own prefix. A low share there means the prefix changed (tools, system prompt, thinking level) or the cache was evicted.
- An in-turn compaction's summary request is often read far less from cache than a turn-end one, and it holds its
  turn while it runs. Many of them mean the turn-end compaction is not keeping ahead.
- A step's low cached share right after a compaction is expected; a low share in a long run of steps is a broken prefix.
  `hits --by place` points at where.
- The `All` row is the sum of the rows above it. The median and end lines under the compaction table cover every
  compaction in the window, not only the rows shown.

## Traps

- DSH writes a compaction's summary record only when the compaction commits. A failed compaction's summary request,
  rejected attempts and the earlier calls of a summary made in steps are counted nowhere: neither in `hits` nor in the
  compaction row.
- A request with no `usage` is not counted. Local servers may report no cache fields; their rows read 0% cached and
  that is not a cache failure.
- A session file last written before the window is skipped (it holds no newer event); events are filtered by their own
  time. A file that cannot be read to its end is counted in a line under the table, with what was readable included.
- The persona's own usage readout lives in its persona package and is hers. It reads the same folders with its own
  rules (its de-duplication is wider), so its numbers for one window need not match these exactly.
