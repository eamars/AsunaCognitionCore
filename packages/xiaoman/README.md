# 小满 — Asuna persona plugin

Install with `@asuna/cognition-core` 0.2.x (persona contract v2) in DSH **0.2.0-rc.2**. The contribution registers the **小满** native role preset, persona ID `local-xiaoman`, and existing persisted character ID `xiaoman`.

`seeds/persona.md` is the original distributable persona text, unchanged (formerly `persona/core.md`). It is declared as the `persona` seed and seeds an absent head only. `persona-model.json` carries only neutral defaults; persona-private values belong in the local policy store. Existing Mongo persona, Character Core, Current Self, voice and relationships remain authoritative across package updates.

`skills/` contains the selected existing offline-check skill. The QQ adapter and its skill moved to the channel package `packages/napcat-qq`. `resources-provenance.json` records the original selection and source hashes; later autonomous publications retain their own lineage. Private account/route examples were anonymized on export. No private config, sample conversation log, inbox/outbox, media cache or live memory is included.

Owner actions develop this project by default through `development_*`. The persistent candidate is writable; the loaded artifact is immutable. Skills change in the candidate through the same tools, while native skill discovery reads the selected published resources. Publish a candidate to make a new resource version visible to subsequent action scopes. Use `project="core"` for authorized cognition changes. These grants are not inherited by ordinary QQ scenes.

Both brain routes may point to the same model; they remain separate native sessions. The enabled adapter snapshot and private configuration are managed by Core's integration service; package installation alone does not create new platform authorization or overwrite live self state.
