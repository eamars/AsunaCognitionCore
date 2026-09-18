# M0 integration probe

Exploratory evidence only; not formal E/L/A/F acceptance.

| Probe | Status |
|---|---|
| character.models | PASS |
| character.props | PASS |
| character.completion | PASS |
| executor.models | PASS |
| executor.props | FAIL |
| executor.completion | PASS |
| embedding.models | PASS |
| embedding.batch | PASS |
| mongo.ping | PASS |
| mongo.hello | PASS |
| mongo.write_cas | PASS |
| mongo.vector_index_create | PASS |
| mongo.vector_index_status | PASS |
| mongo.scope_vector_query | FAIL |

## Unverified boundaries
- DSH provider integration pending
- tool subprocess sandbox unverified
- server-rendered token IDs unavailable
- 196k and 234k capacity NOT_RUN
- human cognition ratings NOT_RUN

All failures and serialized provider requests remain in this attempt directory. No real QQ/device sends; no legacy application was imported.