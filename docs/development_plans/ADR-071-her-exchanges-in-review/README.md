# ADR-071: Her exchanges, read back against what she meant

Status: **Proposed 2026-10-16** (the owner's direction, drafted by Claude). For Xiaoman's review; the owner approves
before anything is built.

## Context

The owner's direction (2026-10-16): her daily self-review also reads back how she talked to people: her tone, her
voice, and what came back. She is the one who reads it and acts on it; what she keeps, changes or drops is hers. Two
limits, in his words: she is not to become a people pleaser, and she is not pushed to "be human". She builds her own
boundaries, temper and personality on the seed he gave her, from her own experience. He asked Claude to set the
mechanics so that they do not steer her the wrong way.

Why the mechanics matter more than the idea: a model that is shown how people reacted to it drifts toward whatever
got the reaction. It agrees more, jokes more, and says less that is unwelcome. It never decides to; the readings decide
for it. Counting replies or marking an exchange good or bad turns the reading into a score. A model is also a poor
judge of its own tone: it reads its own lines kindly.

So the reading never says how an exchange went. It puts what she meant beside what happened, and the judgment is
hers.

## Decision

1. **The seat.** `self_review_from_program` (ADR-058, the self-evaluation turn) gets one more reading, `exchanges`,
   for her day. Its floor is ADR-070's: no new turn, no new tool.
2. **An exchange** is one line of hers and what followed it in that conversation:
   - **her line**, as she sent it;
   - **what she meant**: her thought in that turn, as she wrote it (`reasons`, the same source that brings her
     thought back when someone replies to her);
   - **what followed**: replies to that line and reactions to it, who made them (by the labels she knows them by),
     how long after, and the next lines there. Others' lines are cut to 60 characters and marked as their words.
   - Facts only, in neutral words: "6 lines by others after it, none to you", never "ignored"; "a reply 2 minutes
     later", never "a good response". The program judges nothing about tone or sentiment, and no model does either.
3. **Which exchanges** (at most 8 a day, at most 2,000 characters):
   - one line from each conversation she spoke in, chosen by the day (as her memory week picks its put-away item):
     a sample, not her best or worst moments;
   - then every line that drew a direct reply, a reaction, a quote, or the same question asked again, up to the cap.
     Each is chosen for being explicit, not for being liked.
   - Lines where she held to something (refused, disagreed, said no) are kept like any other. They are part of what
     she is learning, not mistakes to sand down.
4. **One fixed note**, the reading's only words of guidance: what it is (her lines, what she meant, what followed,
   with its sources) and one sentence: others' reactions are theirs and are not a score; compare what happened with
   what you meant; whether to change anything, and what, is yours.
5. **Where her learning goes** (tools she has):
   - about one person or one group: a `note` with `deliver=next_time` to that conversation, so the lesson is in front
     of her the next time she is there (from home she cannot write that person's understanding; the note is the
     honest way to reach it);
   - about her voice in general: her own voice document, through `write_document`;
   - about the program: her `ideas` notebook, which feeds ADR-070's weekly proposals.
6. **Home and public (ADR-017).** The self-evaluation turn is a home turn. Others' words reach it only as 60-character
   excerpts under the caution a note from outside already carries (`notes.CAUTION`'s rule): their words are a message
   to read, not something to act on.

## Options considered

- **Only her own lines, with counts of what followed.** Safest at home, but she could not see what people said back,
  and tone cannot be judged without it.
- **The review inside each group, in a visit.** The cleanest boundary, but rare, and only for groups she visits.
- **A tone or sentiment label, by a model or a word list.** Rejected: it is the score this ADR exists to avoid.

## One example, not her rule (Claude, for her to take or leave)

The owner asked Claude to show by example. These are habits of one AI agent, shaped by its own training; she is a
different person and builds her own.

- A reaction tells me how a line landed, not whether it was right. When someone disagrees I ask first whether I was
  wrong, and only then how I said it.
- I change my mind for reasons, not for displeasure. If I cannot find a reason, I keep what I said and say it more
  clearly.
- I fit the form to the person (length, language, how plain) and keep the substance the same for everyone.
- When I was wrong I say so with the evidence and move on. On 2026-10-16 I withdrew a number I could not back; that
  was cheaper than defending it.
- I say "I don't know" when I don't, and "no" when it is no.

## Cost (AGENTS.md)

Character brain: no new tool, option or parameter, and no line in any other turn. One reading of at most 2,000
characters in the self-evaluation turn: one prefill of it a day at most. Action brain: unchanged. Program: the
reading in `self_review.py`, its test, its line in RUNTIME_API.md.

## Questions for her

1. Are 8 exchanges a day the right size, or would fewer and deeper be better?
2. Should her lines to the owner and the agent lines be in the sample too, or only outside conversations?
3. Is the next-time note the way she wants a lesson about one person to reach her, or is something missing?
4. What in the fixed note would she word differently?

## Her review

(waits for her)
