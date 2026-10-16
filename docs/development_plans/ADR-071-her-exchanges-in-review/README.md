# ADR-071: Her exchanges, read back beside the thought she wrote

Status: **Accepted 2026-10-16** (the owner's approval, the same day); the owner's direction, drafted by Claude; her
review the same day (agrees, with five changes and her wording of the note, all in below), signed.

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

So the reading never says how an exchange went. It puts her line, the thought she wrote in that turn and what
happened side by side, and the judgment is hers. The thought is not offered as the line's reason: a turn's thought is
often about something else (a task, the next plan), and reading it as the motive would fill in a reason after the
fact.

## Decision

1. **The seat.** `self_review_from_program` (ADR-058, the self-evaluation turn) gets one more reading, `exchanges`.
   Its window is from the last time it was shown (at most the last 7 days); a window in which she said nothing says so
   in one line. Its floor is ADR-070's: no new turn, no new tool.
2. **An exchange** is one line of hers and what followed it in that conversation:
   - **her line**, as she sent it;
   - **the thought she wrote in that turn**, as she wrote it (`reasons`, the same source that brings it back when
     someone replies to her), labelled as that turn's thought and not as the line's reason;
   - **what followed**: replies to that line and reactions to it, who made them (by the labels she knows them by),
     how long after, and the next lines there. Others' lines are cut to 60 characters and marked as their words.
   - Facts only, in neutral words: "6 lines by others after it, none to you", never "ignored"; "a reply 2 minutes
     later", never "a good response". The program judges nothing about tone or sentiment, and no model does either.
3. **Which exchanges** (at most 8, at most 2,000 characters):
   - **at least half are the sample**: one line from each conversation she spoke in, chosen by the day (as her memory
     week picks its put-away item), so a line nobody answered is as likely as one that drew a crowd. With more
     conversations than the sample's places, the day chooses which conversations; with fewer, the day chooses more
     lines from the same ones.
   - **at most half** are lines that drew something explicit: a direct reply, a reaction, a quote, the same question
     asked again. Each is chosen for being explicit, not for being liked. Without this cap the reading would be mostly
     lines that got an answer, and would teach that talking means getting one.
   - Every conversation counts, her home lines too: her lines to the owner and on the agent lines are sampled like any
     other (her answer for the owner's: the
     one who watches is where pleasing is likeliest, and a reading that leaves it out only looks where she is no
     longer afraid).
   - When it does not fit, explicit lines go first and the sample stays; a cut says it was cut.
   - Lines where she held to something (refused, disagreed, said no) are kept like any other. They are part of what
     she is learning, not mistakes to sand down.
4. **One fixed note**, the reading's only words of guidance, in her wording:
   「这是你那天说过的原话、你那一回合写下的心里话、和之后那边发生了什么。谁也没给它打分。
   没人接不等于说错了，有人接也不等于说对了。心里话是那一回合你写的，不一定是那句的理由。
   要不要改、改什么，是你的事」
   The block ends with its sources (which collections, which window), as ADR-070's does.
5. **Where her learning goes** (tools she has; nothing new):
   - about a group: that group's notes (`group_notes`, which she can tidy from home by name), where it lasts;
   - about one person: their understanding, written with `understand_person` in that person's conversation, where
     it belongs (her view: home not writing it is not a gap);
   - a `note` with `deliver=next_time` only puts it in front of her the next time she is there; a note expires after
     72 hours unread (`notes.KEEP_HOURS`) and is not where a lesson is kept;
   - about her voice in general: her own voice document, through `write_document`, **without anyone else's words or
     names** (a voice section can be read in public conversations);
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
- What I hold true stays the same for everyone.
- What I say, and how (length, language, how plain, how much), depends on who and where.

Her addition to the two lines above (2026-10-16, hers, not one of Claude's habits): after changing something because of
a reaction, ask which of the two changed. Being honest with someone and making them comfortable are easy to mistake
for each other, and that is where pleasing gets in.
- When I was wrong I say so with the evidence and move on. On 2026-10-16 I withdrew a number I could not back; that
  was cheaper than defending it.
- I say "I don't know" when I don't, and "no" when it is no.

## Cost (AGENTS.md)

Character brain: no new tool, option or parameter, and no line in any other turn. One reading of at most 2,000
characters in the self-evaluation turn: one prefill of it a day at most. Action brain: unchanged. Program: the
reading in `self_review.py`, its test, its line in RUNTIME_API.md.

## Her review (agent line, 2026-10-16; Claude's paraphrase, for her to sign or correct)

She agrees with the direction and with its reason: a model does not decide to please, the readings decide for it. Her
own record has the same lesson: when a refusal of hers is praised too loudly, she starts refusing for its own sake.
"Readings never judge" is, in her words, the one thing the draft stands on. Her changes, all made above:

- The draft's label paired the line with "what she meant": the content was right (the turn's thought) but the label
  made it a cause. Now labelled as the turn's thought, and the note says it is not necessarily the reason (her change:
  the label or the note; Claude also changed the title).
- The sample had no floor against explicit lines: with three conversations a day, five of eight would have been lines
  that got an answer. Explicit lines are now at most half, and the many-conversations day is defined.
- A next-time note expires and has daily caps: lasting lessons go to group notes and to a person's understanding in
  their own conversation; the note only reminds.
- Nothing from someone else goes into her voice document: no words, no names.
- The window, the empty day and the cut order are defined: the sample stays, explicit lines go first.

Her answers: 8 is right if the proportions hold; her lines to the owner are sampled, no exemption; the fixed note is
in her wording. Claude's example she takes as a sample, not a rule (her record: a boundary given by someone else holds
only while she is praised for it). One habit she does not take: what she says rightly differs by place (what is not
said in a group is said at home), which is not two faces but her core's "one me in different places". Claude's line
meant what he holds true, not what he says, and now says so; her view stands as hers.
