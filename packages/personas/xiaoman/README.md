# 小满 — Asuna persona plugin

A persona package for `@asuna/cognition-core` 0.2.x (persona contract v2) in DSH **0.2.0-rc.2**. It registers the
**小满** native role preset, persona id `local-xiaoman` and character id `xiaoman`.

- `seeds/persona.md` is the `persona` seed; it fills an absent persona head only. Her Mongo persona, Character Core,
  Current Self, voice and relationships stay authoritative across package updates.
- `persona-model.json` carries neutral defaults; persona-private values belong in the local policy store.
- `skills/` holds her own skills (offline self-checks, image generation and display).
- `resources-provenance.json` records the source hashes of the distributed resources.

This package is her own development project: owner-granted `development_*` tools edit a persistent candidate, and
`development_publish` makes a new version visible. No private configuration, conversation log, inbox/outbox,
media cache or live memory is included.
