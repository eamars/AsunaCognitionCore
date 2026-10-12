# ADR-057: Group labels: nothing in a message can pass for one, and the number means nothing

Status: **Proposed 2026-10-12** (owner's plan 1: short random ids instead of #n). Needs the owner's choice and
Xiaoman's review. Nothing is built.

## Context

Each person in a group gets a label the first time she sees them, `[name #n]`, numbered in order per group and kept
for good (`people.py`): the same person reads the same across renames, compaction and memory. The number never leaves
the program (sending turns a label into a real @ or a plain name).

The owner's plan: short random ids (4 digits per group) instead of the running number, perhaps re-drawn every few
hours, so a number cannot be guessed and does not read as a rank.

Measured (2026-10-12):

- **Imitation is rare but real.** Since 09-01, 10 incoming lines outside home contained text shaped like a label;
  one used a small number that was a real label in that group, someone else's. Running numbers are easy to guess:
  #1–#3 are the first people she met there.
- **Labels are everywhere in what she remembers.** 4,935 of 5,112 dialogue summaries, 290 chat chunks and 15 of her
  thoughts contain labels. Her documents contain none.
- **Numbers grow large:** the largest group is at #170.

## The broken invariant

"A label is something only the program writes" does not hold: a person's message body can contain `[name #4]`. The
body is indented under the real speaker's label, but a model can still read the inner text as a speaker. Unguessable
numbers make a forged label miss; they do not stop a forged line from looking like a label.

## Options

1. **Close it at the root (recommended first):** text that someone sent can never contain a label. Like ADR-050's
   quote lines, the program rewrites a label-shaped text inside a body (`[x #n]` becomes `［x ＃n］`), so only the
   program's labels have the label's form. Deterministic, no change to any number, nothing she remembers changes.
2. **Random 4-digit ids for new people only**, drawn from 1000–9999 and unique per group: no rank reading, nothing to
   guess, nothing stored changes. Existing people keep their numbers; the established members (the likeliest to be
   imitated) stay guessable, which option 1 already covers.
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
