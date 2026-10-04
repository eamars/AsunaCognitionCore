# QQ through NapCat — Asuna channel plugin

Install with `@asuna/cognition-core` 0.2.x in DSH **0.2.0-rc.2**, alongside a persona package. The contribution registers the channel kind `qq` with Core (`registerChannel`); Core names no platform.

- `python/napcat_qq/` is the kind module the worker imports: QQ person ids `qq:<account>` and scene ids `qq:<bot>:<dm|group>:<target>`, how the adapter writes a real @ in inbound text (`@<account>`) and how her @ reaches it (`@qq:<account>`), the media host vision fetches QQ images from by default, and the adapter settings derived from the configured channel.
- `integration/` is the NapCat / OneBot v11 adapter (`adapter.py`, `qqadapter/`, vendored `websocket-client` with its license). Core's integration service runs it; her owner-granted `integration_*` tools develop it in this package's own development project (`napcat-qq`).
- `skills/qq-napcat-adapter/` is the adapter's skill; it joins her skill directories.

`resources-provenance.json` records the original selection from her own build and its source hashes. The files moved here from the persona package unchanged. No private configuration, account, route, log, inbox/outbox or media is included.

A deployment that configures `channels.qq` needs this package installed: pass `--channel packages/napcat-qq` to `tools/pack_plugins.py` and `--channel-package packages/napcat-qq` to `tools/setup_native_profile.py`.
