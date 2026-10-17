# 小满 — Asuna persona plugin

A persona package for `@asuna/cognition-core` 0.2.x (persona contract v2) in DSH **0.2.1-rc.1**. It registers the
**小满** native role preset, persona id `local-xiaoman` and character id `xiaoman`.

- `seeds/persona.md` is the `persona` seed; it fills an absent persona head only. Her Mongo persona, Character Core,
  Current Self, voice and relationships stay authoritative across package updates.
- `persona-model.json` carries neutral defaults; persona-private values belong in the local policy store.
- `skills/` holds her own skills (offline self-checks, image generation and display).
- `resources-provenance.json` records the source hashes of the distributed resources.
- `xiaoman-official-ref-v2.png` is the official character reference image — the base image for drawing Xiaoman from
  now on (owner-approved for the public repo, 2026-10-14). It is a repo asset only: not listed in `package.json`
  `files`, so it stays out of the published npm package. The v1 alternative is kept out of the repo.
- `claude-ref-v1.png` is the reference sheet of Claude, the coding agent who mentors her, as her older sister: drawn
  and chosen by Claude on the owner's invitation (2026-10-15; `anima-turbo-v1-1`, seed 777, glasses added to one
  close-up with `qwen-image-2.1-edit`). A repo asset only, like hers.

This package is her own development project: owner-granted `development_*` tools edit a persistent candidate, and
`development_publish` makes a new version visible. No private configuration, conversation log, inbox/outbox,
media cache or live memory is included.
