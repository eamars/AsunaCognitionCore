# @asuna/qq-bot

QQ through the official [QQ Bot open platform](https://bot.q.qq.com/wiki/develop/api-v2/) as an Asuna channel. It
sits beside [QQ through NapCat](../napcat-qq/README.md): a profile may have either one or both.

- **Kind `qqbot`.** The platform names people and groups by OpenIDs that belong to this one bot, never by QQ number:
  person ids `qqbot:<openid>`, scene ids `qqbot:<appid>:dm:<user openid>` and `qqbot:<appid>:group:<group openid>`.
  Someone who also talks to her through NapCat is a different person id there; `canonical_persons` links the owner.
- **The bridge runs in this Host** (`src/bridge.js`), not in the integration sandbox. It reaches the channel API
  through `ctx.asuna.channelEndpoint('qqbot')`, and keeps its gateway session and the messages it may still reply
  to in `<data folder>/bridges/qqbot.json`. That file's `events` counts each event type the platform pushed, with
  the last time: `GROUP_MESSAGE_CREATE` there means a group sends every message, not only those that @ her.
- **Inbound:** one gateway session (WebSocket, intent `GROUP_AND_C2C_EVENT`), resumed after a drop.
  - `C2C_MESSAGE_CREATE` becomes a direct message.
  - `GROUP_AT_MESSAGE_CREATE` becomes a group message whose `mentioned_account_ids` holds the AppID, so it wakes her.
  - `GROUP_MESSAGE_CREATE`, which the platform sends only for a group whose owner let the bot receive every message,
    becomes a group message that goes through her usual group wake rules.
  - The sender's `username`, when the platform gives one, rides as `raw.asuna_peer`. In private chats it gives
    none, so a person there has no name until she learns one or `canonical_persons` links them.
  - A group message carries the group's name as the platform gives it (`raw.group_name`, from
    `/v2/groups/{group_openid}/info`), read once a day per group and kept with when it was read in the bridge's
    state file (`groups`). A bot the platform refuses that lookup gets no name, and the group shows none.
  - Other people's @ read as `@<openid>`.
  - Pictures and videos arrive as `[图片（未解析）]` / `[视频（未解析）]` with their link in `raw.asuna_media`, so she
    can read them (a video as a contact sheet). Voice and files arrive as placeholders; a voice message carries the
    platform's transcript when it has one.
  - Platform faces read as `[表情]`.
  - The platform's own send time is `occurred_at`. A message pushed twice is posted once.
- **Outbound:** her words, with one picture where the outbox item carries one (`supports=image`). She speaks here
  only through `speak`, in text and picture parts (the kind's `REPLY_PARTS`); the bridge declares no quote, reaction
  or recall, so those are not shown to her here.
  - Each message goes out as a reply (`msg_id`, `msg_seq`) to the message she answers while the platform still
    takes replies to it (60 minutes and 4 replies in a private chat, 5 minutes and 5 replies in a group, less a
    15-second margin); after that, as a reply to the newest received message in that conversation that still takes
    one; when none does, as her own message.
  - When the platform refuses a reply, the message is sent once as her own message. A refusal of that is a failed
    receipt with the platform's code. The platform may refuse her own messages in a group, or from someone who
    turned them off.
  - A group message with her @ of a person goes as markdown (`msg_type` 2): her @ becomes the platform's
    `<qqbot-at-user>` and her other markdown characters are escaped, so her words read as written. Plain text
    cannot carry an @. A bot the platform refuses markdown (304036, 40034127, 50056) sends her words once as
    plain text without the @. Elsewhere (a private chat, a picture message) the @ is left out.
  - A picture is read from the channel API and checked against its digest. It is uploaded for that one conversation
    (`file_data`, at most 5 MB) and sent as a media message with her words.
- **Not carried:** stickers, faces outbound, quotes, recall and group admin actions, member lists, and catch-up
  after a gap. The platform gives a bot no message history and no group member list.

## Setting up the bot

1. **Create the bot** on the [QQ open platform](https://q.qq.com/) and note its **AppID** and **AppSecret**.
   - Until the bot is certified and published, it talks only to its administrator and to the test users added in
     the console, and only in groups where the administrator is the owner.
   - Its event delivery mode must be **WebSocket**.
   - The IP allowlist, when one is set, must hold the address this Host calls from.
2. **Install the package** with the persona: `--channel packages/channels/qq-bot` to `tools/pack_plugins.py` and
   `--channel-package packages/channels/qq-bot` to `tools/setup_native_profile.py`.
3. **Configure the channel** (`channels.qqbot` on the settings card, or the `channels` block of the channel settings
   on a first install):

   ```json
   "qqbot": {
     "account_id": "<AppID>",
     "app_secret": {"$secret": "ASUNA_CHANNELS_QQBOT_APP_SECRET"},
     "token": {"$secret": "ASUNA_CHANNELS_QQBOT_TOKEN"},
     "routes": {}
   }
   ```

   - `token`: a random string of at least 24 characters for the channel API, as for any channel.
   - `app_secret` lives in DSH's credential store. A first-install file may hold the plain value, which the
     installer moves there.
   - With **外部渠道接入策略** (Channel admission) `automatic`, every private chat and group the bot is reached in gets its route on its
     first message, so no route needs configuring.
   - Optional fields:
     - `api_base` (default `https://api.sgroup.qq.com`) and `token_url` (default
       `https://bots.qq.com/app/getAppAccessToken`), when the platform moves them;
     - `intents` (default `33554432`, private chats and groups).
4. **Link the owner.** Send the bot a private message. Their person id `qqbot:<openid>` is then in the admitted
   route `auto-dm-<openid>`. Add `"qqbot:<openid>": "<the local chat's person>"` to `canonical_persons`, and that DM
   scene to `context_links` if the local chat should read it. **Save**, then **Apply saved settings**.

The Host log says `qq-bot: connected as <bot name>` once the session is up, and why when it is not. It never logs
message text.
