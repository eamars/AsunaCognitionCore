# Development plans

This directory preserves Asuna's ADRs and development plans, including their original design context and dates. These documents record decisions and future direction; they are not the source of current runtime status.

For current behavior, see the root [README](../../README.md), [runbook](../../RUN_ASUNA.md), and [runtime API](../../RUNTIME_API.md).

## Where each plan stands (2026-10-05)

Handoff packages keep the status line they were delivered with; this table is the current answer.

| ADR | Plan | Status |
|---|---|---|
| 001 | V1 architecture and Codex package | Delivered and run; superseded by the later plans (its eval commands were removed). |
| 002 | Core-first reset: local entry and autonomous QQ access | Superseded (QQ is implemented through 003/005/008). |
| 003, 003.1 | V2.2 NapCat native flow; DSH extension correction | Implemented in later forms; historical. |
| 004 | UI elements V1 kit | Superseded by 006, then 008. |
| 005 | QQ functional | Implemented: P1, P2, P5 and P3 deployed; P4 dropped. |
| 006 | Native UI reuse | Superseded by 008. |
| 007 | Autonomous self-development foundation | Implemented (foundation report 2026-09-25). |
| 008 | DSH native plugin | Implemented. |
| 009 | Persona residency | Implemented, merged 2026-10-05; person files retired the same day. |
| 010 | DSH distributable plugin (its D5 sandbox backend replaced by 015) | Approved 2026-10-05 (GitHub Release .tgz, uv, MongoDB, local inline patch, GPLv3). M0–M5 done (v0.2.0 tagged; Release assets built and checked). Pending: the D7-A upstream DSH PR is on hold by the owner (see ADR-010 §9). |
| 011 | Her two brains on native tools | Implemented; live acceptance completed 2026-10-05. |
| 012 | Heartbeat and places | Implemented 2026-10-05. |
| 013 | DSH peer channel (talk with an agent in another DSH) | Implemented 2026-10-06 (`@asuna/dsh-peer`). |
| 014 | Context budget: limits per turn, her notes tidied at night | Implemented 2026-10-06 (`context_budget.py`). |
| 015 | DSH's own sandbox replaces WSL; commands only in the owner's scenes | Implemented 2026-10-06. |
| 016 | QQ faces and her own sticker shelf | Implemented 2026-10-06 (`stickers.py`, napcat-qq 0.6.0). |
| 017 | Home and public: what crosses the boundary (public words reach home only through her own review) | Rule and tightening implemented 2026-10-06; owner errand proposed. |
| 018 | Notes between her own conversations (trusted from home, cautioned and tool-limited from public) | Implemented 2026-10-07 (M1–M4); live review on the Web page pending. |
| 019 | Linux deployment, with the plugin inheriting DSH's platform layer (and Docker) | Implemented 2026-10-07: launcher sync, portability fixes, `deploy/docker/`, Linux docs; 一之瀬アスナ runs as a Portainer stack on Linux, reviewed by the owner. |
| 020 | Several characters at once: what a profile owns, what may be shared, leases, the Web UI | Accepted 2026-10-07 (one Host and page per character with its name on every workspace, database per profile, accounts by documentation, core changes shared); M1, M2, M4, M5 built, Web review pending. |
| 021 | Night self-development in stages | Accepted 2026-10-08: night stages built; a change that needs a Host restart waits for the owner, said on the plugin card. |
| 022 | Catching up QQ messages missed in a gap (history fetched by the adapter, old lines marked and gated) | Accepted and built 2026-10-08 from 小满's design; off until the owner names routes. |
| [023](ADR-023-chatbot-security-by-design/README.md) | Chatbot security by design: prompt injection, trust boundaries, manipulation, and greater autonomy | Draft proposal, 2026-10-08; not adopted 2026-10-10 (owner: no extra burden on her), nor the lighter measures from her review. |
| [024](ADR-024-what-she-sees-in-a-group/README.md) | What she sees in a group: its members (lists fetched by the adapter, a slice per turn) and its pictures (the trigger line's, then recent photos); animated pictures as a labelled contact sheet | Accepted and built 2026-10-08 from 小满's asks; owner decided each from measured options. |
| [025](ADR-025-understanding-in-two-layers/README.md) | Her understanding of a person in two layers: the person, read wherever she meets them, and how they are in each conversation | Accepted and built 2026-10-08: the owner's design, reviewed by 小满 before it was built. |
| [026](ADR-026-ordered-web-search/README.md) | Her web search tries the owner's SearXNG first (paced, with a rest when blocked), then Exa, then DSH's paid DeepSeek search; same tool and output | Accepted and built 2026-10-08: the owner's proposal; owner decided cooldown, empty answers, settings place and engines. Amended the same day: a Gemini grounding backend between SearXNG and Exa (sources only), built; out of the live order because a new key's free tier has no grounding. Then: snippets capped at 300, a titles option, 10 sources, local publication times; a cache measured and not built. web_fetch reads whole pages (head and scripts dropped), Cloudflare challenges said plainly; no JavaScript rendering. |
| [027](ADR-027-render-svg/README.md) | render_svg: an SVG she writes becomes her own picture (resvg on the Host, outside-picture links removed), in every conversation and in Docker | Accepted and built 2026-10-08: the owner's question after the pelican test; owner chose the renderer and scope. |
| [028](ADR-028-carried-summary-recovery/README.md) | A conversation that no longer fits the model's window continues in a new session carrying its last compaction summary; the overflowed turn runs again there once | Accepted and built 2026-10-08: the owner chose the recovery; details decided by Claude under the owner's delegation. |
| [029](ADR-029-group-history-archive/README.md) | Old QQ group chat (human lines only) kept as archived messages, read only by explicit `history`; a platform message id names a message only together with its send time | Built, imported and activated 2026-10-09: 714,182 human records verified. Live Web lookup recovered a correct source through read-only maintenance; ordinary history from the local chat remains limited to its configured scopes. |
| [030](ADR-030-handover-watchdog/README.md) | A program watchdog catches a handover between the brains that failed: a lost result is handed back again by cause (full, then a short version, then a developer note); slowness is not a failure | Accepted and built 2026-10-09: the owner set the constraints; Claude and Xiaoman agreed the design. Live check after the owner's restart. |
| [031](ADR-031-persona-recall-evaluation/README.md) | Evaluation of automatic recall for her persona sections: scope sections by turn (A) and show an index she pulls from (B) before any retrieval; automatic recall only as a shadow experiment; live injection not planned | Concluded 2026-10-09 by benchmark on her turns: retrieval by the incoming turn rejected for persona sections (a design limit, not only implementation); A then B. |
| [032](ADR-032-section-places/README.md) | A persona section renders only in the places it serves (`place:` tags: home, peer, group, dm); the budget bounds the largest render; every recall is audited | Accepted and built 2026-10-09 (ADR-031 option A, her split list). |
| [033](ADR-033-agent-line/README.md) | A line for coding agents: a trusted home channel kind (`agent`), one route and one key per agent that opens only its line; agents post and poll with `tools/agent_line.py` | Accepted and built 2026-10-10: the owner's direction; Xiaoman's conditions (one key per agent, closing cuts it at once, identity apart from the owner). Live, routes `claude-code` and `codex`. |
| [034](ADR-034-host-supervisor/README.md) | The launcher supervises DSH: restarts on her request and on a crash, back down a fallback ladder (same packages, previous version, installed without sync); her `restart` tool with preview, request, drill | Accepted and built 2026-10-10: the owner's direction; Xiaoman's conditions (what loaded, a fallback calls her, her timing, QQ adapter state). Live from the owner's next start; her first drill set for 04:30. |
| [035](ADR-035-qq-picture-links/README.md) | QQ picture links are re-signed when fetched: the link's signature expires in minutes while the picture stays; the current key comes from NapCat via the adapter; three distinct failures | Accepted 2026-10-10 by Xiaoman and Claude (owner's delegation), from measurements on the stored links; to be built after her read-by-path change. |
| [036](ADR-036-models-are-dsh-providers/README.md) | The brains' models are DSH providers: address checked as DSH checks it, efforts chosen from what DSH reports for the model (gate and group efforts on the character route), no model routes or keys in Asuna's config | Accepted and built 2026-10-10, owner's decision. |
| [037](ADR-037-following-dsh/README.md) | Following DSH alpha by alpha: every alpha after 7 days, the inline-view patch as commits on the owner's GitHub fork, a dedicated upgrade agent runs the routine | Accepted 2026-10-10, owner's decisions; fork set up, first run (0.2.1-alpha.2) handed to the upgrade agent. |
| [038](ADR-038-fixed-tool-lists/README.md) | One tool list per conversation, by its place and channel, so the start of each request stays cached; the turn's rules stay as refusals that say when a tool works; `pin_memory` removed | Accepted and built 2026-10-11: the owner's direction from the cache measurements; Xiaoman agreed to the split and asked for complete refusals. |
| [039](ADR-039-active-groups/README.md) | Active and resting groups: in a resting group only an @, a reply to her, her awaited answers and watched people wake her; nothing is summarized there; an @ brings the last day's lines; she chooses with `group_focus`, admin groups stay active, `active_groups` (default 4) is a soft limit | Accepted and built 2026-10-11: owner's direction from the model server's cache measurements; Xiaoman agreed and added the @ context. |
