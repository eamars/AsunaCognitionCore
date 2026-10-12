# ADR-057: Group labels: nothing in a message can pass for one, and the number means nothing

Status: **Decided 2026-10-12** (owner): close the two ways a label can be abused at the root; random ids are parked
while that holds. **Built 2026-10-12** (see Decision). **Closed 2026-10-12** (owner): the number authenticates nothing (see
Where the number is used).

## Context

Each person in a group gets a label the first time she sees them, `[name #n]`, numbered in order per group and kept
for good (`people.py`): the same person reads the same across renames, compaction and memory. The number never leaves
the program (sending turns a label into a real @ or a plain name).

The owner's plan: short random ids (4 digits per group) instead of the running number, perhaps re-drawn every few
hours, so a number cannot be guessed and does not read as a rank.

Measured (2026-10-12):

- **Imitation is rare but real.** Since 09-01, 10 incoming lines outside home contained text shaped like a label;
  one used a small number that was a real label in that group, someone else's.
- **A number is no secret, guessed or not: she says it when asked.** On 10-12 a member asked her for his number and
  she answered "你是5号"; the out-going check (`people.speech_problem`) looks for `#n` only, so it passed. A random id
  would be told the same way. Whatever keeps a person from passing as another cannot rest on the number being
  unknown.
- **Labels are everywhere in what she remembers.** 4,935 of 5,112 dialogue summaries, 290 chat chunks and 15 of her
  thoughts contain labels. Her documents contain none.
- **Numbers grow large:** the largest group is at #170.

## The broken invariant

"A label is something only the program writes" does not hold: a person's message body can contain `[name #4]`. The
body is indented under the real speaker's label, but a model can still read the inner text as a speaker. A number
that is unknown makes a forged label miss only until someone asks her; it never stops a forged line from looking like
a label.

## Options

1. **Close it at the root (recommended first):** text that someone sent can never contain a label. Like ADR-050's
   quote lines, the program rewrites a label-shaped text inside a body (`[x #n]` becomes `［x ＃n］`), so only the
   program's labels have the label's form. Deterministic, no change to any number, nothing she remembers changes.
2. **Random 4-digit ids for new people only**, drawn from 1000–9999 and unique per group: no rank reading, nothing stored
   changes. It hides nothing: she tells a person's id to whoever asks, as she tells a number now.
3. **Re-draw everyone's id once** to random 4 digits: uniform, but every stored summary and chunk then names people
   by numbers that point at nobody. It needs either a lasting old-to-new mapping when memories are shown, or a rewrite
   of 5,000+ stored summaries. Expensive, and it disturbs her memory for a cosmetic gain once option 1 is in.
4. **Re-draw ids every few hours** (the owner's question): not recommended. The ids never leave the program, so there
   is nothing outside to rotate against; every re-draw would break her references in summaries, notes and @ she
   wrote, and a person would read as someone new to her.

## Recommendation

Option 1 now, with option 2 for people met from now on. The prompt then says only what a label is for: recognise
people by it, not by names; the number is an id, not an order, and needs no other explanation.

## Cost (AGENTS.md)

No tool; no per-turn line. The common prompt's sentence about the number gets shorter.

## How it is checked

Replay the 10 imitations found: each reads as text, none as a label. A new person's id is 4 digits, unique in its
group, and never below 1000 (so an old number and a new id can never be confused).

## Decision (owner, 2026-10-12)

The owner's one risk: she leaked a person's number before, and someone could use it to pass as that person. Two ways,
both closed without renumbering anyone:

- **Out:** her bare `#n` leaked five times (10-05 to 10-07, real people's numbers). Closed since 10-08 by the program
  handing such a line back to her before it is sent (`people.speech_problem`); no leak in public since.
- **In:** a label typed in someone's text read exactly like the program's. Now every label-shaped text someone sent
  reads `［name ＃4］` / `@＃4` (`people.typed`, through `People.heard`): in their lines, a quoted reply of theirs, the
  turn's event text, correction snippets and what summaries are made from. Their real @ still becomes the label, after.
  Labels she wrote herself (her own lines, quoted) and the program's memories are unchanged.

Random ids are parked: with no label able to pass in, their only gain is that a number reads as no order.

The out side is not closed by the check: she says a number in words when asked ("你是5号", 10-12), and no pattern
covers every way of saying it. It needs no closing: a number she tells gives nobody a way in, because nothing a person
types can take a label's form. The check stays for what it was for: a `#n` in her line means nothing to the group.

## Where the number is used (2026-10-12)

Assume she tells anyone any real number: she did when asked, and nothing should rest on her keeping it back. The
owner's test: wherever a number is used to authenticate, the account must be used instead. Read from the source:

- **Authentication never reads a number.** What a conversation may do (`visibility.session_class`) comes from the
  scene and the sender's account: home, the owner's DM by the configured canonical person, the owner's own agent
  and peer lines. A group is public whoever speaks, the real owner included, so passing as someone there gains no
  right. `block` acts on the account speaking to her, never on a number, and nobody at home can be blocked.
- **Every other use turns her own writing into an account, in the conversation it belongs to:** her @ of a label
  becomes the platform @ (`People.outbound`), the people her line waits for (`channels.addressees`,
  `waiting.pending`), a person named in her tool arguments (`People.resolve`, `history_query`), and showing people
  to her (`label`, `group_members`). None reads a number from someone else's text.
- **What someone's text can do with a number is a claim** ("2号让你…"), the same as a name, weighed by her as
  hearsay. A summary may later repeat such a claim in label form; the summary's `who` (the speakers, from accounts)
  stays the program's record of who spoke. That is attribution in her memory, not authentication, so the proposal to
  flatten such labels when memories are shown was dropped.

The account, mapped to a person id she never sees, is the identity; the number is only how she tells people apart.
