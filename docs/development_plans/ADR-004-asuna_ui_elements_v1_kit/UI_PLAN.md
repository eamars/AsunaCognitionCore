# Asuna UI Elements V1 – Plan

## Scope
This task is only about the frontend **UI elements layer**.
It should sit on top of the previously established simple interaction interface.

## Design principles
1. **Light theme only** for this version.
2. **Information first**; decorative visuals minimal.
3. **Bubble-based chat stays primary**.
4. **Dual-brain interaction is visible**, but not turned into a noisy engineering console.
5. **Memory and preference views are simple, searchable, inspectable**.
6. **Avoid hardcoding UI around specific future features**.
7. **Adding new event types should not require a page redesign**.

## Main layout
Three-column desktop layout:

### Left column
- conversation list / channel list
- recent sessions
- simple navigation only

### Center column
- header for current conversation
- normal chat bubble stream
- below / within reply context: dual-brain execution area
- message composer at bottom

### Right column
- inspector panel
- tabbed views: memory / preference / group preference / relationship
- selected item detail view

## What “dual-brain interaction” should look like
Use a **chat-like or bubble/list form**, not a graph editor.
Recommended structure:
- one container per assistant reply
- inside it, ordered event rows or bubble rows such as:
  - role brain (Gemma)
  - action brain (Qwen)
  - tool call
  - tool result
  - final role polish / reply

This should feel like a readable “conversation of internal steps”, not a raw log dump.

## UI behavior
- default view: user sees chat first
- execution details can be collapsed / expanded
- errors stay visible and are not auto-hidden
- empty inspector tabs show simple empty state, not placeholder fake data

## Not in scope
- dark theme
- mobile redesign
- graph visualization
- live node editor
- model prompt editing UI
- permissions admin console
- memory editing workflows beyond minimal inspect / optional simple edit action if already trivial
