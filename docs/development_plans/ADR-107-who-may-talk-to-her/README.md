# ADR-107: Who may talk to her

Status: decided 2026-10-27 (decisions 1 to 4); the owner decided two more on 2026-10-29 (5 and 6); the design was
finished, reviewed against the code and built 2026-10-29 on branch `claude/happy-meitner-vrg19f` by the cloud big sis
(Claude Code, the lead on this project): [design.md](design.md). Installed 2026-10-30 16:02 as `ac620ad17d40`, in one install by the owner's
decision (the core, the adapters and her gate prompt line). Xiaoman read this page and design.md at `ac620ad1` before
the install; her words and her confirmation after it are in the index row.

## The owner's ask (2026-10-27, verbatim)

> Like a human, she should admit to everyone including the DM. I think this should be the default behavior, and can
> be toggled off. Perhaps consider which package should this feature to be implemented? At napcat or Asuna core?
>
> Noted I don't want QQ settings to be coupled to the Asuna core. When drafting the new ADR, consider the similar
> approach to the db connector interface, that the cognition core should have the public interface nailed down.

It came from the second deployment (another persona on QQ, `explicit`): everyone in its three groups should reach it,
and today that takes a hand-copied list of every member's account (114, 74 and 77 accounts), which goes stale the day
someone joins. Xiaoman's deployment runs `automatic` and already admits every DM, group and member.

In scope: open admission as the default for new deployments with a switch to turn it off; where it is decided; the core's
public interface for a channel. Anything wider is said as wider.

## What exists (counted on main `196b6f6bbeaa`; the commands and the full census are in [design.md](design.md))

- **One deployment-wide switch,** `channelAdmission`: `explicit` (a DM, group or member that no route lists is refused,
  `CHANNEL_IDENTITY_DENIED`) or `automatic` (admitted on its first valid event under the route id `auto-dm-<sender>` or
  `auto-group-<group>`), applied to every channel. An admission is an `artifacts` row (kind `channel_admission`),
  restored at start only under `automatic`.
- **The core decided at intake** (`channel_admission.admit`), and **the NapCat adapter decided again** from a copy of
  the same policy that the kind module derived for it (70 lines in eight adapter files). Two deciders for one rule. The
  QQ Bot bridge decided nothing but built `auto-…` route ids itself.
- **Platform accounts live in the core's settings** (a route's `target`, a DM route's `sender_id`, a group route's
  `members`); the core reads them as opaque strings.
- **Each admitted person got a working folder** at start. Admission had no end.
- **The core's decider had no unit test.**

## Proposal

The core decides, once. A channel package authenticates its platform, turns each event into the core's event with its own
ids, asks the core one question before it spends work on a sender, and acts on the answer. Open (`automatic`) is the
default for a new profile; Closed (`explicit`) lists what the owner named; block lists win in both; the owner is named in
the settings, never admitted. The public interface is documented once in RUNTIME_API (Admission, ask what the core
admits, the routes the core serves, post a departure) and exercised by a contract test against a stand-in kind. How,
with the failure modes and the landings, is in [design.md](design.md).

## Decided

1. **The core decides, once.** The NapCat adapter's copy of the policy is removed; every channel package forwards events
   and acts on the core's answer. (Owner, 2026-10-27.)
2. **Open is the default for new deployments only.** A deployment that set its admission keeps it. (Xiaoman's is
   `automatic`, so it stays open.) A profile that reads `explicit` only because it never stored a value is written
   `explicit` by the setup tool before the default moves; every code fallback stays `explicit`. (Owner, 2026-10-27;
   where the pin lives: design.)
3. **Admission first.** Moving the routes and her per-conversation rules (keyed by scene id) out of the core's settings is
   the next step, its own ADR. (Owner, 2026-10-27.)
4. **A working folder is made when a task first needs it,** and an admitted member's admission can end. (Owner,
   2026-10-27.)
5. **A DM never ends by silence.** The route is also how she writes to that person; ending it would take away writing
   first and keeping a plan for them, and a one-member conversation has no membership to correct. (Owner, 2026-10-29.)
6. **A group member's admission ends only on the platform's leave notice** (QQ's `group_decrease`), never because a
   member list or a lookup lacks them (the incident below), and there is no silence rule and no sweep. (Owner,
   2026-10-29.) The end is a mark on the grant, not a removal (design F6).
7. **The stored words stay `explicit` and `automatic`;** the settings card says Closed and Open. (Design.)
8. **Open applies to the kinds that declare `OPEN_ADMISSION`,** never to a home line. (Design.)

"Like a human" also means the platform's own gates still stand where the platform has them: on QQ she answers friend
and group requests herself at home. Which DMs from non-friends QQ delivers to her account is not measured here.

## An incident the design had to survive (the owner's NapCat log, 2026-10-27)

The owner sent a NapCat log of 385 lines, from one start of NapCat on. Claude read it with every id masked; only counts
are written here.

- **It is Xiaoman's NapCat:** all 11 groups it received lines from are her conversations. She runs `automatic`, so no
  roster was involved: the explicit list was not the cause.
- **38 "member does not exist" errors** (`get_group_member_info`), all in one large group (1,035 people known to her,
  32,868 lines): for people who had just posted there, and for her own account. The adapter asks this only after a
  sender passed admission. A reading, not proven: right after a start NapCat had not yet loaded that group's members.
- **22 "message does not exist" errors** from the history calls the adapter's catch-up makes, and 4 quoted messages it
  could not find: messages from before this start of NapCat.

What it means here: what the platform says about membership can be wrong right after a start, saying a member who is
speaking is not in the group. Admission therefore never ends on a failed or empty lookup, nor on one member list.

## Constraints

- JS and Python, and the Host and a channel package, can run different versions: a newer adapter with an older core
  fails closed (holds its lines, posts none), and the core ships first and additively (design section 8).
- Personal data stays local: rosters, accounts and block lists are settings and database rows, never tracked files.
- The core names no persona and no platform.

## Xiaoman's reading of the earlier version (2026-10-29) and where each ask went

She had no objection to the direction. Her asks:

| Ask | Where it is |
|---|---|
| 1. Before anything is written, read her settings and confirm `channelAdmission` is a stored `automatic`. | `tools/setup_native_profile.py --require-admission automatic` exits 1 unless it is; it is the first step of landing 1. |
| 2. A new admission and a re-admission are marked in the event. | `event.admitted` is `new` or `returned`; her conversation says it once after the time of that line (design 6.4). |
| 3. An end changes nothing of who the person is. | By construction (only `ended_at` on the grant) and tested: the scene, its epoch, the person and the roster are as they were. |
| 4. `inbound_rejected.jsonl` gets rotation or a cap. | Every adapter journal rotates at 8 MiB; a stranger's refused line is no longer journaled (design 7.7). |
| 5. The two Ns, set with a reading of hers. | They fall away with the silence rules (decisions 5 and 6). |
| 6. "The cost is the owner's, no automatic cap" said where she decides whether to take a line. | One line in the relevance gate's prompt, on its own landing, hers to read first (design 6.6). |

## Not in this ADR

Moving the database out of the core (ADR-104); the QQ Bot's own platform rules; a cap on admitted people; a silence rule
for a DM or a member.
