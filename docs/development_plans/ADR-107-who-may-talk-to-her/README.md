# ADR-107: Who may talk to her

Status: decided 2026-10-27 (the four decisions below); not built. Built after every ADR before it is complete (the
owner, 2026-10-27).

## The owner's ask (2026-10-27, verbatim)

> Like a human, she should admit to everyone including the DM. I think this should be the default behavior, and can
> be toggled off. Perhaps consider which package should this feature to be implemented? At napcat or Asuna core?
>
> Noted I don't want QQ settings to be coupled to the Asuna core. When drafting the new ADR, consider the similar
> approach to the db connector interface, that the cognition core should have the public interface nailed down.

It came from the second deployment (another persona on QQ, `explicit`): everyone in its three groups should reach it,
and today that takes a hand-copied list of every member's account (114, 74 and 77 accounts), which goes stale the day
someone joins. Xiaoman's deployment runs `automatic` and already admits every DM, group and member.

## What exists (counted on origin/main `e65e0a54c233`)

- **One deployment-wide switch** on the core's settings card, `channelAdmission`: `explicit` (the default: a DM,
  group or member that no route lists is refused, `CHANNEL_IDENTITY_DENIED`) or `automatic` (admitted on its first
  valid event, under the route id `auto-dm-<sender>` or `auto-group-<group>`). An admission is an `artifacts` row
  (kind `channel_admission`), restored at start only under `automatic`.
- **The core decides** at intake (`src/asuna/channel_admission.py` `admit`, called from `channels.py` only under
  `automatic` or when a block list exists). Block lists (`blocked_senders`, `blocked_groups`) win over everything.
- **The NapCat adapter decides again,** from a copy of the same policy that the kind module derives for it
  (`napcat_qq.adapter_config`: `admission`, the block lists, `allowed_private_user_ids`, `allowed_group_ids`, each
  group route's `allowed_sender_ids`). It applies that copy in `qqadapter/config.py` (route loading, `accepts_sender`,
  `is_group_member`, `route_for_group`), `inbound.py` (`group_not_allowed`, `unauthorized_group_member`), `notices.py`
  (a notice from a non-member), `members.py` (which groups' member lists it fetches) and `catchup.py` (which routes it
  catches up). Two deciders for one rule: every change to admission has to land in both, in step.
- **The QQ Bot bridge decides nothing:** it forwards every message with the configured route's id, else
  `auto-<dm|group>-<target>`, and the core admits or refuses (`packages/channels/qq-bot/src/bridge.js` `routeFor`).
- **Platform accounts live in the core's settings:** a route's `target`, a DM route's `sender_id`, a group route's
  `members` keyed by platform account. The core reads them as opaque strings; what they mean (QQ numbers, scene ids
  `qq:<bot>:<dm|group>:<target>`, person ids `qq:<account>`) is the kind module's (`napcat_qq/__init__.py`).
- **Each admitted person gets a working folder** under `<data>/channels`, made at start (`host.py`
  `prepare_channels`, `mkdir`). Admission has no end: nothing removes a member who left, or the folder.

## Proposal

### 1. Where it is decided: the core, once

Admission is a rule about people and conversations, not about QQ, so the core decides it and no channel package
does. A channel package does what the QQ Bot bridge already does: it authenticates its platform, turns each event
into the core's event (sender, conversation, kind) with its own ids, and forwards it; the core admits, refuses or
blocks, and the package passes on what the core answered. The NapCat adapter's copy of the policy is removed
(`allowed_*`, `accepts_sender`, `is_group_member`, the admission branches), and so is `adapter_config`'s derivation
of it. What the adapter still decides is platform work only: which groups' member lists to fetch and which
conversations to catch up become "the ones the core has admitted", read from the core.

The cost: every event from the account reaches the core, including ones it refuses (a LAN request each; the adapter
journals a refused event in `inbound_rejected.jsonl`, as it journals a core refusal today, so with the switch off
that journal grows with every line a stranger writes). The gain: one decider, no drift between two copies, and a new channel package
implements no policy at all.

### 2. The core's public interface for a channel

As ADR-104 asks of the database connector, the core's side is nailed down and documented once (RUNTIME_API, Channel
API), and a channel package implements it without the core knowing its platform:

