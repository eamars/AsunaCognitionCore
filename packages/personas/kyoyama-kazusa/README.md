# @asuna/kyoyama-kazusa

杏山カズサ (杏山千纱, Kyoyama Kazusa): an original persona inspired by the Blue Archive character of that name, for the Asuna core
(persona contract v2).

- `seeds/persona.md` and `seeds/voice.md` are original text written from public descriptions of the character; no
  game dialogue or wiki text is used. The portrayal is strictly non-sexual.
- `persona-model.json` is the neutral demo model with her identity: a home heartbeat, no visits, up to two
  messages a turn, and how she treats people by how well she knows them (`people.familiarity`): she does no work
  for people she hardly knows unless the owner asks.
- She is written for group chats as well as the local chat; any channel package works with her.

Install it like any persona package: `--persona packages/personas/kyoyama-kazusa` to the packer and
`--persona-package packages/personas/kyoyama-kazusa` to the installer ([RUN_ASUNA.md](../../../RUN_ASUNA.md)), or
`ASUNA_PERSONA_PACKAGE` in a container deployment (`deploy/`).

`icon.png` is a crop of an illustration of the character supplied by the owner. The character belongs to the game's
publishers and is not covered by this repository's license.
