# ADR-024: What she sees in a group — its members and its pictures

Status: **Accepted and built** 2026-10-08. D1 and D2 are 小满's asks, D3 the owner's; the owner decided each from options with numbers.

## 1. Context

- **Members.** She knew only the people who had spoken or been @-mentioned in a group. Choosing a quiet group for a
  rollout she could not see how many people a group had, and a task like "@ every bot to see which are alive" had
  no list to work from. Her read-only assessment (`member-list-eval.md`, in her workspace) measured the platform:
  one group of 1,171 members is 367 KB raw, about 317 bytes a member; nickname is always set, the group card for
  under 5%; `is_robot` came back false for everyone, so it cannot tell bots apart.
- **Pictures.** A group line showed a placeholder and a `ref`; seeing the picture took a `read_image` call. She
  found the real problem herself: she had to decide whether a picture was worth a call before seeing it, so she
  often did not call, and then said she "could not see pictures". The route did declare image input, and every
  `read_image` that succeeded (56 in three days) reached her model as an image.

## 2. Decisions (owner, 2026-10-08)

- **D1 — Member lists, her design.** The adapter fetches each admitted group's list at startup and every 6 hours
  and posts it only when it changed. The host stores it apart from `scene_people`, which stays "people who appeared
  here". A group turn names a slice within the turn budget: people she knows there, the 50 most recently active,
  anyone @-mentioned lately; `find_member` searches the whole stored list. The owner accepted that this stores the
  nickname, card, role and last-active time of members who never spoke to her.
  Her design also named an on-demand platform lookup as a fallback; searching the stored list serves that need
  without a new outbound action type, and the 6-hour refresh bounds how stale it is.
- **D2 — Pictures come with a group turn.** The pictures on the line that started a full group turn come with it;
  photos (not stickers, which she recognises by fingerprint) from the 6 lines before it fill up to two in all.
  Measured on the two days before: 306 full group turns, 11 trigger-line pictures, 143 under her first proposal
  (stickers included, about 71 a day), about 45 a day as decided. Everything else stays a `read_image` call.
- **D3 — Animated pictures become a labelled contact sheet.** (Owner, 2026-10-08, after D2.) DSH normalises every
  attachment to a single frame, the first, so an animated sticker reached her as its opening frame only. Measured on
  the 48 distinct animated pictures stored: in 37 a later frame differs clearly from the first, in 31 the first
  frame is on screen for under 5% of the loop, 5 have frames of 20 ms or less, one holds a frame for 40 seconds.
  The owner proposed a filmstrip made deterministically and labelled as a lossy snapshot, since frames between the
  ones taken, and effects only a viewer of the running animation sees (fast flicker, two images seen as one), are
  lost. Of three ways to choose frames — even moments in time, the biggest changes, or even moments with the cell
  nearest each change swapped in — the owner chose **even moments in time**: a frame held long fills several
  moments, a blink usually none, and the words name what the sheet cannot show. Video input and several separate
  images were not offered: the first ties the harness to one model server, the second spends the turn's picture
  budget on one sticker. Pillow decodes the frames (the owner pre-approved adding dependencies).

## 3. As built

- D1: adapter 0.7.1 `qqadapter/members.py` (`get_group_list` → admitted groups → `get_group_member_list`, six
  fields kept, hash of the last post in `<data>/members/posted.json`), `HostApi.post_members`; host
  `POST /v1/channels/<id>/members` (`channels.ChannelServer`, 4 MiB), `src/asuna/group_members.py` (`receive`,
  `block`, `find`), collection `group_members`, `members_from_program`, `find_member`,
  `context_budget.MEMBER_LINES` and its place first in `TRIM_ORDER`. Tests: `tests/test_group_members.py`.
- D2: `role_tools.turn_pictures` (selection and pull through `read_image_for_task`), `coordinator._deliver`
  (`pictures_from_program`, the pictures counted as looked at), the stage's `pictures`, `index.js` `pictureParts`
  (saved as DSH attachments, image parts of the turn's first message). Tests: `tests/test_turn_pictures.py`,
  `native-loop.test.js`.
- D3: `src/asuna/animated.py` (`snapshot`, `seen`): every frame decoded once into a 32×32 greyscale thumbnail
  and its effective delay (a GIF delay under 20 ms plays as 100 ms), 9 moments at even intervals, neighbours that
  look the same merged, the chosen frames re-decoded into a 3-column PNG grid with order and time under each cell;
  the words (`animated`): frames, loop length and repeat, a motion tier, a tier for left-out frames that differ
  from their nearest cell, flicker runs, a long hold, the loss note. Used by both `vision` pull paths, so
  `read_image`, `turn_pictures` (`pictures_from_program` items carry the words), shelf and pool looks all get it;
  stored bytes stay the original. Over 1,500 frames or 300 million decoded pixels, or a decode failure, passes the
  original with `ANIMATION_NOT_SPLIT`. Dependency `pillow==12.3.0` (host and worker). Tests:
  `tests/test_animated.py`. On the 48 stored animated pictures the slowest sheet took 0.46 s.
