# ADR-129: One way to speak, at home too

Status: **Proposed** 2026-11-13 (laid down; nothing built; framed by the owner the same night, §3). The owner's request (11-12 night): give her home line the
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
- **The program makes silence at home an act.** At home a turn that ends with no words is handed back
  (`answers.speech_problem`: 这回合没有写要说的话：写出要对对方说的话，或者用 stay_silent 结束), and a turn that keeps
  failing that check fails as `INVALID_TURN_OUTPUT`. To be quiet at home she must call `stay_silent`.
- **No stickers at home.** `stickers.sends` needs a platform scene (`channel_id`). At home the `sticker` tool only tidies
  her shelf.
- **The page already shows `speak` as speech.** `client.js` (`RoleToolRow`) draws a `speak` call as the row 说话 · its
  first text, which opens to all its parts read as speech. The row is closed by default, so at home the owner would
  open each reply to read it.

## 2. The broken invariant

**At home nothing about her manner of speaking is mandated** (owner, 11-13). She may speak in plain text, through
`speak`, in several lines, or not at all, and a turn that ends with no words is fine. The program breaks this in two
ways. It refuses the `speak` that her outer self is used to, and she reaches for it (§1). And it demands words or an
explicit `stay_silent`, which turns silence into an act she must perform (§1).

## 3. Decision (proposed, the owner's framing of 11-13)

**D1. `speak` at home, as on QQ.** Her Web chat conversations (§4) list `speak` with the parts the place can carry: `text`,
`sticker` and `picture`, with `file` if the home page can show one. There is no `poke`, `react` or `recall`, because
there is no platform behind them; ADR-079's `PART_NEEDS` rule already lists a part only where it is declared. It takes
the same parts, writes the same outbound rows (`queue_reply`) and returns the same receipt as on QQ. `attach_image`
becomes its `picture` part, as on QQ (`REPLY_REPLACES`).

**D2. Plain text stays speech at home.** Unlike QQ, body text at home is still said; nothing is handed back. A turn may
use both, and both are said in the order written: `speak`'s parts when it is called, the end-of-turn text after them.

**D3. Silence needs no act at home.** `stay_silent` leaves her home toolbox, and the no-words check
(`answers.speech_problem`'s last case) does not apply at home. A turn that ends with no words and no `speak` is silent
and fine. The checks for things that cannot be sent stay: a reply cut off at the length limit, and a sticker she does
not have.

**D4. No rules on `speak` at home** (owner, 11-13: just give the tool). None of `speak`'s QQ rules apply at home: the
line limit (`SPEAK_HARD_LINES`, `speak.max_messages`), the typing pace, the refusal of a text already sent this turn,
and the refusal of `#number` labels. The one thing still refused is a part that cannot be shown at all: a sticker she
does not have, or a picture id that is not hers. The receipt says which part and why, as on QQ. Pace already follows
the place (`not_before` is set only for a scene with a `channel_id`); the other rules get the same test of place.

**D5. The page shows it.** The 说话 row opens by default where `speak` is her home speech, so the owner reads her reply
without a click, through DSH's own disclosure row. Today a sticker part is drawn as the words ［表情包：name］. Showing
the sticker itself on the page is the point of stickers at home (owner's point 3); if that needs more than DSH's own
image facilities, it is a UI change and needs the owner's approval first.

## 4. Where (decided by the owner, 11-13)

All of her Web chat: every conversation of hers in the DSH Web page. The agent lines and the peer line keep what they
have now. In this ADR, "home" means her Web chat.

## 5. Read before building (not yet checked)

- How a home conversation declares reply parts. The Web chat's scene has no channel kind today, so `reply_parts`
  returns nothing for it. Home must get `speak` without QQ's A2 rule that body text is not sent.
- How a sticker reaches the home page (D5), and what `attach_image`'s picture at home becomes as a `picture` part
  (`_publish` carries `attachment`; `queue_reply` carries `part['fields']`).
- How `_publish` (her end-of-turn text) and `queue_reply` (`speak`'s parts) share one turn's sequence numbers and
  `speak:<index>` keys, so that D2's order holds.
- What her prompts and tool descriptions say about speaking or being silent at home. A changed or new literal needs her
  word first (her F8).
- How `speak`'s receipt reads where a part is shown at once (no platform delivery to wait for).
- The cache: each home session's toolbox changes once, with one cache miss on the first turn after the install.
  `tests/test_tool_budget.py` changes by the measured difference.

## 6. Tests

These go only where a failure would be silent:
- a home turn's `speak` parts and its end-of-turn text both reach her outbound history, in order;
- a home turn with no words ends silent, with no hand-back and no failure;
- a home `speak` that QQ would refuse (over `SPEAK_HARD_LINES`, a repeated text, a `#number`) goes out.

## 7. Shown, then installed. Closes when

- **Shown** in an isolated demo profile with a stub model and the real worker, labeled 造的: a home turn with `speak`
  (text and a sticker, both seen on the page), one with plain text, one with both, one with neither (silent, no
  hand-back), and a long reply with a repeated line. The home toolbox lists no `stay_silent`.
- **Installed** in a restart slot she gives, after her reading.
- **Closed** when, over her own home use, there are no refused `speak` calls at home and no hand-backs for a missing
  answer, and her `speak` replies (a sticker among them) are seen on the page. How often she is silent is hers, not a
  closing condition.
