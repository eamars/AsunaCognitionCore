# Asuna UI Elements V1 – Codex Start

This package is the **UI elements version** for the Asuna inspector frontend.
It is **not** a full product redesign and **not** a new cognition/runtime project.

## Purpose
Build a **minimal, light-theme DSH frontend plugin / extension UI** for the existing Asuna simple interaction interface.
The UI should make the existing interaction flow easier to inspect, especially:

1. normal chat bubbles
2. dual-brain interaction bubbles / trace
3. memory / preference inspection
4. minimal debug visibility

## Primary Goal
Deliver a **usable UI layer** that integrates with the existing simple interaction interface and can display:
- user / Asuna chat bubbles
- the role-brain and action-brain interaction process for a reply
- memory / preference / group preference panels

## Do not overdevelop
Codex must **not** turn this into:
- a full new product shell
- a general-purpose dashboard platform
- a heavy analytics console
- a node graph / workflow editor
- a plugin marketplace
- a visual database admin
- a redesign of cognition runtime
- a new backend if existing APIs are enough

## Strict build order
1. Read all files in this package.
2. Build the **UI only**, on top of the current simple interaction interface.
3. Reuse DSH-native frontend extension / plugin APIs where possible.
4. Match the provided mockup structure closely.
5. Keep the implementation thin and forward-compatible.
6. Stop after the acceptance items are satisfied.

## Required outputs
- working frontend plugin / extension code
- one README for running it locally
- one short integration note listing which existing APIs / events it consumes
- one limitations note describing what is intentionally not implemented

## Delivery rule
The first usable delivery must already show:
- chat bubble area
- dual-brain execution area in bubble/list form
- right-side memory inspector tabs

Do **not** wait for perfect completeness before showing a usable build.
