# ADR-047: Telling bots from people in her groups

Status: **Proposed 2026-10-11.** Drafted by Claude from the owner's brief and Xiaoman's first four points; she
reviews and rewrites it on 2026-10-12. Nothing is built.

## Context

The owner asked Xiaoman for a bot-detection skill: whether a group member is a bot, worked out from the bots she
already knows (most run AstrBot or MaiBot; one runs a Hermes-based QQ bot; she herself runs on Asuna), sorted and
classified, with **passive detection** and **active probes**. The probe loop he sketched: her character brain sends a
probe, the reply goes to the action brain, which judges from logs or past history and picks the next probe. Static
source comparisons of several bots are in a local folder outside this repository. He asked for this ADR.

His rulings the same night:

- **Probing only, and friendly.** No prompt injection, no jailbreaks, nothing harmful, no flooding, nothing that
  tricks a member who turns out to be a person.
- **Scope of study:** AstrBot, MaiBot and the Hermes QQ bot in full, two others briefly. His own designs are out of
  scope.

Xiaoman's first points (from her note to the developer inbox, then the agent line):

1. A probe has to wait for an answer across turns: who is being tested, which step, how long to wait, whether
   silence counts.
2. Who judges: she accepts mechanical readings from elsewhere, but not a second mind deciding for her. Two columns,
   not merged.
3. Probes cost something socially: an @ to the wrong person must be wrapped up, a cold group may leave it hanging.
4. Validate offline first: replay group history for a hit rate before any live probe.

And one more: a conclusion written to her notes on a person must say it is undecided and comes from probing, because
the person layer can surface in another group, and an unmarked guess becomes fact within days.

What already exists and fits:

- **Waiting:** when she @s or replies to someone, the program waits three minutes for their answer and wakes her
  with it (`await_answer`); her waiting list keeps them for an hour (ADR-041).
- **A session for the judging:** a delegated task keeps its own conversation; `message_action` continues the same
  task with all that came before. One task per person under test is the probe session.
- **Her notes on a person:** `understand_person`, layer `person` (everywhere) or `here` (this group).
- **The record:** every line with its time, sender and reply target; group member lists with join and last-spoke
  times (`group_members`); the action brain's history search returns lines with their times.

## Decision (proposed)

1. **One skill, two halves.** The skill (hers, in her persona package) holds the catalog of framework behaviours, the
   procedure and the social rules. The program supplies the passive half as computed readings; she runs the active
   half.
2. **Passive readings are computed by the program, not guessed by a model.** Per person and group, from stored lines:
   how fast they answer when addressed; bursts (several lines in seconds with no one in between); the hours they are
   active; exact repeats of their own or others' lines; command-prefixed lines; regularity of length and format;
   join date and last spoke. They reach the action brain only as interpreted words in tiers (AGENTS.md: program
   statistics reach a model as text, never raw numbers). First form: a read-only action-brain tool that returns one
   person's readings in one group.
3. **The catalog** lists, per framework, what another member can see in chat, each with its source evidence: what
   makes it reply, its timing, how it splits and shapes messages, fixed command answers, error texts that leak, how
   it answers "are you a bot". *(Filled in from the source study; see Catalog below.)*
4. **The active loop uses what exists.** She posts a friendly line to the person (an @ and something she would say
   anyway); the program waits and wakes her with the reply and its time. She delegates once per person ("is X a
   bot?") with the reply; each later step is a `message_action` to the same task, so the task carries the step,
   the earlier probes and the answers. Silence is a reading too: no answer within three minutes, or within the hour.
5. **Two columns, never merged.** The mechanical column (program readings plus catalog matches) is what the action
   brain reports; the semantic column (does the person take a joke, does the text feel templated) is hers. The action
   brain writes observations, never a verdict.
6. **Conclusions go to her notes on the person,** layer `person`, marked undecided and probe-only until she decides
   otherwise. Never announced in a group; what she does with a conclusion is hers.
7. **Social rules, in the skill.** Friendly only. At most one probe line per person per day, and a few steps per
   session. Never in a group that has gone quiet, never at someone she has not seen speak. Stop at the first clear sign
   of a person. A probe that lands on a person gets a natural wrap-up, not an explanation of the test.
8. **Validate offline first.** Replay the passive readings over the people she already knows, her known bots and
   people she is sure of, for a hit rate. Live probes only after that rate is good enough for her, and at first
   alongside her own judgment, not replacing it.
9. **Only if measurement asks:** a small structured record of probe sessions (who, step, deadline) if the task thread
   proves too loose; automatic probe scheduling.

## Catalog

*(Pending: the source study of AstrBot, MaiBot and the Hermes QQ bot, cross-checked against Xiaoman's own survey.)*

## Open questions for Xiaoman

- Her list of known bots and known people: the ground truth for the offline replay, and where it lives.
- The tiers and words for each passive reading.
- The probe lines themselves: her voice, so hers to write.
- Whether `here`-layer notes suit groups where a bot is only a bot there (a person and their bot may share a name).
