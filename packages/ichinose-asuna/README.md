# @asuna/ichinose-asuna

一之瀬アスナ: an original persona inspired by the Blue Archive character of that name, running on the Asuna core. The owner asked for her on 2026-10-07 as the first persona deployed on Linux (ADR-019).

- Her persona and voice (`seeds/`) are written fresh from public descriptions of the character. No game dialogue or wiki text is copied. The portrayal is strictly non-sexual.
- The persona model is the neutral demo model with her identity: a home heartbeat, no visits, up to three messages a turn.
- She has no channel of her own. In her first deployment she talks only in her local chat.

Install it like any persona package: pass `--persona packages/ichinose-asuna` to the packer and `--persona-package packages/ichinose-asuna` to the installer. In a container deployment, set `ASUNA_PERSONA_PACKAGE` (see `deploy/`).

`icon.png` is a head-only crop of the character's official game art, supplied by the owner. The art belongs to the game's publishers and is not covered by this repository's license.
