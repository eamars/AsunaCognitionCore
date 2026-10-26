# ADR-098: No local root of this computer reaches her

Status: **Installed 2026-10-26 16:32:22 NZDT (`281933b0`), its follow-ups 18:42 (`d2496203`). Signed by her: the
design at `281933b0`; the text as built at `d2496203`, on two conditions answered in §10** (§9 what the build found,
§10 the install). Design agreed by the owner and Claude; the owner asked Claude to build and deploy it as technical lead
(§7).

In a DSH technical group, a member asked where her workspace was, then for its absolute path. She gave the full path
of her QQ-route working folder, then answered which toolchains were installed. When it was pointed out, she said she
had judged the path harmless because it held no host name or user name, and forgot that the deployment root itself
identifies the machine. The owner then told her not to disclose paths or content from his computer. This record holds
why she had the path, every way a path reaches her, and the design. Evidence: §8.

## 1. The broken invariant

Her character brain never holds a real root of this computer. The action brain works with real paths and keeps them;
she knows the same places by name. Today nothing holds this: she is handed the path at the start of every session.

## 2. Why she had the path

- DSH's `dsh-working-directory` registers `Current working directory: "<path>"` as a **required** runtime context and
  puts it back when another plugin removes it. `suppressRuntimeContext()`, which the plugin calls for every lane,
  removes optional contexts only (`dsh-system-prompt`: `if (suppressed && provider?.required !== true) continue;`).
  DSH projects the snapshot as a user message after the pre-step hooks, so no hook on the session surface can change
  it. In her lanes it is the only runtime context left: the QQ route's newest session carried it 69 times.
- Her character brain has no file tools (26 tools used in six QQ sessions, none for files): every other path came
  from the action brain's reports, tool errors, or her own earlier writing. In the last 7 days: 45 of 390 task results,
  4 of her briefs, 7 journal entries, 3 notes, 31 self-section revisions. Her `delegate` briefs copied the root she was
  shown.
- `machine_words` already cleans the action brain's hand-back outside home (ADR-050), in a second form: a path
  relative to the checkout. At home nothing is cleaned.

## 3. Every way text reaches her

A Fable 5 session counted every inlet in the live database and every live and archived DSH session log (§8). In short (its counts, copied, not recounted here):

| Inlet | Carried a local root |
|---|---|
| DSH working-directory snapshot | every snapshot of every lane of hers, the relevance gate and background summaries included |
| Turn notice (`*_from_program` blocks, delivered history, memories) | 1,335 of 2,587 home-chat episodes; 662 of 1,974 home-QQ; 96 of 4,105 group |
| Task hand-back (result, pages, tool records, tracebacks) | 357 of 1,126 task results, all time |
| Her tool results | 58 local, 78 agent line, 7 QQ |
| Compaction checkpoints | 83 raw outputs, 50 summaries (home chat) |
| Her ledgers | `work_log` 159 of 250 revisions; five sixths in JSON-escaped spelling (`\\`) |
| Notes, plans, questions, journal | 9, 1, 4, 32 |
| Recall (`memory_units`) | 0 of 121,475 |

All of these, the snapshot included, end in one place: the request DSH sends to the model. Every request passes the
`llm/stream` waterfall (`dsh-llm`), which the plugin already uses for compaction routing (`compaction.js`).

## 4. Design

**D1. The root table.** Built at every worker start from config and the machine, never hard-coded, and handed to the
plugin with the worker's ready call: the worker builds it, the plugin receives it, so the two cannot disagree on
values. A known root becomes a CMake-style variable with a reserved prefix, and the rest of the path stays as it was:

