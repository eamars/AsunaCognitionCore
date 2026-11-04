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
  hop (`deepseek-harness:packages/web/web-fetch-http/src/network.ts` `isPublicIpAddress`, `resolve`, `createPinnedLookup`;
  `provider.ts` `fetch`, `requestOnce`; at the pinned
  `d9d52ada`). The refusal: `URL hostname "…" resolves to a non-public IP address` (`WEB_BLOCKED_URL`). No setting,
  variable or permission mode turns it off.
- **Upstream removed it** in `2f01ad549c` (2026-10-20, "let web_fetch reach non-public destinations": the check "did
  not confine a model that has shell network access"), on master, in no release yet.
- **Her home tasks already reach the LAN**, by reading, not measured: `sandbox_run` confines writes only; reads and
  network are not restricted (RUNTIME_API's `sandbox_run` entry; DSH `packages/sandbox/sandbox/README.md`, "the seam
  expresses no network…restrictions", and `sandbox-windows-acl/README.md`, a confined child can "open sockets"),
  and it is given only where the session class is owner-private (`Coordinator._grants`). Measured by her 11-03
  16:17-16:22 from a home task's `sandbox_run` (her task `task-379f008645da`): the default gateway answered on 80 (302) and 443
  (200), other LAN hosts with 426, 200, refused and timeout, each shaped differently; the two hosts other than the
  gateway carry VMware addresses and are probably virtual machines on this computer, so the gateway is the one
  physical device off this machine. Before the change, `web_fetch` of the gateway answered
  `URL hostname "…" resolves to a non-public IP address`. Not measured: IPv6, UDP, the firewall rules themselves. Every task gets
  `web_fetch` (`tasks.ACTION_DSH_CAPABILITIES`), a task begun in a public group included: for those, the fetch gate is
  the only barrier to the LAN.
- **Her `web_fetch` is our provider.** `packages/cognition-core/src/fetch.js` wraps DSH's `HttpFetchProvider` (the npm
  `@deepseek-ai/dsh-web-fetch-http` 0.2.1-rc.2, not the fork), whose constructor already takes a resolver
  (`HttpFetchResolver`). The provider is given only `{url}`: it cannot tell which task calls.
- **The services she could reach are token-authorized.** Her DSH Web (`127.0.0.1:8780`) answers 401 to a GET with no
  token (measured 11-03 ~15:45; which code answers it is not checked). Her Host's channel server (`127.0.0.1:8766`)
  takes a request only with its bearer token (`channels.py` `Channels.authenticate`,
  `secrets.compare_digest(authorization, 'Bearer ' + token)`, by reading); the 400 `UNKNOWN_CHANNEL_ENDPOINT` measured
  the same minute comes from the path check before authentication (`channels.py` `ChannelServer`'s request handler,
  `handle_request`) and is no evidence of the token.
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
  is the one source: the session binding sent to the plugin copies the task's recorded `network`, never computing it
  again (an action session serves one task), and a continuation keeps it but never widens it: `any` only while the
  continuing turn would give `any` too, as its `sandbox_run` follows that turn (review 11-03: a group removed from
  `home_groups` kept `any` without `sandbox_run`). By place:

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
- **D3. The scope.** The plugin's `tools/execute` hook runs `next()` inside the scope of that session's binding:
  DSH runs a tool body as the last step of that waterfall (dsh-tools `ToolRuntime`: `tools/execute` ending in
  `dispatchToolBody`), so the fetch reads the scope set there. `tools/pre-execute` only decides whether a call may run;
  a scope set there ends before the body (review 11-03, which found the first build there). The action lane takes its
  task's network; every other lane runs `public`, never an inherited scope. A call outside any scope (DSH's own UI, a
  session the plugin did not bind) gets the public provider.
- **D4. Words.** Her action brain's `web_fetch` in a public-only task is refused as now; the refusal is DSH's English
  line. It gets one sentence of ours in the action brain's language: the address is on the local network and this task
  was not handed over at home. No other text changes.

**Upgrading DSH.** Upstream `2f01ad549c` removes the check and, with it, `HttpFetchResolver` and the provider's
resolver parameter that D2 uses. While the pin has the check (it does at `d9d52ada`, and no release tag contains the
commit yet), D2 stands; the DSH upgrade that brings the commit in makes every fetch reach every address, and D2 is then
rewritten as a check of ours in `fetch.js` for public tasks, carrying all of what DSH's check does: every resolved
  address judged (not the first only), IPv4-mapped IPv6 by its IPv4, the NAT64 translation, and pinning to the
  addresses checked. The upgrade guide that commit adds sits under a `v0.2.1-rc.2`
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

