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

