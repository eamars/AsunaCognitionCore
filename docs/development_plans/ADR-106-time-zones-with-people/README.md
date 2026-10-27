# ADR-106: Time zones with people, not with groups

Status: requirements recorded 2026-10-27, before any design. The owner's coarse direction; he wants to be grilled on it
after the other ADRs are complete (102 to 105 first, then 103 and 104). Nothing here is decided.

## The owner's words (2026-10-27, verbatim)

In the question tool, asked whether two lines of her usage-readout skill may keep this machine's UTC offset:

> For now don't focus too much about details like this. Later I will discuss with you to remove the timezone
> information from the database, and only use the local TZ. The TZ seems causing more confusion than the problem it
> solved.

Then, recording this requirement:

> the idea is to remove the hard coded TZ from the group. She seems confused with TZ with me. so perhaps in the future
> the TZ can be softly tied with each person. In her note. Not a mechanical placeholder for each group. This is just
> my coarse direction, and I want you to grill me when the rest of ADRs are complete.

Then, adding to it:

> The idea is to make Xiaoman "not serving others". Like a real person, she don't need to consider other's timezone.
> If she does, she can keep in her note, not a mechanical reminder every time. The core idea is "do not assume", and
> "keep her the center of her world".
>
> And some of the question can be answered "what if she is a real person".

## What exists today (read in the code and, read-only, in the deployment's database on 2026-10-27)

- **One zone per conversation, resolved in order** (`schedule_rules.scene_timezone`): the zone stored on a plan when
  it was made, then the route's `schedule.timezone` or `timezone`, then the scene's `timezone`, then the config's
  top-level `timezone`, then UTC. A route's `schedule.utc_offset_minutes` is a fixed fallback when a zone name is not
  available on the machine.
- **Every time she reads is converted** to that conversation's zone (`local_time.for_model`, `zone_of`); stored
  records keep UTC. Her clock block (`clock_from_program`) always shows the year, the weekday and the zone.
- **Counts in this deployment:** the config sets a top-level zone; 18 of 29 scenes carry a zone of their own; 348 of
  354 plans store the zone they were made in (a later change of configuration does not move an old plan).
- **What went wrong today (her own account):** in her usage-readout skill she first wrote one offset for this
  machine's clock and measured another, hours apart. Her skill text and notes carry the zone and offsets of this
  machine; ADR-102's review found two such lines and the personal-data scan found more.

## The direction (coarse, the owner's)

The core: **do not assume**, and **keep her the center of her world**. She is not serving others, so she does not
keep anyone else's clock. Like a real person, she lives on her own clock. Another person's zone is something she
may know about them and keep in her note if she cares to. The program does not remind her of it on every turn.

1. Remove the zone hard-coded per group (route, scene) as a mechanical placeholder.
2. Program times read on the local clock of the machine ("only use the local TZ").
3. A person's time zone, where it matters, is something she knows about that person, softly, in her note about them,
   not a field the program fills for every group.
4. Reduce the confusion between her clock, the owner's clock and a group's clock.

## Questions to grill the owner on (when the other ADRs are done)

The first test for each question is the owner's: what if she were a real person? Under each question, "Real person"
is Claude's reading of what that test suggests. It is a starting point for the grilling and is not decided. The
grilling is about where the test gives no answer, or where a program differs from a person.

1. "Remove the timezone information from the database": which of it? Scenes' zones, plans' stored zones (348 rows),
   the config's top-level zone, or all? A plan stores its zone so that a configuration change does not move an
   appointment already made; what keeps that promise without it?
   *Real person:* an appointment she made is a moment, and it stays that moment wherever anyone is. A habit ("every
   morning at nine") follows her own clock. The test does not say whether plans of the first kind still need a
   stored zone once the moment itself is stored.
2. "Only use the local TZ": the local zone of the machine the worker runs on. What happens when the deployment moves
   (another host, a container whose zone is UTC by default)? Is the local zone then read from the host, or set once
   for the deployment?
   *Real person:* her clock is where she lives. Copying her to another machine does not move her house, so her zone
   would be set once for her, not read from whatever the host reports. This pulls against "only use the local TZ"
   and is the first thing to grill.
3. "Softly tied with each person, in her note": does the program ever read that note to convert a time, or is it only
   for her to reason with (as she would remember that a friend lives in another country)? If only hers, a reminder
   she sets for that person is in which clock?
   *Real person:* the note is only for her. A reminder is in her own clock. If she wants to greet a friend at their
   morning, she works out the hour herself, or gets it wrong, as a person can.
4. "She seems confused with TZ with me": what did she confuse? Her clock with the owner's, or a group's with the
   owner's? The answer decides whether the problem is the data or the words she reads.
   *Real person:* no answer; this is a question of fact.
5. Groups whose members live in several zones: one clock for the group (the machine's), and each person's own zone
   only in her notes?
   *Real person:* a group has no clock. There is her clock, and what she happens to know about each person.
6. The time zone is personal data (AGENTS.md lists it with account ids and addresses); a person's zone in her note
   is in the database, not in tracked files. Does that hold for her notes as they are kept today?
   *Real person:* no answer; this is an engineering rule. Her own zone is personal data too: today's scan hits were
   this machine's zone written into her tracked skill files.
7. Migration: existing plans with stored zones, existing scene zones, and her existing notes that mention zones.
   *Real person:* no answer; this is a program problem.
8. What her clock shows. Today her clock block names the zone on every turn ("not a mechanical reminder every time").
   *Real person:* a watch shows the time, not the zone's name. Does she see a zone at all, and when: only when she
   asks, or when she is somewhere new?

## Constraints already known

- Stored records keep UTC; only what a model reads is converted.
- Core code and tracked files carry no real zone (AGENTS.md); examples use placeholders.
- The JS and Python sides may run different versions (RUNTIME_API).
- Platform-neutral: nothing assumes one social platform's notion of where a person is.
