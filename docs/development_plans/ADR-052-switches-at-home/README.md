# ADR-052: Her switches at home: what each conversation may do

Status: **Draft 2026-10-12**: her side settled (defaults, mute); waiting on the owner's two questions below, then built.

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