Before the build, measured (her ask, done 11-03 16:22, §2): a home task of hers reaches a LAN device with
`sandbox_run`. For the acceptance after landing she picks a plain-HTTP target: the self-signed HTTPS ones would fail
on the certificate, and the gateway's 302 to HTTPS is a cross-origin redirect `web_fetch` does not follow. Then one core landing (the plugin and
the worker), the suite, the node tests, the push gate, her slot asked first, the restart, the loaded commit checked.
Then read on the live system, by her: a home task's `web_fetch` of a LAN device (status code and time), and D4's
refusal seen in a task she hands over in a group (acceptance, not a staged scene). Bundled with ADR-112 §12.10 (`settle`), which waits for the next
core landing.

## 7. Asuna owns the public-only check (designed 2026-11-04, before the DSH 0.2.2 switch)

**Why now.** The owner's plan of 2026-11-04 (ADR-037): this change lands on its own, on the current DSH, and then
DSH moves to 0.2.2 in one switch. DSH 0.2.2 contains upstream `2f01ad549c`: its HTTP fetch reaches every address,
and the resolver parameter D2 uses is gone. Asuna's core is JavaScript, so the resolver would be ignored without an
error, and every public-only task would reach the LAN. The ICD's SVC-1 already says which addresses a fetch may reach
is the plugin's own policy. A public-only task has no `sandbox_run` (D1), so for it this check is the only barrier
to the LAN, and upstream's reason for dropping it (a model with shell network access) does not apply.

**Broken invariant after 0.2.2:** a public-only task's fetch reaches what such a task may reach, public addresses only;
DSH no longer enforces that, so Asuna must.

**D5. The public lane is Asuna's own transfer, a copy of DSH's check.** `fetch.js`'s public provider stops being
DSH's `HttpFetchProvider` and becomes a vendored copy of DSH's own provider as it is today: the built `lib/index.js`
of `@deepseek-ai/dsh-web-fetch-http` 0.2.1-rc.2 (MIT, 681 lines), kept as one file with DSH's notice
(`packages/cognition-core/src/vendor/web-fetch-http-rc2.js`). Its behaviour therefore stays exactly what she has
today: every resolved address judged (not the first only), IPv4-mapped IPv6 by its IPv4, NAT64 through RFC 7050
discovery, the connection pinned to the checked addresses through a per-request agent (no second DNS answer), each
redirect hop checked again and followed only when it is same-origin, and the same limits and refusal line
(`URL hostname "…" resolves to a non-public IP address`, `WEB_BLOCKED_URL`), so D4's sentence and the 11-03
refusal she verified keep their exact text. Four edits to the copy, each marked in it:
- **No proxy route.** It imports `proxyRouteFor` from DSH's `dsh-http-proxy`; the copy always connects directly,
  pinned. Her Host has no proxy configured (read 2026-11-04: no `HTTP(S)_PROXY` for the user or the machine). If one is
  ever needed, a public-only fetch fails to connect, which fails closed.
- **Its two DSH imports go.** `deadline`/`timeoutOf` (`dsh-timeout`) become a few local lines, and `WebError` comes
  from `@deepseek-ai/dsh-web`, which Asuna already imports (part of SVC-1's result shape). `ipaddr.js` 2.5.0 and
  `undici` 8.11.2, the versions rc.2 resolves today, become the core package's own dependencies.
- **Only the provider stays.** The copy's plugin wrapper (`Config`, `apply`, `name`, `inject`, which also import
  `schemastery`) goes; `fetch.js` constructs `HttpFetchProvider` itself, as it does now.
- **The check is exported** (`resolvePublicAddresses`), so its tests can hand it a DNS answer.

**D6. The owner lane is DSH's.** A task of the owner's own conversations (`any`) keeps DSH's provider: on rc.2 with
`resolveAny`, as now; on 0.2.2 the plain provider, which reaches every address by itself. That is the only line the
0.2.2 pickup changes here.

**Rejected:** a check before DSH's own fetch, because DSH resolves the name again and a second DNS answer can point at
the LAN; and a process-wide dispatcher routed by async scope, because it is global state the whole Host shares
(her LAN model server is reached through it) and depends on how DSH sends.

**Failure modes.** The copy drifts from upstream fixes: it is DSH's last version of a check upstream has dropped, so
there is nothing upstream left to follow, and its tests stay with it. A lost scope still gets the public lane (§4).
A malformed or empty DNS answer refuses as today.

**Tests that earn their place.** The two LAN cases in `fetch.test.js` (public refused with D4's sentence, owner lane
reaches a loopback page) now run through the copy and must stay green unchanged. Added: an answer mixing a public and
a private address is refused (every address is judged), and a redirect hop to a private literal is refused. Both use
the copy's own resolver seam, so nothing leaves this machine.

**Landing.** One core landing on the current DSH, with her slot asked first. Then on the live system: one fetch of a
LAN address from a task she hands over in a public group is refused with the same line as 11-03, and one public page
fetched from a group task arrives. The 0.2.2 switch (ADR-037) then changes D6's one line and nothing here.
