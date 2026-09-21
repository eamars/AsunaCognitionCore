# Strict Development Boundaries

## Must do
- Reuse DSH frontend/plugin APIs where possible.
- Integrate into the current simple interaction UI path.
- Keep frontend architecture thin.
- Use generic event rendering so new event types can appear without redesign.
- Keep text readable and layout clean.

## Must not do
1. Do not create a separate full web app if a plugin/embedded view is enough.
2. Do not replace existing Asuna runtime architecture.
3. Do not redesign storage or cognition for this task.
4. Do not build a complex settings system.
5. Do not add charts, graphs, avatars, illustrations, or decorative cards unless necessary.
6. Do not create fake “AI insights” panels.
7. Do not add automatic scoring, ranking, or sentiment dashboards.
8. Do not build a generalized memory CMS.
9. Do not add multi-page navigation if one integrated workbench view is enough.
10. Do not hardcode future feature assumptions into the layout.

## Data boundary
This UI should consume already-available or lightly adapted data from the existing Asuna/DSH integration.
If a backend field is missing, add only the minimum adapter needed for UI display.
Do not create a large new backend layer for presentation convenience.

## Mock data rule
Mock data is allowed only for:
- local visual development
- storybook/demo rendering

Mock data must not be confused with runtime data.
Runtime wiring must remain clearly separated.
