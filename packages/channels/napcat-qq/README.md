# QQ through NapCat — Asuna channel plugin

A channel package for `@asuna/cognition-core` 1.x in DSH **0.2.1-rc.2**. It registers the channel kind `qq`
with Core (`registerChannel`).

- `python/napcat_qq/` is the kind module the worker imports: QQ person ids `qq:<account>` and scene ids
  `qq:<bot>:<dm|group>:<target>`, how the adapter writes a real @ in inbound text (`@<account>`) and how her @
  reaches it (`@qq:<account>`), the media hosts vision fetches QQ images from by default, and the adapter
  settings derived from the configured channel.
- `integration/` is the NapCat / OneBot v11 adapter (`adapter.py`, `qqadapter/`, vendored `websocket-client` with its
  license). Core's integration service runs it in DSH's sandbox; the owner-granted `integration_*` tools develop
  it in this package's own development project (`napcat-qq`).
- `skills/qq-napcat-adapter/` is the adapter's skill; it joins her skill directories.
- The people a group message @-mentions are looked up like its sender (`get_group_member_info`, the same refresh and
  cache windows, at most three lookups per message) and ride on the event as `raw.asuna_mentioned`.
- After a gap (the adapter starting, or its event socket coming back) the messages missed on the routes
  `adapter_config.catchup.routes` names are fetched from history (`get_group_msg_history` /
  `get_friend_msg_history`, from a per-route time cursor in the adapter's data folder however old it is; a
  route without one looks back `lookback_hours`, 1–24) and fed oldest first through the usual inbound path,
  marked `raw.asuna_catchup`. At most 5 pages of 100 forward from the cursor, then the newest page: a longer gap
  loses lines in its middle, not the ones just before the adapter came back. Off by default.
- A merged forward (合并转发) is read before the event is posted: from the messages NapCat includes in the segment,
  else with one `get_forward_msg` call (8 s), a forward inside it one level deep, at most 3 forwards a message, 100
  messages and 20,000 characters a forward. They ride on the event as `raw.asuna_forward` (`ref`, `count`, `nodes`
  with name, account, time and text, `source` `inline` or `fetched`), and the line shows `[合并转发｜N 条｜ref]` with
  the first three messages, one short line each. One that cannot be read keeps its placeholder. The log names the
  segment's fields, the source and the count, never the text.
- A group or private-chat message that quotes another carries the quoted message's ID as `reply_to`; one that only
  quotes, with no words, also carries `raw.asuna_reply_only`. On every outbox claim the adapter declares what it
  carries: `image`, `sticker`, `file:<bytes>` (4 GiB), `react`, `poke`, `quote`, `quote_in`, `react_in`, `recall`.
- A file goes to a group alone, up to 4 GiB (QQ's single-file limit for group files); a private target is a
  `failed` receipt. Its bytes come from Core's attachment endpoint in 4 MiB pieces, each sent to NapCat's
  `upload_file_stream` (stream id = the attempt id, the whole file's sha256, NapCat's temp file named after the
  attempt), so one WebSocket message stays under 8 MiB; the adapter checks the sha256 across the pieces and NapCat
  checks it again when the stream completes. Then `upload_group_file` sends it under her name for it. The receipt
  carries NapCat's answer (its `file_id` only as data, never as an id) and the file's artifact id, sha256 and size;
  a refusal carries the platform's words as `response.platform`. Waits grow with the size: 60 s a piece,
  60 s + size / 32 MiB/s to complete the stream, 120 s + size / 1 MiB/s for the upload (4 GiB: about 70 minutes).
  An upload that outlasts its wait is `unknown`, and a later answer settles it. The outbox waits while a file is
  sent.
- A message she sends quotes a line (a leading `reply` segment) only when the outbox item carries `quote`, in a group
  or a private chat; the item's `reply_to`, the line her words answer, is not shown.
- A `recall` action in her reply takes back a message of hers (`delete_msg` on its id); the platform's retcode is
  the receipt.
- Duplicate detection binds the route, platform message ID and original send time in whole seconds. A pushed message and its catch-up copy use the same key; an ID reused at a later time is a new message. Reply attribution selects the newest matching line at or before the reply's send time.
- Each admitted group's member list (`get_group_list`, then `get_group_member_list` for the groups the admission
  policy admits) is fetched when the adapter starts and every 6 hours, reduced to id, names, role and activity times,
  and posted to Core's `members` endpoint only when it changed.
- Picture links from the NT media host are signed (`rkey`) for minutes; the picture stays. Every 4 minutes (a
  minute after a failed round) the adapter asks NapCat for its current download keys — `get_rkey`, else
  `nc_get_rkey`, else `get_rkey_server` — and posts them to Core's `media_keys` endpoint as `qq-group` (appid 1407)
  and `qq-private` (appid 1406) with the seconds each still lasts. Core signs a stored link again with them before
  fetching it. The keys are never logged or written to disk; the log says which names were posted, for how long,
  and which action answered.
- Her own role in each group (asked with `get_group_member_info` for the logged-in account, cached ten minutes)
  rides on group events as `raw.asuna_self`. Admin actions the host queues (mute, unmute, kick, recall) become
  `set_group_ban`, `set_group_kick` and `delete_msg`, and nothing else; the platform's retcode is the receipt.
