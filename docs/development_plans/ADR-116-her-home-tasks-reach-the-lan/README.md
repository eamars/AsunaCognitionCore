# ADR-116: Her home tasks reach the LAN

Status: **Open**. Designed 2026-11-03 from the owner's decisions that evening; not built.

## 1. The ask

The owner, 2026-11-03: open her LAN access; keep her home permission the same as DSH's default full workspace access,
without restricting LAN devices on purpose. He takes the risk for her home permission. Then: tasks of his own
conversations only; and, on loopback, since the Asuna services are token-authorized, opening loopback too is safe.

She had planned this already (her task `task-82b9c5c4`, held for the owner's word: whether DSH has an official switch
for `web_fetch`'s private-network refusal).

## 2. What is in the way (read 2026-11-03)

- **One gate: `web_fetch`.** DSH's HTTP fetch provider refuses every non-public address: it resolves the host first and
  passes only `unicast` addresses (private, loopback, link-local, CGNAT, `0.0.0.0`, multicast refused; IPv4-mapped IPv6
  judged by its IPv4), pins the connection to the checked addresses, follows same-origin redirects only and checks each
  hop (`deepseek-harness:packages/web/web-fetch-http/src/network.ts:54-212`, `provider.ts:66-144`, at the pinned
  `d9d52ada`). The refusal: `URL hostname "…" resolves to a non-public IP address` (`WEB_BLOCKED_URL`). No setting,
  variable or permission mode turns it off.
- **Upstream removed it** in `2f01ad549c` (2026-10-20, "let web_fetch reach non-public destinations": the check "did
  not confine a model that has shell network access"), on master, in no release yet.
- **Her home tasks already reach the LAN**, by reading, not measured: `sandbox_run` confines writes only; reads and
  network are not restricted (RUNTIME_API's `sandbox_run` entry; DSH `packages/sandbox/sandbox/README.md:166`, "the seam
  expresses no network…restrictions", and `sandbox-windows-acl/README.md:125`, a confined child can "open sockets"),
  and it is given only where the session class is owner-private (`Coordinator._grants`). To be measured before the
  build (§6): pending. Every task gets
  `web_fetch` (`tasks.ACTION_DSH_CAPABILITIES`), a task begun in a public group included: for those, the fetch gate is
  the only barrier to the LAN.
- **Her `web_fetch` is our provider.** `packages/cognition-core/src/fetch.js` wraps DSH's `HttpFetchProvider` (the npm
  `@deepseek-ai/dsh-web-fetch-http` 0.2.1-rc.2, not the fork), whose constructor already takes a resolver
  (`HttpFetchResolver`). The provider is given only `{url}`: it cannot tell which task calls.
- **The services she could reach are token-authorized.** Her DSH Web (`127.0.0.1:8780`) answers 401 to a GET with no
  token (measured 11-03 ~15:45; which code answers it is not checked). Her Host's channel server (`127.0.0.1:8766`)
  takes a request only with its bearer token (`channels.py:275` `ChannelController.authenticate`,
  `secrets.compare_digest(authorization, 'Bearer ' + token)`, by reading); the 400 `UNKNOWN_CHANNEL_ENDPOINT` measured
  the same minute comes from the path check before authentication (`channels.py:931`) and is no evidence of the token.
  The QQ adapter's NapCat endpoint (on the LAN) has a token set (read from its run config, value not printed). Both of her Host's ports listen on `127.0.0.1` only, not `0.0.0.0`
  (`netstat -ano`, same time): opening loopback lets this machine's tasks reach them, not the LAN. `web_fetch` sends a bare URL and no
  header. A service that takes its token in the URL could be reached by a task that read the token from disk, which a
  home task can already do with `sandbox_run`: opening `web_fetch` adds no reach a home task does not have.

## 3. Design

**Broken invariant:** a home task reaches the LAN with a command but not with a fetch; the fetch gate stops nothing it
was meant to stop, and only gets in the way.

**Rule: `web_fetch` reaches what `sandbox_run` reaches.**

- **D1. The grant.** A task's network is decided once, when it is handed over, by the same line as `sandbox_run`: the
  session class of the turn that delegates it (`visibility.session_class`, read by `Coordinator._grants` from the
  turn's manifest), never by where the action brain runs (work moved to the Web chat keeps what its delegating turn
  gave). `OWNER_PRIVATE` gives `network: 'any'`; any other class, present or added later, is public by construction
  (`_grants` tests `!= OWNER_PRIVATE`, as for `sandbox_run`). It is recorded on the task with its grant, and that record
  is the one source: a continuation copies it, and the session binding sent to the plugin copies the task's recorded
  `network`, never computing it again (an action session serves one task). By place:

  | Where the delegating turn is | Session class | Network |
  |---|---|---|
  | the Web chat | owner-private | any |
  | the owner's private chat on a channel (a DM whose canonical person is the owner) | owner-private | any |
  | a home line (`channel_kinds.home`: the agent lines, the peer line) | owner-private | any |
  | a group the owner configured as home (`home_groups`); others speak there too | owner-private | any |
  | a home turn woken by a note from outside that delegates with `for` (ADR-111): the work runs in the Web chat | owner-private (the delegating turn is at home) | any |
  | any other group or private chat | public | public |

  This is exactly where `sandbox_run` is given today: every row that gives `any` reaches the LAN by commands already,
  the two that may carry other people's words (a home group, work asked from outside) included. The default is public: only `OWNER_PRIVATE` gives `any`, and
  a task with no recorded `network` (made before this change, or by a path that sets none) is public. A place becomes
  owner-private only by the owner's configuration (his chat, his canonical person, a home channel kind, `home_groups`),
  and that one act gives both tools: there is no second list of places for the LAN, which would drift from the first.
  The owner confirmed the line 2026-11-03: private conversations, as opposed to public.
- **D2. The provider.** `fetch.js` builds two providers: DSH's as now (public only), and one with a resolver that
  resolves the host (`dns.lookup`, all addresses, verbatim order; an IP literal as it is) and passes every address,
  loopback included. Pinning, the same-origin redirect rule and each hop's resolution stay DSH's. Which one serves a
  call is read from an async-local scope (`AsyncLocalStorage`, as `roots.js` scopes her requests).
- **D3. The scope.** The plugin's `tools/pre-execute` hook for the action lane, which already validates the stage per
  session, runs `next()` inside the scope `{network}` of that session's binding. A call outside any scope (DSH's own
  UI, a session the plugin did not bind) gets the public provider.
- **D4. Words.** Her action brain's `web_fetch` in a public-only task is refused as now; the refusal is DSH's English
  line. It gets one sentence of ours in the action brain's language: the address is on the local network and this task
  was not handed over at home. No other text changes.

**Upgrading DSH.** Upstream `2f01ad549c` removes the check and, with it, `HttpFetchResolver` and the provider's
resolver parameter that D2 uses. While the pin has the check (it does at `d9d52ada`, and no release tag contains the
commit yet), D2 stands; the DSH upgrade that brings the commit in makes every fetch reach every address, and D2 is then
rewritten as a check of ours in `fetch.js` for public tasks. The upgrade guide that commit adds sits under a `v0.2.1-rc.2`
folder although no release contains it; not looked into.

Not in scope: work asked from outside, which runs in the Web chat (ADR-111), gets `network: 'any'` as it gets
`sandbox_run` today. Keeping outside work off the LAN would need both tools, and belongs to the owner's future work
channel architecture.

## 4. Failure modes

- A scope lost across DSH's async chain (the provider runs outside it): the call gets the public provider. It fails
  closed, never open; a test drives a fetch through the real hook to prove the scope arrives.
- A binding from an older worker without `network`: public.
- DNS that answers nothing: DSH's own `WEB_BLOCKED_URL`-family error, as now.
- A proxy in the environment: hostnames go to the proxy, as now; literal addresses connect directly.

## 5. Tests that earn their place

| Test | Guards | Fails without |
|---|---|---|
| a home task's fetch of a private and a loopback literal resolves and connects (a local test server); a public-only task's is refused | the rule | D2, D3 |
| a fetch outside any scope is public-only | failing closed | D3's default |
| `_grants`: owner-private delegation gives `any`, a group's `public`; a continuation keeps the task's | D1 | D1 |

## 6. Landing

Before the build, measured (her ask): a home task of hers reaches a LAN device with `sandbox_run` today, so §2's
reading is checked against the live system before anything is installed on it. Then one core landing (the plugin and
the worker), the suite, the node tests, the push gate, her slot asked first, the restart, the loaded commit checked.
Then read on the live system, by her: a home task's `web_fetch` of a LAN device (status code and time), and D4's
refusal seen in a task she hands over in a group (acceptance, not a staged scene). Bundled with ADR-112 §12.10 (`settle`), which waits for the next
core landing.
