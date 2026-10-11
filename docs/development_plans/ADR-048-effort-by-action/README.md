# ADR-048: Thinking effort by what she is doing, not by the conversation

Status: **Proposed 2026-10-12.** Drafted by Claude from the owner's request; Xiaoman reviews. Nothing is built. Step 3
depends on a model-server setting that is the owner's decision.

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
3. **Only cache-safe with the effort at the end.** Before step 1 is switched on, the owner turns on
   `effort_position: "end"` on the model server. Each conversation then reads itself once more on its first request
   after the switch (a group's top changes from no sentence to the default one), and never again for an effort
   change. Without it, a different effort inside a shared conversation costs two full re-reads per switch; the
   fallback is to keep effort per conversation, as today, and vary it only where an operation has its own session
   (the gate, delegated tasks).
4. **Settings.** The levels live with the route, like `attendEffort` and `groupEffort`. A `studyEffort` field on the
   existing route settings card is a UI addition and needs the owner's approval; until then it is profile
   configuration only.
5. **Measure before and after:** cache misses by idle time in group conversations must not rise; the step time of a
   study visit at high; what the visit produced (notes written, nothing, a line said).

## Open questions

- Does the model follow an effort given in a short system turn at the end as well as one at the top? A server-side
  probe, asked of the model-server session together with its cache deep dive.
- Which operations Xiaoman wants deeper, and whether she wants the choice in step 2 at all.