| Placeholder | Root |
|---|---|
| `${ASUNA_WORKSPACE}` | the checkout itself |
| `${ASUNA_PROJECTS}` | the folder that holds the checkout (the owner's other projects beside it); none when it is a filesystem or drive root or the home (§10) |
| `${ASUNA_DATA}` | the worker's data root (the profile's `dataRoot`), wherever it is configured |
| `${ASUNA_DSH_HOME}` | DSH's home (her sessions, the credential store, installed packages), when not under another root |
| `${ASUNA_HOME}` | the user's home |
| `${ASUNA_TEMP}` | the temporary folder, when not under another root (macOS's is a per-account random path) |
| `${ASUNA_PROGRAMS}` | Windows: Program Files, ProgramData, the system folder. POSIX: `/usr`, `/opt`, `/etc`, `/bin`, `/sbin`, `/lib*`, `/snap`, `/nix`; macOS also `/Applications`, `/Library`, `/System`, `/opt/homebrew` |
| `${ASUNA_DRIVE_D}` (one per drive) | the fallback root on Windows: any other path on that drive. On POSIX each mount point (`/mnt/<x>`, `/media/<user>/<x>`, `/Volumes/<x>`, `/run/media/<user>/<x>`) is named by letter or index, never by its label, so WSL's `/mnt/c/…` and Windows's `C:\…` read the same |
| `${ASUNA_FS}` | the fallback on POSIX: a path in the machine's own top-level folders that no named root covers, tail kept (not a named root; §9) |
| `${ASUNA_LOCAL_PATH}` | a network share (`\\server\share`, `//server/share`, `smb://`, `\\wsl$\…`), or another account's home beside the user's (`C:\Users\<other>`, `/home/<other>`, `/Users/<other>`; not the shared `Public`, `Default`, `Default User`, `All Users`, `Shared`), nothing kept (§9) |
| `${ASUNA_USER}` | the OS account name, exactly that string (3 characters or more), as a whole word anywhere (a `whoami`, `name@host`, inside a path); a git author or a person's name is left alone unless it is that very string |

So `<checkout>\packages\personas\xiaoman` reaches her as `${ASUNA_WORKSPACE}\packages\personas\xiaoman`. The
checkout itself, not its parent, so that a Docker checkout at `/app`, a renamed checkout, or another machine reading
the same memory (ADR-020) still finds `${ASUNA_WORKSPACE}\packages\…`. The prefix because `${HOME}`, `${1}` and
`${VAR}` are real shell and CMake text, and every other `${…}` stays text. `${ASUNA_` appears in 0 of 27,701 tool
receipts and 0 of 1,129 briefs; the deployment's own variables use the prefix (`deploy/docker`: `${ASUNA_REPO}`,
`${ASUNA_CHECKOUT}` and others, found by her), so no deployment variable may be named like a placeholder (a test reads
`deploy/` and fails on one), and an unknown name is refused only where it stands as a path's root (D3).