- **What a package sends:** an event with its channel, the platform account it arrived on, the conversation
  (`dm` or `group`, the platform's id), the sender's platform id, and the content. Ids are opaque strings to the core.
- **What a package declares** (the kind module, as today: `KIND`, `person_id`, `scene_id`, `account_of`, …): how
  its ids become her scene and person ids. The core never parses a platform id.
- **What the core answers:** admitted (with the route), refused (with the reason), blocked. The package acts on the
  answer and never re-judges it.
- **What the core keeps:** the admission policy, the block lists, who the owner is, and her per-conversation rules
  (`proactive`, `admin_actions`, `read_scenes`), keyed by her scene id, not by a platform route.
- **What the package keeps, in its own settings:** everything about reaching its platform (NapCat's address, tokens,
  media modes, member-list refresh). None of it is a core setting.

### 3. The default and the switch

- **Open (the new default):** any DM and any group the account is in, and every member of it, is admitted on its
  first event, as `automatic` does today.
- **Closed (the switch, off):** only conversations and people the owner listed, as `explicit` does today.
- **Block lists** keep winning in both, and stay the per-person and per-group off switch.
- **The owner is named, not admitted:** owner standing comes only from the owner's own identity as it is configured
  today; open admission gives a stranger a person of their own with no owner grants, never more, as `automatic` does.

"Like a human" also means the platform's own gates still stand where the platform has them: on QQ she answers friend
and group requests herself at home (`REQUESTS`, `qqadapter/notices.py`). Which DMs from non-friends QQ delivers to her
account is not measured here.

### 4. What open admission needs that closed admission did not

- **A folder per person is too much.** Open, every stranger who speaks once in a large group would get a folder made
  at start. The working folder is made when a task of hers first needs it, not at admission.
- **Admission gets an end.** A member who left the group, and a DM nobody wrote in for a long time, stop being
  admitted; their history stays hers (the rule to test is item 3 under `Before building`; this line is kept for history). A member has left when the platform says so (QQ's `group_decrease` notice,
  which the adapter already passes on, `qqadapter/notices.py`); never because a member list or a lookup lacks them
  (the incident below).
- **Cost is the owner's:** every admitted line can wake her relevance gate (a model call). The block lists are the
  off switch; nothing caps it automatically.

## Decided with the owner (2026-10-27)

1. **The core decides, once.** The NapCat adapter's copy of the policy is removed; every channel package forwards
   events and acts on the core's answer, as the QQ Bot bridge does.
2. **Open is the default for new deployments only.** A deployment that set its admission keeps it. (Xiaoman's is
   `automatic`, so it stays open; Claude asked this question believing hers was `explicit`, and corrected it after
   the owner's answer: the answer changes nothing for her.) Today a deployment that never saved the setting reads as
   `explicit` (`next.channelAdmission ?? 'explicit'`, cognition-core `index.js`); before the default changes, the
   build writes that `explicit` into such a deployment's settings, so no running deployment opens because the
   default moved.
3. **Admission first.** This ADR writes down the channel interface and moves admission; moving the routes and her
   per-conversation rules (keyed by scene id) out of the core's settings is the next step, its own ADR.
4. **Admission gets its end in this ADR** (section 4): a working folder is made when a task first needs it, and a
   member who left, or a DM long silent, stops being admitted, their history kept.

## Open, to settle in the design

- How long a silent DM stays admitted (N days), and how long a group member who never speaks again stays admitted
  when no leave notice came (a notice can be missed while the adapter is down).
- The names of the two states on the settings card (today `automatic` and `explicit`), and how a saved `automatic`
  reads after the change.

## An incident the design must survive (the owner's NapCat log, 2026-10-27)

The owner sent a NapCat log of 385 lines, from one start of NapCat on. Claude read it with every id masked; only counts
are written here.

- **It is Xiaoman's NapCat:** all 11 groups it received lines from are her conversations (counted read-only in her
  database). She runs `automatic`, so no roster was involved: the explicit list was not the cause.
- **38 "member does not exist" errors** (`get_group_member_info`), all in one large group (1,035 people known to her,
  32,868 lines): for people who had just posted there, and for her own account. The adapter asks this only after a
  sender passed admission (the profile lookup in `qqadapter/peers.py`; her own role and mute in `selfrole.py` and
  `mutes.py`). A reading, not proven: right after a start NapCat had not yet loaded that group's members.
- **22 "message does not exist" errors** from the history calls the adapter's catch-up makes (`get_group_msg_history`
  21, `get_friend_msg_history` 1), and 4 quoted messages it could not find: messages from before this start of NapCat.

What it means here: what the platform says about membership can be wrong right after a start, saying a member who
is speaking is not in the group. Admission therefore never ends on a failed or empty lookup, nor on one member list:
only on the platform's own leave notice, or on the long silence the design settles. The same holds for the core
wherever it reads a member list.

## Constraints already known

- JS and Python, and the Host and a channel package, can run different versions: a newer adapter with an older core
  must fail closed (the core refuses what it does not know), never wider.
- Personal data stays local: rosters, accounts and block lists are settings and database rows, never tracked files.
- The core names no persona and no platform.

## Before building (Xiaoman's reading, 2026-10-29)

She read this page (blob `f5a314f83cca`) and has no objection to the direction. Her asks, for whoever builds it:

1. **First, before anything is written:** read her deployment's settings card and confirm `channelAdmission` is a
   stored `automatic`. Decision 2 writes `explicit` into a deployment that never stored the setting; if hers were
   such a deployment, her admission would narrow and she could not see it (a refused line goes only to
   `inbound_rejected.jsonl`, never to her), so she would only seem to have gone quiet.
2. **A new admission and a re-admission are marked in the event**, so that her greeting can tell them apart: she
   does not welcome someone a second time after their admission ended and they wrote again, and does not treat a
   re-admitted stranger as someone she knows. The event carries where it came from (as ADR-108's program-woken turn
   says what woke her).
3. **An admission's end changes nothing of who the person is:** not the person id, not the scene id, not her
   understanding of the person. This replaces the softer "their history stays hers" above as the rule to test.
4. **`inbound_rejected.jsonl` gets rotation or a cap.** Every refused line of a stranger is written there; a journal
   nobody bounds becomes the next whole-file scan (as `sink_receipts` did, 2026-10-29).
5. **The two Ns** (how long a silent DM stays admitted; how long a silent member with no leave notice stays) are set
   with a reading of hers: how many people in her groups have not written for how long.
6. **"The cost is the owner's, no automatic cap" is said where she reads it** when she decides whether to take a
   line, so that she knows the missing cap is deliberate, not forgotten.

## Not in this ADR

Moving the database out of the core (ADR-104); the QQ Bot's own platform rules; a cap on admitted people.