- Every NapCat notice and request is projected into one line of words from a versioned table
  (`qqadapter/notices.py`, `WORDS`): a person in a group line is `@<account>` (Core shows their label), her own
  account is 你, text a person controls stays in 「」. Which kinds she is shown is the switch table `SHOWN`: a poke at
  her, a reaction (to a line of hers it asks for her look; one between others is kept for her next turn), a recall, friend and group requests, a kick of her account
  and a change of her admin role. A shown group or private-chat line goes to Core's `events` endpoint from the person
  who did it, under a message's gates, with `raw.asuna_notice` (`kind`, `gate` `poked` / `reacted`, `line`); a
  request or news about her account goes to the `notices` endpoint for her home, with the person's nickname
  (`get_stranger_info`) and, for a group she has no conversation in, its name (`get_group_info`). Her answer to a
  request comes back as an admin action and becomes `set_friend_add_request` or `set_group_add_request` with the
  request's flag. Every kind is counted, with no content: `health.json` `notices` shows today's and the last 7 days'
  counts by kind and outcome (`posted`, `home`, `own_state`, `not_shown`, `not_projected`, `unknown`, a gate that dropped it),
  kept by UTC day for 14 days in `notices/counts.json` in the adapter's data folder. Typing, connection events, her
  messages sent elsewhere and online-file transfers are counted, never projected.
- Her own mute in each admitted group goes to Core's `own_mute` endpoint. A `group_ban` notice (`ban` / `lift_ban`)
  about her account, or about the whole group (`user_id` 0), is posted at once as state (until = notice time +
  duration, the operator's account); every other notice is dropped. A send NapCat refuses with retcode 1200 and QQ
  result 120 is a `failed` receipt with `response.reason` `muted`, and that group is looked at at once. When the
  adapter starts or its event socket comes back, each admitted group not looked at in the last 6 hours is looked at,
  one a second; the times are kept in `mutes/checked.json` in the adapter's data folder. A look is
  `get_group_member_info` for her account (`shut_up_timestamp`) and `get_group_info` (`group_all_shut`), both with
  `no_cache`; it never sends, mutes or unmutes. The log (`OWN_MUTE*`) carries the group, the outcome and the seconds
  a round took.

`resources-provenance.json` records the source hashes of the distributed resources. No private configuration,
account, route, log, inbox/outbox or media is included.

## Setting up QQ

You need a running [NapCat](https://napneko.github.io/) logged in to the QQ account she uses, with its OneBot v11
**WebSocket server** enabled (forward WebSocket) and an access token. One QQ account serves one Asuna instance at a
time: two characters on one account both receive every message and both answer it. Give each running character its
own account ([Running several characters](../../../RUN_ASUNA.md#running-several-characters)).

1. **Install the package** with the persona: `--channel packages/channels/napcat-qq` to `tools/pack_plugins.py` and
   `--channel-package packages/channels/napcat-qq` to `tools/setup_native_profile.py` (or add the release `.tgz`
   with `dsh plugin add`). See [Add or remove an optional package](../../../RUN_ASUNA.md#add-or-remove-an-optional-package).
2. **Configure the channel** (`channels.qq` in the deployment; on a first install, the `channels` block of
   `asuna-channel.local.json`, template [config/asuna-channel.example.json](../../../config/asuna-channel.example.json)):
   - `account_id`: the bot's QQ number;
   - `token`: a random string of at least 24 characters, shared by the adapter and Core's channel API;
   - `routes`: at least the owner's DM, `{"sender_id", "person_id": "qq:<id>", "scene_id": "qq:<bot>:dm:<id>",
     "target": {"type": "dm", "id": "<id>"}}`. A group route has `"scene_id": "qq:<bot>:group:<group>"`, `"target": {"type": "group", "id": "<group>"}` and
     `members` (`{"<qq id>": {"person_id": "qq:<qq id>"}}`). Each person's workspace is a folder in the profile's data
     folder unless the route or member names an absolute `workspace` there. With **外部渠道接入策略** (Channel admission) `automatic` (or `--channel-admission
     automatic` at install), new DMs and groups get routes on their first valid message, so only the owner's DM
     needs configuring;
   - optional `blocked_senders` / `blocked_groups`.
3. **Link the owner** at the top level: `canonical_persons` maps `qq:<owner id>` to the local chat's person, so her
   owner in QQ and at home is one person; `context_links` (`{"<local scene>": ["<QQ DM scene>"]}`) lets the local chat read the owner's DM.
4. **Configure the adapter** (`integration` in the deployment; on a first install, `integration.local.json`):
   - `enabled: true`, and `scene_id` / `person_id` of the owner's local chat (the adapter is the owner's integration);
   - `endpoints`: the addresses the adapter may reach, each `{"name", "host": "<private or loopback IP>",
     "port": <local alias port ≥ 1024>, "target_port": <the device's port>}` — one for NapCat and one for
     Core's channel API (`127.0.0.1`, `channel_port`, default 8766);
   - `adapter_config.napcat`: `{"transport": "websocket_forward", "url": "ws://127.0.0.1:<alias port>", "token": "<NapCat
     access token>"}`;
   - `adapter_config.host`: `{"base_url": "http://127.0.0.1:<alias port>", "channel_id": "qq"}`;
   - optional `adapter_config.catchup`: `{"routes": ["<route id>", …] or "all", "lookback_hours": 6}` turns on
     catch-up after a gap for those routes (the keys of `channels.qq.routes`; under automatic admission a group or DM
     without one is `auto-group-<id>` / `auto-dm-<id>`; `"all"` means the configured routes and every admitted
     route the adapter has a cursor for).
   With `enabled: true`, the adapter starts by itself on the first start (`python3 /app/adapter.py --service`) and
   restarts with her from then on, unless its integration settings changed since it last ran other than by applying
   the settings card (it then stays stopped until `integration_start`); after an `integration_stop` it stays stopped
   until started again.
   The NapCat account id, the host token, routes and allowlists are derived from `channels.qq`; do not repeat them.
5. **Save and apply** on the settings card, then check the card's status line and send her a DM.
   `python tools/probe_qq_admission.py packages/channels/napcat-qq` checks the admission policy offline.

Tokens typed into the settings card go to DSH's credential store; the settings keep only references.