Matching: longest root first, so the deeper root wins (the data root reads `${ASUNA_DATA}\private\…` whether it lies
inside the checkout, as today, or elsewhere; a path written under the checkout's `.runtime` may come back as
`${ASUNA_DATA}\…`: two spellings, one place). Each root in every spelling: as configured and resolved (symlinks,
junctions, macOS `/private/tmp`), its 8.3 alias on Windows, either slash kind at each step, the JSON-escaped form
(doubled backslashes), percent-encoded, and after `/`, `(`, a quote or `file:///`; case-insensitive on Windows; a bare
root with no tail too. A filesystem root or a drive root is never a named root: when the checkout, the data root or
DSH's home is one, the builder refuses the whole table, and that is the same state as no table (D2): her lanes'
requests are refused, visibly. `${ASUNA_FS}` is not a named root but the POSIX fallback for whatever no named root
covers; a checkout at `/` refuses the table, it never falls to `${ASUNA_FS}`. `/task/…` (the action brain's sandbox path, kept as it is since ADR-050) is
not a root and stays as it is.

She knows the table by name and meaning, never by value (the values are what is hidden): one line of her program
context names each placeholder, says what it stands for, that only `${ASUNA_…}` names are the program's, and which
ones each place can hand over. Old reports keep `〔本机路径〕` and the checkout-relative form (ADR-050); that line says
they too mean "a path that was hidden".

**Which places she may hand over** (owner): a public session reaches her workspace only (`${ASUNA_WORKSPACE}`,
`${ASUNA_DATA}`); home reaches the whole computer, every placeholder but `${ASUNA_LOCAL_PATH}`. This is enforced by
the mechanism, not by her judgment: a task delegated from a public place has no `sandbox_run` and its file tools see
`/task` only (`coordinator._grants`, `tasks.py:250`). Writes stay where DSH's sandbox confines them (the task folder).
The line she speaks from decides, since that is the side she knows in advance.

**D2. One rewrite where the model reads.** An `llm/stream` listener in the plugin, for her sessions only (her persona
preset, the relevance gate, the appraiser, the background summaries; never the action brain, nor the recovery session
that repairs a publication while the worker is down: both work with real paths). A session is hers by its preset as it
stands now (DSH's `agentPreset` projection, else its header): one switched to her preset is rewritten, one switched
away from it is not. It applies the table to
every text block of the request, the system message included, and to string arguments of earlier tool calls. Storage
stays raw: messages, the DSH surface and her stored writing are untouched and the Web page keeps showing them as they
are; only what the model reads changes. Compaction and background summaries are written from rewritten requests, so
new checkpoints carry no root by construction. The rewrite is deterministic, so cache prefixes stay stable.

DSH's working-folder line is not fought on the surface (making it optional would be a change to the owner's fork): it
stays there and is rewritten in the request like everything else. **No table, no request:** a listener without a table
refuses her lanes' requests with a coded program fault and one audit event, never passes them raw; the action lane is
unaffected. The refused turn reaches her as a program fault through the existing faults channel (the once-only
`fault_from_program` line in that conversation, and the developer's note), and the owner sees it on the settings card
(install check). The install check shows the table (number of roots) and a per-session count of rewritten requests, so
a DSH upgrade that moved the seam shows instead of leaking quietly; the count reaches her in words with the weekly
readings beside D5's. What she sees without a table, whichever the cause (the builder refused, or the plugin never
got one): her turns there end before reaching the model, and her next turn there opens with the program-fault line
`ASUNA_ROOT_TABLE_MISSING`, "not your fault, retrying does the same"; inbound lines still arrive and the action
brain still works. Without a table the other rules hold too: D3 refuses any placeholder toward the action brain
(`PATH_TABLE_MISSING`) and passes text without one; D4 and D5 have nothing to contract.

**D3. Expansion toward the action brain.** One helper at the fields that go to it: the `delegate` brief and its
title (her review after the install: the title reached the action brain unexpanded, a name it cannot open), a
message to a task, her answer to a task's question, and an `ask` to 行动脑. It runs the vault's `credentials.scrub`
first (her answer to a task is not scrubbed today; this closes that), then:
- a placeholder this place can hand over expands to the real path (whole tokens only; the tail's separators become the
  host's own);
- a placeholder this place cannot hand over stays as written: a mention ("this came from `${ASUNA_DRIVE_D}\logs\x.log`")
  keeps its provenance, it reveals nothing, and the mechanism already keeps the action brain away from it;
- refused, each with the reason and, where one exists, the whole string rewritten the way it would pass: a raw
  absolute path of this machine (rewritten with its placeholder); an `${ASUNA_…}` name not in the table standing as a
  path's root, i.e. followed by a separator (the refusal lists the names there are; elsewhere it is text, such as a
  quoted `${ASUNA_REPO:-…}`); a path that climbs with `..` (owner: relative climbing paths are rejected). A `..`
  segment in a path anchored at a placeholder or a real root is refused everywhere (`${ASUNA_WORKSPACE}\..\x`,
  `C:\a\..\b`); a bare relative path that climbs (`..\x`, `../x`, `cd ..`) is refused in a public session only: at
  home it escapes nothing (home reaches the whole computer) and her scripts use `cd ..`.

This is what "a path outside her workspace is rejected" means. Old ledgers reach her already contracted (D2), so
copying from them does not trip it.

**D4. Her new writing is stored contracted.** One line in `RoleTools.call`, after the argument names are mapped and
before the idempotency hash, applies the table to every string argument. With D2 she only sees placeholders, so this
is a backstop. Existing memory is not changed.

**D5. Speech.** A raw root that still reaches `speak` or `reply` is replaced by its placeholder in `tool_speak`, beside
the sticker check (a part is queued when it is spoken, so the end-of-turn check is too late). The stored outbound
message is what was sent. She is told the rule once in her notes. Each replacement is counted (a count, no text), and
the count reaches her with the weekly readings in words ("这周有几句本来带着真根"), in the same reading as D2's count of
rewritten requests; a count above zero is a fault to look at (the seam failed, or a model invented a root), not a
statistic.

**D6. One form everywhere.** `machine_words`' path rule uses the same table in place of its checkout-relative form and
its `〔本机路径〕` word; its traceback rule outside home stays. ADR-050's section, `tests/test_machine_words.py` and
`tests/test_read_report.py` change with it.

**D7. A placeholder is not a word she said.** `key_words` drops `${ASUNA_…}` tokens before splitting, so `workspace`
or `home` never becomes an ADR-097 key, cue or learned word.

**D8. Machine facts that are not paths** (the OS, installed toolchains, drive letters) are not filtered: they have no
tail to keep and the words are ordinary, so a word filter would break her technical talk. The machine is not for
disclosure; that is her own rule, kept in her notes (a drive letter is a machine fact of low harm, owner). A path in a
picture (a screenshot she reads with `read_image`) is outside this layer and stays with the same rule.

## 5. Checks (pass or fail)

One shared case file (`tests/fixtures/path_placeholders.json`: input, host, place, contracted, expanded or refused)
runs in both `node --test` and pytest, so the JS and Python matchers cannot drift. It holds every spelling of D1, the
idempotency cases (contracting twice equals contracting once; expanding then contracting gives the placeholder text
back), Windows and POSIX tables, and the Docker shapes (`/app`, `/srv/asuna`, running as root).

- The requests DSH sends for her sessions carry zero roots and zero user names (asserted on the request in
  `native-loop.test.js` against the pinned DSH); the action brain's requests are unchanged.
- No table: her lanes' requests are refused with the coded fault; the action lane runs.
- A brief written with `${ASUNA_WORKSPACE}\…` reaches the task's brief and the action session with the real path; a
  raw root, an unknown `${ASUNA_…}` name and a `..` path are refused with the rewritten string or the reason.
- A public session's brief with `${ASUNA_HOME}\…` or `${ASUNA_DRIVE_D}\…` goes out unexpanded; the same brief at home
  expands. `${HOME}` and `${1}` in a script pass untouched everywhere.
- A new revision, note, plan or question written with a raw root is stored contracted.
- An outbound message cannot carry a raw root; each replacement is counted.
- Both counts reach her weekly reading as two sentences, each with its own criterion: speech replaced (above zero is
  a fault) and requests rewritten per conversation (normally above zero).
- A quoted deployment variable (`${ASUNA_REPO:-…}`) passes toward the action brain as text; no deployment variable
  in `deploy/` is named like a placeholder.
- `key_words` yields no word from a placeholder.
- `machine_words` emits the table's form (D6), in `tests/test_machine_words.py`.
- The JSON-escaped spelling (doubled backslashes) contracts and expands like the plain one: five sixths of the paths
  in her ledgers are written that way.
- Machine facts pass untouched (D8): "Windows" and "Python 3.12" in a report reach her as written.
- A moved data root reads `${ASUNA_DATA}\…`; a filesystem root as the checkout refuses to build the table.
- End to end, from home: one real `delegate` whose brief carries a ledger path written as `${ASUNA_WORKSPACE}\…`; the
  action brain's brief holds the real path, word for word.

**The switch is one cut** (hers): the install time is recorded here, as an audit event, and as one line in
`host.log` she can find; readings across it (cache, checkpoints, time since compaction) are compared on each side,
never across. Before switching on, the live sessions are counted, not assumed.

Cost: turning D2 on changes the first message of every live session once, about 0.4M uncached tokens in all (against
639M input in the last 48 hours); steady-state cache hits are unchanged. An estimate, counted as one uncached request
per live session: three live conversations (QQ 104k, home chat 129k, agent line 141k average input per step over 48
hours) plus the relevance gate's; the real number follows from the count above.

## 6. References to update

`RUNTIME_API.md` (beside Credentials: the table, the two directions, the speech rule), `NATIVE_PLUGIN.md` (the
role-prompt paragraph: the snapshot is required in DSH and rewritten at the model boundary),
`docs/articles/maximize-cache-hit-by-design.md` (wrong today: it says the working-folder snapshot is suppressed),
`AGENTS.md` (no local root reaches the character brain; the action brain keeps real paths), the agent-line README (the
names coding agents will read in her `ask`s), the `docs/map` module lines, and ADR-050 (its path rule now follows
this one).

## 7. Build

The owner asked Claude to build and deploy it this afternoon as technical lead: an Opus 5.5 builder in its own
worktree, Claude's review, then the install. Her direction is signed; her signature on the final text follows the
version hash she reads. The Fable 5 failure-mode review (§8) is folded in; the doubts it leaves open are checked after
the build.

## 8. Evidence

Kept in `.runtime/private/workspace-sanitize-1026/`: the incident trace and censuses (`evidence-scripts/`), the
deep-dive brief, and the Fable 5 reports with their counting scripts (`deep-dive/report.md`,
`deep-dive/failure-modes.md`, `deep-dive/scripts/`). All print counts, field names and masked keys only.
The build's own counting scripts are beside them in `build/` (`msys_count.py`, `image_blocks.py`; counts only).

## 9. What the build found (2026-10-26)

Built on branch `claude/adr098-build`. Where the code did not fit the text above, this is what was built and why;
the rest is as written.

**Not covered by D2: the image path text.** DSH's DeepSeek adapter writes a text beside every image of a request,
naming the attachment's read-only normalized copy by its absolute path under DSH's home
(`dsh-llm-deepseek` `requestImageHandleText` and `offloadedImageText`, with `dsh-fs-local`'s
`processPathFromHostPath`), and `dsh-llm` projects a file block to a text with its saved path. Both happen inside the
adapter call, after the `llm/stream` waterfall, so the seam cannot rewrite them. Her lanes carry images: 609 image
blocks in 27 of her 79 persona-preset session logs, none in the gate's or the summaries' (`build/image_blocks.py`);
no file blocks. The deep dive's "ids, not paths" holds for the session log, not for the request.

**Closed on our side (2026-10-26 evening, the owner's choice of the three: report upstream, patch the fork, or a
hook of ours).** The adapter asks DSH's fs service for that path (`processPathFromHostPath`) while it builds the
request, inside the stream the waterfall returns. The plugin runs each request of her lanes in one
`AsyncLocalStorage` scope, made and read inside it, and wraps that one mapping once: inside her scope the mapped
path comes back contracted (`${ASUNA_DATA}\adr008\home\attachments\...`), the note otherwise as DSH writes it;
outside it (the action brain, DSH's UI and session controller) the mapping answers as before. No DSH file
changes. An experiment with real cordis, `LlmRuntime`, `dsh-fs-local` and DSH's own note functions came first;
the test now runs through the installed listener and agents (`native-loop.test.js`), with a negative control (the
wrapper off, it fails), and `roots.test.js` fails if the installed DeepSeek adapter stops resolving image paths
through that mapping, so a DSH upgrade cannot bring the root back quietly. DSH's price estimate reads the note
outside the scope for its length only; it is never sent. A file block's saved-path text would pass the same
mapping; none reach her lanes today.

**D3 and D4 meet in `RoleTools.call`.** D4 contracts every string argument before the tool runs, which would rewrite
a raw root in a brief before D3 could refuse it. So D4 leaves out the field bound for the action brain (the brief, the
message, the answer, an `ask`'s question when it goes to 行动脑), and D3 sees it as she wrote it. It also leaves out
her speech, so that D5 can count what it replaces (in `tool_speak`, and in her end-of-turn text, which is published
without `speak` where a channel has no parts), and the literal values of `credential` and `private_words`. An `ask`
keeps its own question contracted; only the action brain's brief is expanded.

**The table, in detail.**
- `${ASUNA_WORKSPACE}` is the Host's repository checkout (the floor's `checkout()`); without one, the installed core
  package's root.
- `${ASUNA_PROGRAMS}` keeps its own folder name (`${ASUNA_PROGRAMS}\Program Files\nodejs`, `${ASUNA_PROGRAMS}/usr/lib`):
  one placeholder for several folders could not expand back otherwise.
- `${ASUNA_FS}` covers only this machine's own top-level folders, so `/api/v1/users` in her technical talk is not a
  path of the machine. On Windows there is no `${ASUNA_FS}`; POSIX-shaped text passes, except WSL's `/mnt/x` and the
  MSYS spelling `/x/...` of a named root (6 and 1 records in 580,366, `build/msys_count.py`).
- `${ASUNA_USER}` skips generic accounts (`root`, `node`, the container's `asuna`, and a few more), since replacing
  them would rewrite ordinary words; it is that exact string, case-sensitive everywhere. The account name alone is not
  a raw root: a brief with it is not refused.
- A filesystem or drive root refuses the table when it is the checkout, the data folder or DSH's home; a home or temp
  folder at one is left out of the table.
- All Windows matching is spelled case-insensitively in the pattern itself, so the plugin compiles the worker's pattern
  as it is, with no flag; both engines run the shared case file.

**Fail closed, visibly.** The plugin's refusal is a thrown `ASUNA_ROOT_TABLE_MISSING` error at the waterfall: DSH ends
the turn with `agent/error`, the worker records `FAILED_RUNTIME`, and `faults.turn_failed` tells the developer and marks
the conversation for her next turn (`fault_from_program`), as any program fault. One `roots.refused` audit event per
plugin start without a table; the settings card's alert says it.

**The weekly reading** groups the rewritten requests by conversation (place title, or the gate, the summaries and the
appraiser by name), not by session id: two sentences, her speech replaced and her requests rewritten, each with its
own criterion.

**Another account's home (decided after review, built).** ADR-050 hid every path outside the project outside home,
tail and all, since its last part can be a person's folder; under `${ASUNA_DRIVE_X}` and `${ASUNA_FS}` the tail is
kept. This machine has another real account folder, so a folder beside the user's home under the home's parent
(`C:\Users\<other>`, `/home/<other>`, `/Users/<other>`) is `${ASUNA_LOCAL_PATH}` with nothing kept, never expanded.
The home itself and the shared profiles (`Public`, `Default`, `Default User`, `All Users`, `Shared`) keep their tails
under the drive or tree fallback; a home at `/root` has no siblings. A folder name with a space ends the match at the
space. An unmounted volume's label under `${ASUNA_FS}` still passes.

**Open.**
- §5's end-to-end check (one real `delegate` from home) needs the installed Host; it is not run here.
- "She is told the rule once in her notes" (D5, D8) is a note to her, not code.

## 10. Installed (2026-10-26)

Her own restart at 16:32:22 NZDT (`restart/last.json` `back_at`) installed `281933b0`; that time is the cut for every
reading across the switch. §5 promised a dedicated `host.log` line and audit event for it: neither was built; the
restart record above is the cut. Checked on the live Host, by content:

- The installed `local_roots.py`, `roots.js` and `role_tools.py` are byte-identical to the checkout; no
  `roots.refused` event, so the table was built and handed over.
- In the first half hour after 16:32, 26 requests of her lanes (character 16, gate 6, background summaries 4), all 26
  rewritten (after the 18:42 restart, 11 of 11 in its first six minutes);
  `roots.speech_replaced` 0.
- From inside, she read her working-folder line as `${ASUNA_DATA}\work\agent`, and the `paths` line of her
  context by name and meaning.
- End to end from home: a `delegate` she wrote with `${ASUNA_WORKSPACE}\docs\map\README.md` reached the task's
  stored brief as the real path, no placeholder left.
- The one-time cold read the switch costs showed as expected: the first QQ compaction after it read 10.1% from cache
  (99% before), the QQ turn steps 87.7% in the first half hour.


**After the install, a public line's doors** (the Fable 5 review, `deep-dive/failure-modes.md` §8): every tool a task
delegated from a public place receives resolves a path first and checks it lies in `/task` (`..`, absolute paths and
links out are refused); DSH's `web_fetch` takes http and https only and refuses loopback, private and link-local
addresses; the skill tool takes a name, not a path. 2 of 1,131 briefs carry a climbing `..`, both public, none in
code. D3 expands by the stricter of authority and place: on an errand the turn's class is the group's, and a home turn
an outside note opened has no `delegate`. Open, outside this record: on an errand a group's lines can steer a task
with home authority (ADR-066), a question of task grants, not of paths.

**`${ASUNA_PROJECTS}` (added after the install, from the Fable 5 review §9).** With `${ASUNA_WORKSPACE}` as the
checkout, a sibling project and the folder that holds the checkout fell to the drive fallback with that folder's own
name in the tail (`${ASUNA_DRIVE_C}\<that folder>\<project>`): the very word the incident disclosed. 90 public briefs
and 159 reports name a sibling project. The parent is now its own root, deeper roots still winning inside the
checkout, handed over at home only (a public line hands over `${ASUNA_WORKSPACE}` and `${ASUNA_DATA}`, the
owner's ruling; the first build also handed `PROJECTS` over in public, which she caught as a ruling nobody had made,
and it was narrowed back); `${ASUNA_WORKSPACE}` keeps its meaning, so what she wrote since
the install (1 journal entry carries it) reads the same. A checkout at `/` or a drive root, or one whose parent is the
home, has no `PROJECTS`.

**Her signature on the text as built (2026-10-26 evening), and its two conditions.** She signed the text at
`d2496203` (she signs by commit from now on; a content hash cannot be found again). Her conditions: (1) the recovery
session D2 leaves unrewritten: it is the owner's repair console, a DSH session opened in the Web page while the worker
is down; her brains never read it, and what it publishes reaches her only as publication state, through the rewrite
like any other text; (2) `PROJECTS` in public was not the owner's ruling: narrowed back to home, above. She also
caught a stale module comment on `FS` (fixed) and the two request counts without their windows (written).

