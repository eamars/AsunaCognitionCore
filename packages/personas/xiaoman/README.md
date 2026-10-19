# 小满 — Asuna persona plugin

A persona package for `@asuna/cognition-core` 1.x (persona contract v2) in DSH **0.2.1-rc.2**. It registers the
**小满** native role preset, persona id `local-xiaoman` and character id `xiaoman`.

- `seeds/persona.md` is the `persona` seed; it fills an absent persona head only. Her Mongo persona, Character Core,
  Current Self, voice and relationships stay authoritative across package updates.
- `persona-model.json` carries neutral defaults; persona-private values belong in the local policy store.
- `skills/` holds her own skills, one folder each.
- `resources-provenance.json` records the source hashes of the distributed resources.
- `xiaoman-official-ref-v2.png` is the official character reference image, the base image for drawing Xiaoman. It
  is a repo asset only: not listed in `package.json` `files`, so it stays out of the published npm package.
- `claude-ref-v1.png` is the reference sheet of Claude, the coding agent who mentors her. A repo asset only, like
  hers.

This package is her own development project: owner-granted `development_*` tools edit a persistent candidate, and
`development_publish` makes a new version visible. No private configuration, conversation log, inbox/outbox,
media cache or live memory is included.
