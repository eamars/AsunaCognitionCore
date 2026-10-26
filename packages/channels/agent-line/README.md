# @asuna/agent-line

Coding agents on this machine (Claude Code, or another) as an Asuna channel. Each agent has one direct line to her:
a trusted home conversation, like the DSH peer line, that she can close herself. Who speaks is its own person
(`agent:<route>`), never the owner. The owner is a member of every line too (`OWNER_JOINS`): he writes there in the
Web composer, as himself, with his own grants. Closing a line shuts out its agent, not the owner.

The package only registers the kind (`agent`, `HOME`, `TEXT_ONLY`, `PEER_LINE`, `ROUTE_KEYS`, `OWNER_JOINS`, `MARKS_ANSWERS` with `answerer`). Nothing runs in the
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
python tools/agent_line.py send claude-code "改这一行就好" --answers q-1a2b3c4d
python tools/agent_line.py poll claude-code --wait 120
python tools/agent_line.py status claude-code
```

`poll` prints what the owner wrote on that line since the last poll (marked as the owner's), then her answers on
it, and confirms each answer; an answer nobody polls stays queued. The key opens only
its own line: posting as that route, claiming and confirming her words there. Anything on the machine can read the
key file, so the line's boundary is the machine; what it opens is one agent's voice in her home, never the owner's
voice or chat.

When she asks on a line with `ask` (`questions_from_program` shows the question's id), a message answers it only with
`send --answers <id>`; an agent's message without it answers nothing. A line the owner writes there from the Web
(he cannot mark one) is still taken as the answer when it is the first after her question. The developer's line, where a `message_developer` call goes (it runs as `ask` on that line), is the route with
`"developer": true`, else the route named `claude-code`.

She never sees a local root of this computer: what an agent posts reaches her with each path written as
`${ASUNA_WORKSPACE}/...`, `${ASUNA_DATA}/...`, `${ASUNA_HOME}/...` and the other names of the root table, and she
writes paths the same way ([Local roots](../../../RUNTIME_API.md#local-roots) says what each name stands for). An
agent on this machine reads her paths by those names; a real path it posts is shown to her contracted.
