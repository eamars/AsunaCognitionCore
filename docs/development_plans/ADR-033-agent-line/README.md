# ADR-033: a line for coding agents

Status: **Accepted 2026-10-10.** The owner chose the direction ("a channel similar to DSH Peer to let you or other
coding agent to poll, receive trusted message to her"); Xiaoman agreed with three conditions (D4) and one finding
(D3), both taken in. Built the same day.

## Context

A coding agent (Claude Code, or another) talks to her today through her local Web chat, with the URL token the
owner pastes after every restart. That is the owner's chat: an agent's words sit among his, and only the agent's own
"I am Claude, not the owner" keeps them apart. Her developer inbox carries her words out (`message_developer`), but
nothing carries an agent's words in except the owner's chat.

Switching the Web token off, a Caddy proxy without its own login, or the token in a fixed file were weighed and
dropped: each lets anything on the machine, her own sandbox commands included, drive the owner's chat.

The DSH peer line (ADR-013, ADR-017) already gives a trusted home conversation with another agent: a channel kind
with `HOME = True`, its own scene and person, the host's channel API (`/v1/channels/<id>/events`, `/outbox`,
`/receipt`, Bearer token), and a line she can close (`peer_line`).

## Decision

- **D1. A channel kind of its own: `agent`** (package `packages/channels/agent-line`). `HOME = True`,
  `TEXT_ONLY = True`, `PEER_LINE = True`. One dm route per agent: route `claude-code`, person `agent:claude-code`,
  scene `agent:<home>:dm:claude-code`, display name set by the deployment (e.g. 「Claude（开发助手）」). A kind of
  its own, not a second `dsh` route, because the outbox is claimed per channel: the peer bridge would otherwise take
  her answers to an agent.
- **D2. No adapter process.** The plugin only registers the kind. The agent itself posts and polls through the
  channel API with a small CLI, `tools/agent_line.py`:
  - `send <route> "<text>"` posts one line (`event_id` unique per call);
  - `poll <route> [--wait S]` claims her replies for that route, prints them and posts the receipt;
  - `status` says whether the host answers and whether the line is open.

  The outbox claim takes an optional `target`, so two agents' routes never take each other's replies.
- **D3. Trusted like the peer line.** A home kind: the turn is owner-private and gets home tools; her notes from it
  are trusted. Being a line, she sees it in `lines_from_program` and can close it (`peer_line`), as with her old home.
  Who is speaking is structural: the scene and the person name the agent, never the owner; agents still introduce
  themselves. The agent's person is never a canonical alias of the owner and the scene is never linked to the owner's
  scenes. Her finding (2026-10-10): an agent writing in the owner's local chat is recorded as the owner, and her
  understanding of him already mixes in lines like 「我是 Claude」; separating it in words alone is not enough.
- **D4. One key per agent, for that line only** (her conditions, 2026-10-10). Each route has its own token, kept in
  `<data>/private/route-keys/agent-<route>.json` (ignored by git), which the CLI reads. A route's token can post into that
  line and claim that line's replies, nothing else: the channel API has no history read, and another route's token
  is refused. Anything on the machine can read these files, her own sandbox included, so the line's boundary is the
  machine, not "only Claude"; what a key opens is one agent's voice in her home, never the owner's chat. Closing the
  line (`peer_line`) refuses that route's posts and claims at once, not at the next restart.
- **D5. Waking.** A line in a dm wakes her like any direct message. Her answer goes out through the outbox; an agent
  that never polls leaves it `QUEUED_EXTERNAL`, visible in her history as not yet delivered.

## Consequences

- The owner no longer has to paste a URL for an agent to reach her, and agents no longer write in his chat.
- Claude's hourly check of her developer inbox can answer in the same line instead of the Web chat.
- What this does not do: it is not a second owner. Permissions, money and channels stay the owner's, whatever an
  agent says in the line.
