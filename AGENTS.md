# Asuna development and interaction rules

- Use the existing Web UI for normal interaction, runtime observation, execution details, and interactive review. Prefer the in-app browser when available and inspect the visible result.
- The default entry point is `start-asuna.cmd`; `start-asuna-ui.cmd` is an alias. It launches the installed native DSH Web profile; `asuna ui` selects the same profile. Do not replace Web interaction with terminal chat, stdin text injection, or `asuna run`; fix Web issues in the Web path.
- CLI commands other than `ui` are for explicit `--debug` diagnosis and maintenance. Shell may be used for source edits, host lifecycle, and non-interactive diagnostics; these do not replace Web review.
- `chat.py`'s `Chat` class is the Web-reused queue and action controller. There is no terminal chat adapter; all interaction goes through the Web UI.
- Asuna extends the pinned DSH runtime. Prefer its existing capabilities and public UI primitives; do not duplicate its scheduler, tool system, or UI control library without a documented need.
- Character brain and action brain name responsibilities, not model families. Configure their routes independently; UI labels, compatibility, reasoning, and token counting must not infer a model from a lane name.
- Current manuals describe behavior in the source, configuration, and contract tests. `README.md`, `RUN_ASUNA.md`, and `RUNTIME_API.md` are current references. `docs/development_plans/**` preserves design decisions and future plans and is not authority for current runtime behavior.
- In body text, Chinese fonts may supply English glyphs. Inline code, code blocks, JSON, tool payloads, and code editors use the shared monospace font stack.
- The core is persona-agnostic. Persona names, persona text, and persona-specific parameters live only in persona packages, persona-private data, or test fixtures; core code, core prompts, core tools, and example configs must not contain them.
- Personal data stays local. Real account IDs, addresses, host names, user names, time zones, and private content belong in ignored local config, MongoDB, or private source roots, never in tracked files. Examples use documentation-reserved placeholders.
