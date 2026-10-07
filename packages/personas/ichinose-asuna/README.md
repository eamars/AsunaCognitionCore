# @asuna/ichinose-asuna

一之瀬アスナ (一之濑明日奈, Ichinose Asuna): an original persona inspired by the Blue Archive character of that name, for the Asuna core
(persona contract v2).

- `seeds/persona.md` and `seeds/voice.md` are original text written from public descriptions of the character; no
  game dialogue or wiki text is used. The portrayal is strictly non-sexual.
- `persona-model.json` is the neutral demo model with her identity: a home heartbeat, no visits, up to three
  messages a turn.
- She has no channel configuration of her own; the persona works in the local chat alone or with any channel.

Install it like any persona package: `--persona packages/personas/ichinose-asuna` to the packer and
`--persona-package packages/personas/ichinose-asuna` to the installer ([RUN_ASUNA.md](../../../RUN_ASUNA.md)), or
`ASUNA_PERSONA_PACKAGE` in a container deployment (`deploy/`).

`icon.png` is a crop of the character's official game art. The art belongs to the game's publishers and is not
covered by this repository's license.
