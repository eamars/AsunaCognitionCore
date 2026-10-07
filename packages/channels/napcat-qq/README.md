# QQ through NapCat — Asuna channel plugin

A channel package for `@asuna/cognition-core` 0.2.x in DSH **0.2.0-rc.2**. It registers the channel kind `qq`
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
  `get_friend_msg_history`, from a per-route time cursor in the adapter's data folder, at most
  `lookback_hours` back, 1–6) and fed oldest first through the usual inbound path, marked `raw.asuna_catchup`.
  Off by default.
- Her own role in each group (asked with `get_group_member_info` for the logged-in account, cached ten minutes)
  rides on group events as `raw.asuna_self`. Admin actions the host queues (mute, unmute, kick, recall) become
  `set_group_ban`, `set_group_kick` and `delete_msg`, and nothing else; the platform's retcode is the receipt.

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
     "target": {"type": "dm", "id": "<id>"}}`. A group route has `"target": {"type": "group", "id": "<group>"}` and
     `members` (`{"<qq id>": {"person_id": "qq:<qq id>"}}`). Each person's workspace is a folder in the profile's data
     folder unless the route or member names an absolute `workspace` there. With **QQ 接入策略** `automatic` (or `--channel-admission
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
   - `adapter_config.napcat`: `{"transport": "websocket_forward", "url": "ws://<ip>:<alias port>", "token": "<NapCat
     access token>"}`;
   - `adapter_config.host`: `{"base_url": "http://127.0.0.1:<alias port>", "channel_id": "qq"}`;
   - optional `adapter_config.catchup`: `{"routes": ["<route id>", …] or "all", "lookback_hours": 6}` turns on
     catch-up after a gap for those routes (the route ids are the keys of `channels.qq.routes`).
   With `enabled: true`, the adapter starts by itself on the first start (`python3 /app/adapter.py --service`) and
   restarts with her from then on; after an `integration_stop` it stays stopped until started again.
   The NapCat account id, the host token, routes and allowlists are derived from `channels.qq`; do not repeat them.
5. **Save and apply** on the settings card, then check the card's status line and send her a DM.
   `python tools/probe_qq_admission.py packages/channels/napcat-qq` checks the admission policy offline.

Tokens typed into the settings card go to DSH's credential store; the settings keep only references.
