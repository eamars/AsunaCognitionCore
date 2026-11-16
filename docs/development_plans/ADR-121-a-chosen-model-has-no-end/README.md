# ADR-121: A model chosen for one session has no end

Status: **Proposed** 2026-11-09 (laid down); designed 2026-11-16 by big sis (Claude Code). The owner's idea of
2026-11-07; he chose it as the next ADR on 2026-11-14. Her ask on it (agent line 0496, 2026-11-14): keep a read-only
"which model this session runs" on the page, as one of her ways to check an install and a route; no interaction for
it. Designed against `main` at `009a637ba502`; every count in §1 was read 2026-11-16 17:42-17:48, read-only, from
her session files (structure only) and her profile's settings. Times on this page are local time.

## 1. What is known

**How a session's model is chosen (code).**

- DSH 0.2.2 fixes a step's provider, model and level when it prepares the step: the session's last model selection
  (a `model/selection` record), else its last request's, else the options it was opened with.
- DSH's model picker (`dsh-client-ui-model-selection`, the composer's `conversation.input.model` seat) and its
  `/model` command both write such a selection (`sessions.selectModel`). The seat shows the selection's model and
  level on its button; DSH disables the button only for a removed, inert or offline session (`modelSeatLocked`).
- The plugin selects its own route before each stage (`settings.js` `selectFor`) and marks that selection as its own
  (`asuna/route`). Any other selection is "deliberate" (`settings.js` `deliberate`) and stays authoritative for its
  session for good: `index.js` `requestRoute` then sends every request of that session on it, at its level, with no
  stage level (the group and gate levels on the settings card do not apply) and no 高 for a job. Nothing ends it.
- The recovery session (`recovery.js`, the owner's repair path through the publication floor) honours a deliberate
  selection the same way: there it is the owner's choice for one repair.

**What there is today (her profile, 2026-11-16).**

- 2,784 session files: 68 character, 1,800 action, 795 summary, 120 relevance gate, 1 scheduler. 4 carry any
  model selection at all.
- **One pin**: one character session (the owner's test of 2026-10-25 00:30), two selections made in DSH, none by
  the program after them; the session is in use today. It names the provider and model of her character route; its
  requests run at the pin's level, `medium` (the card's character level is `high`, its group level `medium`). So it
  costs little today, and it would not follow any change of model or level on the settings card: that is the gap.

## 2. Closes when

No session of hers stays on a model that nobody has chosen for it now. Either the widget is gone from her sessions,
or a pin has an end (a visible way back to the program's route, or an expiry); in both cases the existing pins are
found and cleared with the owner. Shown first in an isolated review profile, then on her profile.

## 3. Decisions

**D1. Her sessions always run on the program's route.** `requestRoute` stops reading a selection made in DSH: every
request of a character, action, summary, appraiser or gate session takes the lane's route, its stage level and 高 for
a job, as one with no pin does today. A selection made anyway (the `/model` command, the session API) lasts until the
next step, when `selectFor` selects the program's route over it. The root gap is the rule "a selection not ours rules
for good"; the rule goes, so no path can make a pin, and the one there is ends at its session's next step. The
recovery session keeps its rule (the owner's choice for one repair; its session ends with the repair).

**D2. The seat stays and shows; it does not open.** On those sessions the client renders DSH's own model seat with
DSH's own `locked` flag set: the button shows the model and level of the session's selection (the program's, from
D1), disabled. That is her read-only "which model this session runs". Every other session (recovery, scheduler, any
non-Asuna session) renders DSH's seat unchanged. The same wrapper as DSH's permission picker in her two brains'
sessions (`client.js`, since 2026-10-05): DSH's component, DSH's injection, DSH's locale; no new UI and no new words.
The seat shows the selection, so between a change on the settings card and the session's next step it shows the
model of the last step.

**D3. The existing pin is cleared by D1, told to the owner.** No session file is edited: at that QQ session's first
step after the install the program selects her route over the pin, and the seat shows it. The owner is told before
the install that his 10-25 test pin ends with it.

**D4. Nothing she reads changes.** No tool, no description, no guide text, no prompt: the route and level her turns
run on are what her settings card says, now in every session. F8 has nothing to ask; the tool budget is unchanged.

**Answers to the page's open points (§3 of 2026-11-09).** Remove the widget or give a pin an end: both, in effect;
the seat stays as a read-only label (her ask) and no pin outlives a step. An Asuna setting or a DSH change: Asuna's,
in the plugin; DSH is untouched. How many pins: one (§1).

## 4. What could go wrong

| Failure | Answer |
| --- | --- |
| Someone picks a model by `/model` in her session and expects it to hold | It holds until the next step; the seat shows the program's model again after it. Her sessions have one route, the card's |
| The owner needs another model for her when the route's is down | The settings card's route, for every session at once (as for any other change of model); the recovery session keeps its own picker |
| A session not hers loses its picker | The lock applies only to sessions opened with her presets; every other session renders DSH's seat unchanged, as the permission wrapper does |
| The seat shows a model that is not the one the next request takes | Only between a card change and the next step (the seat shows the selection). The next step selects the new route and the seat follows |
| The preset list on the client is not loaded yet | The seat renders DSH's own until the list arrives (one call at page load), as the permission wrapper does |
| A future DSH changes the seat's `locked` prop | The wrapper passes DSH's own prop; if DSH drops it, the seat is DSH's live picker again and D1 still holds every pin to one step |

## 5. Build

- `index.js` `requestRoute`: no `deliberate`; the recovery lane keeps its own in `recovery.js`.
- `client.js`: a `conversation.input.model` wrapper (priority -1) that renders the shipped seat with `locked: true`
  for her routed presets; `api.js` gives the client that list (her persona presets and `PRESETS`).
- Test: the existing case "a model chosen in DSH for this conversation stays authoritative"
  (`native-loop.test.js`) is turned round: after a selection in DSH, the next turn runs at the program's level. The
  recovery case stays as it is.
- Docs: none describes a deliberate selection. `DSH_API.md` lists the `asuna/route` record, which stays: the program
  still marks its selections, and the recovery session still tells them from the owner's.

## 6. How it is shown

1. An isolated profile on a stub model (造的): a character session given a selection through DSH's session API; its
   next turn's request on the program's route and level, the pin replaced by the program's selection; the seat on
   her session disabled with the model's name, the seat on a non-Asuna session live. The page row is read on the page
   itself this time (ADR-131's demo page stayed behind DSH's preview notice).
2. Her profile after the install: the pinned QQ session's first step after it carries the program's selection; the
   count of §1 run again (no session whose last selection is not the program's, beyond a recovery session); the seat
   read on her page by the owner or her.
</content>
</invoke>
