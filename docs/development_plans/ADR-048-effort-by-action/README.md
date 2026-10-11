# ADR-048: Thinking effort by what she is doing, not by the conversation

Status: **Proposed 2026-10-12.** Drafted by Claude from the owner's request; Xiaoman reviews. Nothing is built. No
server change is needed; the probe in step 4 needs the owner's GPU time.

## Context

The owner, 2026-10-12: within a conversation the thinking effort is fixed. A group visit runs in that group's own
conversation, so it gets the group level even when the visit is meant for learning. Consider letting certain actions
raise the effort for a while, not only visits but other tasks too. This is a mechanism change, so it gets its own ADR.

How effort is chosen today (`packages/cognition-core/src/index.js`, `stageEfforts` and `effortFor`): the plugin sets
the effort on every model request. The relevance gate gets the route's `attendEffort` (low on the live profile); any
character request in a group conversation gets `groupEffort` (medium); everything else gets the route's
`reasoningEffort` (high). So effort follows the kind of conversation. A reply to an @, a chain, a visit to start a
topic and a visit only to write notes all run at medium; home and her night turns at high.

The cost of changing it inside a conversation: the local model server writes the effort as a sentence in the prompt.
By default that sentence sits in the first system message, at the top. A request whose effort differs from the
conversation's earlier requests then no longer matches the cached prompt, and the whole conversation is read again:
about 25 s for a 150k-token group conversation against about 3 s from the cache (measured 2026-10-11, ADR-049), and
once more when the next request switches back. Today that never happens, because each conversation keeps one level.
The server has an opt-in placement, `effort_position: "end"` (off on the live server): the conversation is rendered
with the default effort at the top, and a different effort follows in a short system turn just before the answer, so
a switch keeps the cache. The thinking budget (`thinking_token_budget`) is a request field and never touches the
prompt.

The model-server session's review of that placement (2026-10-12, from the server code and its upstream issue): the
default at the top is the model's highest level, so every conversation would carry "think carefully" at the top and a
medium or low request would add a contradicting sentence at the end. Whether the model lets the later one win is not
measured anywhere; if it does not, her group conversations, medium today, would think at the highest level and
answer more slowly. Turning it on also needs a server restart, after which each conversation is read once more.

## Decision (proposed)

1. **Effort follows the operation.** Each stage the program opens names an effort class, and the plugin maps the class
   to a level from the route's settings, the way `attendEffort` and `groupEffort` work now. First table:
   - replying in a group (an @, a gated join, a chain, an awaited answer): the group level, as now;
   - a visit with intent `write_notes`, and the part of her daily reflection that learns from groups (ADR-049): a
     **study** level, high;
   - other visits (start a topic, share a picture, check in): the group level;
   - night turns, home: the route's level, as now;
   - the relevance gate: low, as now;
   - delegated action tasks: the action route's level for now; by task kind only if measurement asks.
2. **Hers to raise, later and only if she wants it:** a categorical choice that makes the rest of one turn, or one
   delegated task, think harder. Not in the first step.
3. **How the level reaches the model, without touching the cache.** The effort sentence at the top stays as it is
   per conversation. Inside a conversation the operation changes only what sits at the end of the prompt:
   - the thinking budget of the request (a cap: it can make a reply think less, not more than the model would);
   - a short line in the turn's own stage text, which is already at the end ("这次是来学的，想透了再写"): it stays in
     the history, so the cache holds.

   Both need no server change. The server's effort-at-the-end placement is the fallback, only if these do not move
   her thinking and only after a measurement shows the model follows a level given at the end.
4. **Measure first, off the live server.** The model-server session proposed a short probe (about 15 minutes of GPU
   when the owner says it is free; test requests on the live server would push her conversations out of the cache):
   group-chat replies and hard questions with exact answers, at the native levels, with a budget cap, with the stage
   line, and with the level at the end, comparing thinking length and correctness.
5. **Settings.** The levels live with the route, like `attendEffort` and `groupEffort`. A `studyEffort` field on the
   existing route settings card is a UI addition and needs the owner's approval; until then it is profile
   configuration only.
6. **Measure live before and after:** cache misses by idle time in group conversations must not rise; thinking length
   and step time on study visits; what the visit produced (notes written, nothing, a line said).

## Open questions

- Whether the owner gives the GPU time for the probe in step 4.
- Which operations Xiaoman wants deeper, and whether she wants the choice in step 2 at all.
