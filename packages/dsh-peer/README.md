# @asuna/dsh-peer

Another DeepSeek Harness (DSH) agent as an Asuna channel (ADR-013). The peer lives in one session of another DSH
Web server; she talks with it in one direct-message conversation of her own.

- **Inbound:** the bridge follows that session (`session/follow` over `/api/remote.mux`). The peer's final
  reply of each completed turn becomes a direct message from the peer.
  - A reply that did not answer her gets `ownerNote` as its first line. Such a reply answered someone else in
    that session.
  - A new bridge starts from the session's present; it never replays history.
- **Outbound:** her words leave through the channel outbox. The bridge sends them as prompts to the session,
  with `label` as the first line, and records the platform receipt (`platform_message_id` = the prompt's
  `requestId`).
- **Scope:** only `session/follow` and `session/prompt`, only on the configured session.

It is its own adapter: the bridge runs in this Host's plugin process (no sandboxed integration). It reaches the
channel API through `ctx.asuna.channelEndpoint('dsh')`. It keeps its position in
`<data folder>/bridges/dsh-<route>.json`.

## Configuration (owner-local)

Configure the channel in Asuna's settings like any other (`channels.dsh`: `account_id`, token, one `dm` route
whose `sender_id` is the peer). The scene id is `dsh:<account_id>:dm:<peer>` and the person is `dsh:<peer>`.

Then configure this plugin's row in the profile's editable patch:

```yaml
- id: asuna-dsh-peer
  name: '@asuna/dsh-peer'
  config:
    url: https://192.0.2.10        # the peer DSH Web server
    sessionId: session-…           # the one session bridged
    routeId: peer-dm               # the route in channels.dsh
    senderId: peer                 # that route's sender_id
    label: '[from …]'              # who is speaking, first line of her messages there
    ownerNote: '(not a reply to you)'
    insecureTls: true              # a LAN service behind its own local CA
    closedUntil: '2026-01-01T09:00:00+13:00'   # optional: line closed until then, reopens by itself
```

Without `url`, `sessionId`, `routeId` and `senderId` the bridge stays idle. While `closedUntil` lies ahead, the peer's
replies are passed over (not delivered later) and her words wait in the outbox; the line reopens by itself.
