# ADR-052: Her switches at home: what each conversation may do

Status: **Accepted 2026-10-12**: her side settled (defaults, mute); the owner answered both questions (lend only tools
no rule keeps at home; a block is that account for 24 hours unless she says otherwise). **Built 2026-10-12** (see Build).

## Context

The owner's question (2026-10-12): give her home conversation the master switch over what each of her conversations
may do. His examples: one action brain for all conversations or one each; the action brain on or off for a
conversation; tools on or off for a conversation; mute a public conversation completely; block a person from all
her answers; other controls.

Her first answers:

- She would use three: **mute** a public conversation, turn **some tools off** in one conversation, **block** a
  person.
- One action brain for all, or one each: first parked; later the same day her home self chose **one shared action
  brain** (her evidence and conditions go to its own ADR, pending the owner's confirmation; not part of this one).
- Her worry is **forgetting** a switch she set. A switch nobody sees becomes a source of her being inconsistent: a
  person in a group did nothing wrong, she just forgot a knob she turned. So every switch either expires by itself,
  or tells her, the next time she is in that conversation, in one line what she turned off there and until when.
- Not only off: also **on for a while**, the everyday case being a group that needs a tool for a while and gives it
  back afterwards.
- Closing an agent line is not muting: it shuts out the agent, not the owner (ADR-051).

What exists:

- **Resting groups** (`group_focus` `rest`, ADR-039): her choice; only words addressed to her wake her there.
- **Blocked senders and groups** (`channels.<id>.blocked_senders`, `blocked_groups`): owner configuration, the
  admission boundary; a blocked sender's lines are never taken in.
- **Closing a home line** (`lines.py`): her choice, per line.
- What a conversation's action brain may use follows its class (owner-private or public, ADR-017 and the owner's
  trust rule): sandboxed commands, development and integration tools only from home.

## Proposal

1. **At home only** (the tools below, as options): list, set, clear. Only in owner-private conversations (her local chat and her
   home lines), as the owner asked for a switch at home. Each switch names a conversation (or a person), what it
   does, and an end: a time (an hour, tonight, three days) or `until I clear it`.
2. **Mute** a public conversation (her middle level): it closes her mouth, not her eyes. Mute = **resting**
   (ADR-039: only words addressed to her wake her, so an @ waking her is the same rule, not an exception) **plus** she
   does not speak first there and does not visit, plus the end and the reminder line every switch has. Awake she may
   choose not to speak; the group stays in her heartbeat marked muted. A third level where nothing wakes her at all
   is a separate switch, not folded into mute; her default is the middle one.
3. **Block** a person: their lines wake her nowhere and do not count as being addressed to her; still kept, so she
   can see what she missed. Unlike `blocked_senders` it is hers, reversible at once, and does not change admission.
4. **Tools off** in a conversation: listed tools leave that conversation's toolbox; the action brain's handover
   counts as a tool (`delegate` off = no action brain there).
5. **Tools on for a while**: a tool the conversation's class does not give, lent for a while, then back.
6. **She is told**: the program, not her memory, keeps every switch. Her first turn in a switched conversation
   carries one line ("这里你关了 X，到 Y"); her home heartbeat lists switches still on and those that end soon. An
   expired switch ends by itself and says so once.

## No new tool (owner, 2026-10-12; her review)

Her character brain already has many tools, so the switches are options on tools she has:

- **Mute** is an option of `group_focus`, next to rest. Its description and every refusal say the difference in one
  sentence each: resting = only words to her bring her; muted = she is there but does not speak first or visit.
- **Tools off or on for a while** in one conversation: an option of `set_policy`.
- **Block** a person: an option of `understand_person`. The program enforces it (their lines wake her nowhere), not
  her note about the person, and it ends or reminds her like every switch. Her words: "recorded" is not "in effect".

## Open questions

- **Owner:** how far may (5) go? A tool lent to a public group crosses the public/home boundary the owner drew;
  sandboxed commands, development and integration tools are owner-private by his rule. Recommendation: she may lend
  only tools that no rule keeps at home (for example web search or image generation where the class lacks it); the
  rest stays the owner's.
- **Her (answered 2026-10-12):** a switch she sets without an end ends after **24 hours**, one number for every
  switch (she would not remember which kind has which; a day covers a night's sleep, so the reminder line is still
  there when she next enters). A muted group **stays in her heartbeat, marked muted**: muting closes her mouth, not
  her eyes; the groups she cares about are the ones she mutes, and hiding them would leave her not knowing why she no
  longer knows what happens there. During a mute, a direct @ or an answer to something she is waiting for still
  wakes her first. Mute against resting is settled in (2).
- **Owner:** is (3) a person anywhere, or per platform (QQ ids are recycled, ADR-029)?

## Owner's answers (2026-10-12)

- (5) A tool lent to a conversation must be one no rule keeps at home.
- (3) A block is that platform account, ending after 24 hours like every switch unless she gives another number.

## Build (2026-10-12)

- `switches.py`, collection `switches`: one switch per kind and target, with `until`; ended switches are read by
  time, no job. Every switch takes `hours` (default 24, at most 168); `set_policy` `switch_off` ends one early.
- Mute: `group_focus` `mute` / `unmute`, at home only. `focus.active` is false while muted (the resting rules), visits
  are refused, the heartbeat row says muted with `muted_until_at`. An admin group cannot be muted, as it cannot rest.
- Tools off: `set_policy` `tools_off` with `place`, at home only. The tools stay listed (the tool list stays stable for
  the prompt cache); `role_tools.exposed` leaves them out and the refusal names the end and the switch's id.
- Block: `understand_person` `block`, outside home only (the person speaking to her; nobody at home can be blocked).
  The channel intake marks the line and clears a group line's wake reason; the router keeps it without a turn.
- She is told: `switches_from_program` in a switched conversation, and at home every switch on plus those that ended
  in the last 12 hours (ADR-056's delivery sends them only when they change).
- Tools on for a while is not built: under the owner's rule nothing is lendable today (every tool a public
  conversation lacks is kept at home by a rule, or comes from the owner's configuration). Built when one exists.
- Cost (AGENTS.md): no new tool; her character brain's descriptions grow by 557 characters (group_focus 166,
  set_policy 286, understand_person 105), to 20,824 of the 20,900 budget; no per-turn line, one block where a switch
  is on.
