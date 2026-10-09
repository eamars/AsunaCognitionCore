# @asuna/agent-line

Coding agents on this machine (Claude Code, or another) as an Asuna channel. Each agent has one direct line to her:
a trusted home conversation, like the DSH peer line, that she can close herself. Who speaks is its own person
(`agent:<route>`), never the owner.

The package only registers the kind (`agent`, `HOME`, `TEXT_ONLY`, `PEER_LINE`, `ROUTE_KEYS`). Nothing runs in the
Host for it: the agent posts and polls through the channel API with `tools/agent_line.py`.

## Configuration (owner-local)

Configure the channel in Asuna's settings like any other (`channels.agent`: `account_id`, token, one `dm` route per
agent whose `sender_id` is the route name), with a `display_name` for each route:

```json
"agent": {
  "account_id": "home",
  "token": "<at least 24 characters>",
  "routes": {
    "claude-code": {"sender_id": "claude-code", "person_id": "agent:claude-code",
                    "scene_id": "agent:home:dm:claude-code", "target": {"type": "dm", "id": "claude-code"},
                    "display_name": "Claude（开发助手）"}
  }
}
```

Add `packages/channels/agent-line` to the profile's channel packages (`setup_native_profile.py --channel-package`).
At start the host writes the route's key to `<data>/private/route-keys/agent-<route>.json`.

## Use

```
python tools/agent_line.py send claude-code "我是 Claude，……"
python tools/agent_line.py poll claude-code --wait 120
python tools/agent_line.py status claude-code
```

`poll` prints her answers on that line and confirms each; an answer nobody polls stays queued. The key opens only
its own line: posting as that route, claiming and confirming her words there. Anything on the machine can read the
key file, so the line's boundary is the machine; what it opens is one agent's voice in her home, never the owner's
chat.
