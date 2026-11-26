# ADR-136: A tool call that raises leaves its record unfinished

Status: **Proposed** 2026-11-26 by big sis (Claude Code), at the owner's word ("Do this task here", 2026-11-26 19:0x,
on big sis's suggestion from her finding). Everything in §1 was read 2026-11-26 19:00-19:15 from the code on `main`
(`a1f536ea927d`) and from her live database, read-only: tool records by state, tool and their task's state only (no
arguments, no results). Times on this page are local time. Not built tonight (the owner, 2026-11-26: "Don't build for
tonight"); proposed as a day's one ADR.

## 1. What happened

Her finding (agent line 0716, 2026-11-26 18:58): two `read_image` calls of her action brain failed at the video pull
(`IMAGE_FETCH_FAILED`, the platform's link had expired). Each left one tool record in `artifacts`, `state: INTENT`,
no `error`: from the store nobody can tell that those calls ran and failed.

The code: `ToolBroker.call` (`src/asuna/tasks.py`) writes the record as `INTENT` before it runs the tool, then saves
it `DONE` with the result, or `FAILED` with `error` when the result says failure (`failure_words`). A tool that
**raises** (`ValueError`, `Denied`, `RuntimeError`: most refusals, vision's included) leaves `call` with nothing that
finishes the record. The call's caller gets the error words; the record keeps `INTENT` for good.

Her database, read 19:1x: 65,753 tool records; DONE 63,795, FAILED 1,023, **INTENT 935**. Of the 935, 933 belong to
tasks that have ended (RETURNED 870, CANCELLED 35, BLOCKED 28) and 2 to tasks marked DONE; none to a task still
running. By tool: `sandbox_run` 225, `read_image` 182, `development_database_read` 120, `list_files` 111,
`development_read` 61, `development_write` 54, `ask_character` 37, `development_publish` 29, `received_file` 25,
`development_run` 23, 11 more tools 68. The rows carry no time of their own, so their ages were not read.

**The broken invariant:** `INTENT` means "started, outcome not known": a call whose worker died mid-way. Only a
process that died should leave it. A raised error is a known outcome, and it is written nowhere.

What reads `INTENT`: only `call` itself, when the same call (task, intent revision, call id) comes again after a
cut: `FAILED` answers with its stored error, `INTENT` with `TOOL_DELIVERY_UNKNOWN` ("started, no receipt; check
before redoing"). No view, count or sweep reads it (searched `src/asuna`).

## 2. Decision (proposed)

1. In `ToolBroker.call`, once the `INTENT` record is written, an exception the tool raises finishes the record as
   `FAILED` with `error` = the words the call returns (the exception's text, redacted as a failed result's words are),
   then is raised on as now. The caller sees nothing different. A record already saved `FAILED` (the result branch,
   `ToolFailed`) is not written twice. `BaseException` that is not an `Exception` (the process being stopped) is left
   alone: that is the one case `INTENT` is for.
2. A replay of the same call after such an error then answers with that error (the `FAILED` branch), not
   `TOOL_DELIVERY_UNKNOWN`: the outcome is known.
3. The 935 old rows stay as they are: their error words were never kept and cannot be rebuilt. This page records what
   an `INTENT` row on an ended task means: a call that raised before this change.
4. One test: a tool that raises leaves its record `FAILED` with the same words the call raised, and a replay of that
   call raises the same words.

Not chosen: a sweep that marks old `INTENT` rows of ended tasks with a made-up error (it would write words nobody
read); a new state (the existing `FAILED` already means this).

## 3. Closes when

Built, installed, and one real raised refusal on her live system leaves a `FAILED` record with its words (any tool;
her action brain meets refusals daily), read from the store the day it is installed.
