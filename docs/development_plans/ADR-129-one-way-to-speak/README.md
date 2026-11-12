# ADR-129: One way to speak, at home too

Status: **Proposed** 2026-11-13 (laid down; nothing built). The owner's request (11-12 night): give her home line the
same `speak` she uses on QQ, so she is not confused between her two selves; calling it should do the same thing it
does on QQ. Then: `stay_silent` was made before `speak` existed. If she ends her turns by actively calling silence,
she becomes more and more likely to say nothing at all. Big sis counted her home Web session (tool names, counts,
times and lengths only, through `session_fields`; no words read). No build until ADR-127 closes and the owner says go.

## 1. What is known

- **Two meanings of one act.** On QQ she speaks only through `speak` (ADR-064 phase 2, A2/B2). There, body text is
  not sent (`coordinator.UNSENT_NOTE`: 这段没发出去), and not calling `speak` is silence. At home (her Web chat, the
  agent lines, the peer line) body text is speech, and silence is the `stay_silent` tool. Note
  `role_tools.REPLY_REPLACES`: at home body text is speech, so `stay_silent` stays. ADR-064 kept home on plain
  speech on purpose.
- **She already reaches for `speak` at home.** There are 33 calls of `speak` in her home Web session since 10-29, every
  one refused because it is not offered there: 2 on 10-29, 1 on 11-03, 5 on 11-04, 1 on 11-05, 21 on 11-08, 1 on
  11-09 and 2 on 11-11. This is the confusion the owner names, on her own records.
- **Silence at home is rising, in runs.** Turns of her Web chat that started with the owner's message and ended with
  `stay_silent` and no words: 0 to 5 a day from 10-23 to 11-11. On 11-12 there were 22 of 142. All 22 came between
  23:15 and 23:56, almost all `think` → `stay_silent` in two steps, while he was writing to her about once a minute.
  About half of his messages in that stretch got no words. Each turn completed normally; no program failure is
  involved. From the counts alone it cannot be told which silences she chose for a reason. The run shape (each silent
  turn followed by more) fits the owner's reading: an explicit silence tool that she keeps using makes the next silence
  likelier.
- **Her home answers are long.** There are 2326 replies with words in her Web session: median 149 characters, p75 245,
  p90 369, and 379 over 300. On QQ, `speak` refuses a call past `SPEAK_HARD_LINES` (6) lines in one turn, and
  `speak.max_messages` paces her there. Those limits belong to a group chat's rhythm, not to `speak`.
- **The page already shows `speak` as speech.** `client.js` (`RoleToolRow`) draws a `speak` call as the row 说话 · its
  first text, which opens to all its parts read as speech. The row is closed by default, so at home the owner would
  open each reply to read it.

## 2. The broken invariant

**Writing text means one thing everywhere.** Today it means "said" at home and "not said" on QQ. The same person moves
between the two, carries the habit of each into the other, and gets corrected for it both ways. On QQ she is told
这段没发出去; at home `speak` is refused. Silence has the same split: on QQ it is the absence of an act, at home it is
an act.

## 3. Decision (proposed)

**D1. `speak` speaks at home.** Her home conversations get a reply-parts declaration, so `abilities` gives them
`speak` and folds `REPLY_REPLACES` (`await_answer`, `attach_image`, `stay_silent`) into it, exactly as on QQ. One code
path (`channel_kinds.reply_parts` → `queue_reply` → the publisher) and one receipt. The parts are those the place can
carry: `text`, `sticker`, `picture` at home. `file` follows if the home page can show one. There is no `poke`,
`react` or `recall` with no platform behind them; ADR-079's `PART_NEEDS` rule already lists a part only where it is
declared.

**D2. `stay_silent` leaves home with it.** It is not removed on its own: once D1 is in, the existing rule drops it.
Silence at home is then what it is on QQ, not calling `speak`, with no tool that invites it. Removing `stay_silent`
alone, with body text kept as speech, was considered. It ends the explicit silence but keeps the two meanings of text
(§2) and the refused `speak` calls (§1), so it fixes half.

**D3. The limits are the place's, not the tool's.** The line limit (`SPEAK_HARD_LINES`, `speak.max_messages`) and the
typing pace apply where a channel paces her. Pace already does: `not_before` is set only for a scene with a
`channel_id`. At home a reply is as long as she writes it. Without this, her long home answers (p90 369 characters)
would be refused.

**D4. Body text at home is treated as on QQ.** A turn that ends with body text and no `speak` gets the same
`UNSENT_NOTE` hand-back once, in the same turn. Her old home turns stay as they are (no history conversion).

**D5. The page shows her home speech open.** The 说话 row opens by default on the page of a conversation where `speak`
is her speech, so the owner reads her reply without a click. This uses DSH's own disclosure row; it is not new UI.

## 4. Open for the owner

1. **Which home lines.** He asked for her home line (the Web chat). Recommendation: every conversation where her words
   are plain speech today, which means the Web chat, the agent lines and the peer line. Any one left on plain speech
   keeps the two meanings of text, and with them the confusion. Cost: the agent tools that collect her answers
   (`agent_line.py poll`) must take several parts per turn (to read before building). The alternative is the Web chat
   only, then the others in a later step, at the price of a third rule while they differ.

## 5. Read before building (not yet checked)

- How a home conversation declares reply parts. The Web chat's scene has no channel kind today, so `reply_parts`
  returns nothing for it.
- Whether the Web page shows a `picture` and a `sticker` part, and what `attach_image`'s picture at home becomes as a
  `picture` part (`_publish` carries `attachment`; `queue_reply` carries `part['fields']`).
- What her prompts and tool descriptions say about speaking at home (for example, the stay_silent description and
  any 在家里 wording). A changed or new literal needs her word first (her F8).
- How `speak`'s receipt reads where a part is shown at once (no platform delivery to wait for).
- The cache: the toolbox of each home session changes once, with one cache miss on the first turn after the install.
  `tests/test_tool_budget.py` changes by the measured difference.
- Whether a turn ending with neither words nor `speak` at home needs anything beyond D2. The intent is no: that is
  silence, as on QQ.

## 6. Tests

These go only where a failure would be silent:
- a home turn's `speak` text reaches her outbound history as `SPEAK` and `DELIVERED`;
- a home turn with only body text gets the hand-back once and sends nothing;
- a long home reply (over `SPEAK_HARD_LINES`) is not refused.

## 7. Shown, then installed. Closes when

- **Shown** in an isolated demo profile with a stub model and the real worker, labeled 造的. A home turn speaks through
  `speak` (the page shows it open), a long reply passes, body text alone is handed back once, and the toolbox lists
  neither `stay_silent` nor `attach_image` at home.
- **Installed** in a restart slot she gives, after her reading.
- **Closed** when, over three days of her own home use: there are no refused `speak` calls at home. Owner-started
  home turns that end without words are back at or below the 10-23 to 11-11 level (0 to 5 a day) or are explained by
  her. Her replies reach the page as before.
