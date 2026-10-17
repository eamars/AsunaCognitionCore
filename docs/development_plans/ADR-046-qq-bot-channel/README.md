# ADR-046: QQ through the official QQ Bot platform, beside NapCat

Status: **Accepted 2026-10-11, owner's direction; first step built.** The owner asked for a second QQ connection
through the official QQ Bot API. It sits at the same level as NapCat, a profile picks either or both, and it should
do what NapCat does. The first step covers the functions the two platforms share. The deployment test runs in Docker
with the 白濑栞 persona and DeepSeek `deepseek-v4-flash`.

## Context

NapCat logs in an ordinary QQ account and speaks OneBot 11. Asuna's QQ kind (`qq`, `packages/channels/napcat-qq`)
names people by QQ number, and its adapter runs in the integration sandbox. The official platform
(<https://bot.q.qq.com/wiki/develop/api-v2/>) gives a bot account of its own.

**Probed against the owner's bot, 2026-10-11:**
- The AppID and secret get a token (`bots.qq.com` and `api.bot.qq.com`, about 7,200 s).
- `/users/@me` names the bot. `/gateway` and `/gateway/bot` answer on both `api.sgroup.qq.com` and `api.bot.qq.com`
  (1,500 session starts a day).
- A WebSocket identify is answered READY for these intents:
  - `GROUP_AND_C2C_EVENT` (1<<25);
  - `INTERACTION` (1<<26);
  - `PUBLIC_GUILD_MESSAGES` (1<<30), `DIRECT_MESSAGE` (1<<12) and `GUILDS` (1<<0).

  `GUILD_MESSAGES` (1<<9, private-domain bots only) is refused with op 9.
- No IP allowlist is set.
- **Send test (the owner's private message):**
  - It reached a production and a sandbox gateway session alike.
  - Its payload has `author.user_openid` (32 hex characters, equal to `author.id`), an empty `username` and
    `union_openid`, a 117-character message id, `timestamp` with +08:00, and `message_scene.ext` `msg_idx`.
  - A reply (`msg_id`, `msg_seq` 1) and a message of the bot's own were both accepted and arrived.
  - Two sends with the same `msg_id` and `msg_seq` came back as one message (same id).
  - The owner's first message never reached either session; the cause is unknown.

**Platform rules that shape the design** (docs read 2026-10-11; pages updated 2026-07 to 2026-09):
- **Identity.** People and groups are OpenIDs that belong to this one bot. The platform never gives a QQ number, and
  `union_openid` links only bots of the same registered entity. The sender's `username` comes with each message.
- **Reach.** An uncertified bot talks only to its administrator and up to 20 test users, and only in groups where
  the administrator is the owner. Public use needs certification.
- **Groups.**
  - The bot is pushed only the messages that @ it (`GROUP_AT_MESSAGE_CREATE`), with the @ removed from `content`.
  - `GROUP_MESSAGE_CREATE`, every message, comes only after the group owner allows it in that group.
  - There is no message history and no member list.
- **Sending.**
  - A reply to a received message (`msg_id` + `msg_seq`) is accepted for 60 minutes and 4 replies in a private chat,
    5 minutes and 5 replies in a group.
  - A message of the bot's own (no `msg_id`) has quotas, a user can turn it off, and in groups it needs the group
    owner's permission. A third party saw it refused (`40034105`) in groups on 2026-10-08.
  - Group text containing a URL is refused (`40054010`).
  - Recall works only within 2 minutes.
- **Pictures.** One upload per conversation (`/files`, `file_data` up to 5 MB), then a media message (`msg_type` 7).
  Inbound pictures are attachment links.
- **Event delivery.** WebSocket or a webhook. A webhook needs public HTTPS on 80/443/8080/8443 and ed25519
  signatures. WebSocket was announced for retirement in 2024 and is documented and recommended again for
  single-machine use in 2026. The API domain moved to `api.bot.qq.com` in 2026-08.

## Decision

- **D1. A channel package of its own, at NapCat's level:** `packages/channels/qq-bot`, kind `qqbot`, title `QQ Bot`.
  - Person ids are `qqbot:<openid>`, scene ids `qqbot:<appid>:<dm|group>:<openid>`.
  - A profile installs `napcat-qq`, `qq-bot`, or both, and configures `channels.qq`, `channels.qqbot`, or both.
  - Not a second transport of the `qq` kind: the ids differ, so a person can't be the same id on both.
- **D2. The bridge runs in the Host process,** as the DSH peer bridge does.
  - The integration sandbox reaches only private and loopback addresses, and its one integration belongs to NapCat.
    Running there would mean opening her sandbox to the internet and adding a second integration.
  - Consequence: she cannot develop this adapter with `integration_*` tools; a change to it needs a Host restart.
- **D3. WebSocket gateway** (works for this bot now, no public endpoint needed). The connection lives in one method
  of the bridge, so a webhook receiver can replace it if WebSocket goes away. Base URLs are settings.
- **D4. The bot's credentials are channel settings.**
  - `account_id` is the AppID, and `app_secret` lives in DSH's credential store.
  - `channelEndpoint(kind)` now also returns the channel's settings with credential references resolved.
- **D5. Reply first, then her own message.**
  - Each outbound message replies to the received message it answers (the outbox's `reply_to`), else to the newest
    received message in that conversation that still takes replies.
  - Past the window it goes out as her own message; a refused reply is sent once that way.
  - A refusal is a failed receipt with the platform's code, which she sees as 没发出去. No core change: the delivery
    state already tells her.
- **D6. The core reads ids through the channel kind.**
  - Peer-profile checks cut group ids to 20 characters and account ids to 32. Member lists, people lookup and history
    lookup took only digits as a bare account.
  - Each now uses limits that fit any kind (ids 64, person and scene ids 80) or asks `channel_kinds`.
  - Without this, every group sender's profile was dropped (`scene_mismatch`).
- **D7. Linking people across the two connections.** Only the owner is linked, through `canonical_persons`, once
  their OpenID is known from their first private message. Everyone else is a separate person on each connection.

### Function parity (first step = the shared functions)

| NapCat function | QQ Bot, first step |
|---|---|
| Private chats, groups, automatic admission | Carried |
| Sender name (`raw.asuna_peer`) | Carried where the platform gives `username` (empty in private chats; no group card; the role is sent, see 2026-10-18) |
| @ of her wakes her; her @ of someone | Carried (`mentioned_account_ids`; `<qqbot-at-user>`) |
| Every group message, the relevance gate | Carried where the group owner allows it (`GROUP_MESSAGE_CREATE`) |
| Inbound pictures readable; video, voice, file placeholders | Carried (attachment links; voice with the platform's transcript) |
| Her pictures outbound | Carried (upload + media message) |
| Platform send time, dedupe | Carried |
| Faces `[表情:名字]` both ways | Inbound as `[表情]`; outbound later (the face syntax for bots is not documented) |
| Stickers | Later (no sticker type in the bot API; a custom sticker could go out as a picture) |
| Quotes inbound and outbound | Later (needs the platform's `ref_idx` kept per message; inbound quotes arrive in `msg_elements`, see 2026-10-18) |
| Member lists, `find_member`, group role | Member list invite-only; role sent with each message (see 2026-10-18) |
| Catch-up after a gap | Not offered (no history API); a resumed session replays what it missed |
| Mute, kick; recall | Not offered for groups; recall only within 2 minutes |
| Media-link keys (`rkey`) | Not needed until links are seen to expire |

## Consequences

- The same person reaching her through NapCat and through the bot is two people to her, unless the owner links them.
- In a group where only @ lines arrive, she sees no talk between them; her group view there is thin.
- Late words (a long task finishing after a group's 5 minutes) may be refused in groups; she sees which ones.
- The bridge's state (`<data>/bridges/qqbot.json`) holds the gateway session, the messages it may still reply to, and
  inbound messages not yet accepted by the host. No message text is logged.

## Deployment test (2026-10-11)

A new Portainer stack `asuna-shiori` runs persona `shirase-shiori` with only the `qq-bot` channel. It has its own
database and ports, automatic admission, and DeepSeek `deepseek-v4-flash` for both brains (the owner's choice). The
owner messages the bot from QQ; the Web page and the bridge log are checked.

## Group @ (2026-10-17)

The owner reported that Xiaoman's older sister, on her own QQ Bot, could not @ anyone in a group. Claude probed the
platform with that bot while the owner @-ed it in a group (21:11–21:15 NZDT). In a plain-text message
(`msg_type` 0) the platform shows both `<qqbot-at-user id="…" />` and `<@…>` as raw text; in a markdown message
(`msg_type` 2, `markdown.content`) both become a real @. Markdown also reformats `*`, `_`, a line-start `#`, `1.` or
`>`; a backslash before each keeps them as written (the space after an escaped line-start marker is lost). This
bridge sent plain text too, so it now sends a group message that @s someone as escaped markdown, and falls back to
plain text without the @ when the platform refuses markdown. The sister's own code runs on her host, which Asuna's
agents only read; the owner carries the finding to her.

## Platform facts corrected (docs read 2026-10-18)

The event pages (`GROUP_AT_MESSAGE_CREATE`, `GROUP_MESSAGE_CREATE`, updated 2026-09-16) and the group API pages were
read again on 2026-10-18 for the group-name question. Three facts above were wrong or have changed:

- **Group role.** Every group message's `author` (and each `mentions` entry) is a User with `member_role`
  (`owner`, `admin`, `member`). The bridge does not carry it yet; a use of it in her understanding of speakers goes
  through the core (people.py) and Xiaoman's agreement.
- **Inbound quotes.** A message carries `msg_elements`, each with `msg_idx`, `author`, `message_type`, `content`,
  attachments and nested elements: a quoted message arrives with the message. Not carried yet; it would touch the
  `reply_to` chain, which goes through the core and Xiaoman first.
- **Member list.** `GET /v2/groups/{group_openid}/members` (page updated 2026-09-03; members with `member_role` and
  `joined_at`, 30 a page, 60 QPM) is documented as invite-only (内邀接入中, 11253 without access). Not used.

**Group names.** The message events carry no group name. `GET /v2/groups/{group_openid}/info` (page updated
2026-08-10, 30 QPM) returns `group_name`, documented as whitelist-only (11253). Probed with Kazusa's bot on
2026-10-18 12:2x NZDT: it answered with a name for both her groups. The owner's rule (2026-10-18): a group's name
is its admins'; she reads it when the platform gives it, nobody sets one by hand. The bridge reads it once a day per
group into `raw.group_name` (`6cb18784`); a refused lookup shows no name.

**Known gap: a default name reads as a real one.** Xiaoman found in her own database (NapCat, 2026-10-18) that a
group's first `group_name` values were three member names joined with 、, and a real name came only later; why is
unconfirmed (perhaps QQ's default for a group nobody has named). Whether `/info` returns such a default for a
never-named group was not tested (no such group to probe), and the bridge cannot tell the two apart. A rename
reaches her within a day.
