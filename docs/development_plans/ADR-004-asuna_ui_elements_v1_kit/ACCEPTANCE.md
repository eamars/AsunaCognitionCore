# Acceptance Criteria

## A. Layout
- A three-column light-theme workbench exists.
- Left sidebar shows conversations/channels.
- Center shows chat bubbles.
- Right inspector has tabbed records.

## B. Chat usability
- Normal user/assistant conversation is readable.
- Final assistant reply is visually primary.
- Input box remains simple and usable.

## C. Dual-brain visibility
- For an assistant reply, the user can expand and inspect internal steps.
- Internal steps are shown as ordered readable rows or bubble-style entries.
- Role brain and action brain are distinguishable.
- Tool steps, when present, are visible.
- Errors are visible and not silently collapsed away.

## D. Memory / preference inspector
- Memory tab lists records.
- Preference / group preference / relationship tabs are accessible.
- Selecting a record shows detail.
- Record rendering works without requiring hardcoded per-record layouts.

## E. Boundary compliance
- No dark theme in V1.
- No graph view.
- No analytics dashboard.
- No fake data in runtime mode.
- No new large backend/service introduced only for UI.

## F. Forward compatibility
- A new event type can appear in the internal trace without a layout rewrite.
- A new inspector record type can still render through generic record components.
