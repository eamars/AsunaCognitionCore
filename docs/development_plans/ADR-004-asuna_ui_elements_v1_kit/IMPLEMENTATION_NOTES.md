# Implementation Notes for Codex

## Preferred implementation direction
1. First inspect current DSH frontend extension points available in the local project version.
2. Prefer:
   - sidebar / tab registration
   - embedded panel or workbench page registration
   - existing event/session APIs
3. Avoid direct patching of DSH core frontend code unless absolutely necessary.

## Integration strategy
- Use the current simple interaction interface as the entry path.
- Add one UI workbench / plugin view for Asuna.
- Read existing session/conversation data and Asuna-specific trace/inspector data.
- If a small adapter is needed, place it in a thin bridge layer.

## Visual strategy
- mimic the mockup structure, not every pixel
- spacing and hierarchy more important than ornament
- keep it readable on a standard desktop

## Development strategy
- build the shell
- wire the center chat area
- wire the internal trace section
- wire the right inspector tabs
- polish after all three are visible

## Stop condition
Once the UI satisfies the acceptance criteria and is usable with live data, stop.
Do not continue expanding feature scope unless explicitly requested.
