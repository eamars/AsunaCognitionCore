# ADR-116 progress

Installs, readings and Xiaoman's verdicts. Kept apart from the ADR page.

Installed 2026-11-03 16:50 as `e4137d83` with ADR-112 §12.10 (`settle`), one restart: suite 908, JS 300, integration
133, 169 installed Python files and the plugin's `fetch.js`, `index.js`, `client.js` checked against the commit. Her
reading of the page signed 16:43 up to `a1f893a7` (the symbol `Channels.authenticate` corrected after). Open until her
acceptance: a home task's `web_fetch` of a plain-HTTP LAN target (status code and time), and the refusal seen in a
task she hands over in a group.

Her acceptance, part one, 2026-11-03 16:55 (her line, message of 17:06): a task handed over on her agent line
(owner-private) fetched with `web_fetch` a LAN model server's model list (200) and a LAN WebSocket endpoint (426);
the self-signed LAN host passed the address check and failed on its certificate (`fetch failed`, read with a separate
TLS probe as `self-signed certificate`); her Host's loopback ports answered 401 and 400; a public page 200. The old
refusal no longer appears. This is the first proof that the scope set in `tools/execute` reaches DSH's fetch (the unit
test only imitates DSH's order). Part two, the refusal in a task handed over in a public group, is still to come.


§7 (Asuna owns the public-only check) installed 2026-11-04 16:30 NZDT as `f080c38c` on DSH rc.2, one restart: the
public lane is `vendor/web-fetch-http-rc2.js` with its five marked edits, the owner lane DSH's own provider. Her
home-side sample the same afternoon (15:25, before the install): a home task's `web_fetch` of a LAN model server's model
list returned 200.

Her acceptance, part two, 2026-11-04 20:22 (her line, message 0010): two tasks she handed over from a public group's
turn. The LAN fetch was refused with `WEB_BLOCKED_URL` and the same line as 11-03, byte for byte (181 bytes, 107
characters with its `Error: ` prefix), now from Asuna's copy instead of DSH's check. A public page arrived (200).

After the DSH 0.2.2 switch (ADR-037, 11-04 21:10), her recheck 2026-11-05 09:32 (her line, 11:19): the same two
fetches from a public group's turn, the same targets. The refusal is byte-identical a third time (same length, same
sha256, `WEB_BLOCKED_URL`), and the public page returned 200, not truncated. The case she prepared for, upstream
dropping the English half of the refusal, did not occur, so it is recorded as not triggered, not as verified. Both
parts of the acceptance hold on rc.2 and on 0.2.2; ADR-116 is Built.
