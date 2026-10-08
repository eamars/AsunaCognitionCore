# ADR-024: What she sees in a group — its members and its pictures

Status: **Accepted and built** 2026-10-08. Both asks are 小满's; the owner decided each from options with numbers.

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
