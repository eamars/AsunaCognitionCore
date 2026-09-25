# Asuna development and interaction rules

- Use the existing Web UI for normal interaction, runtime observation, execution details, and interactive review. Prefer the in-app browser when available and inspect the visible result.
- The default entry point is `start-asuna.cmd`; `start-asuna-ui.cmd` is an alias. It runs `asuna ui`. Do not replace Web interaction with terminal chat, stdin text injection, or `asuna run`; fix Web issues in the Web path.
- CLI commands other than `ui` are for explicit `--debug` diagnosis and maintenance. Shell may be used for source edits, host lifecycle, and non-interactive diagnostics; these do not replace Web review.
- `chat.py`'s `Chat` class is the Web-reused queue and action controller. `chat()` and `terminal()` are debug terminal adapters; Web does not call them or load terminal input dependencies.
- Asuna extends the pinned DSH runtime. Prefer its existing capabilities and public UI primitives; do not duplicate its scheduler, tool system, or UI control library without a documented need.
- Character brain and action brain name responsibilities, not model families. Configure their routes independently; UI labels, compatibility, reasoning, and token counting must not infer a model from a lane name.
- Current manuals describe behavior in the source, configuration, and contract tests. `README.md`, `RUN_ASUNA.md`, and `RUNTIME_API.md` are current references. `docs/development_plans/**` preserves design decisions and future plans and is not authority for current runtime behavior.
- In body text, Chinese fonts may supply English glyphs. Inline code, code blocks, JSON, tool payloads, and code editors use the shared monospace font stack.
