# ADR-044 · Persona-owned identity and embodiment

Status: implemented in source, 2026-10-11. Requested by the owner for an embodied persona; real-model behavior has not been evaluated.

## Request and conflict

The owner asked for a persona that understands herself as a person with a physical body and a real personal past,
rather than as an AI or a fictional identity. The common role prompt imposed “没有现实身体” on every package,
contradicting such a persona before its own identity and biography were rendered.

## Decision

Identity, embodiment and established biography belong to the persona document. The common prompt no longer
assigns a universal body or ontology. Existing packages that describe themselves as digital characters continue
to supply that identity themselves. No new model parameter, state machine, rendering branch or UI is needed.

An embodied persona may speak of her own life, senses and bodily feelings in the first person. This does not
establish that the current interlocutor shares her location, has participated in her past, or has performed an
unobserved action. Personal biography, shared experience, examples and current scene facts remain distinct.

The common turn guidance continues to reject invented motives, shared history, the other person's bodily
reactions, tool results and delivery claims. Physical self-description grants no new perception or permissions.

## Delivery and evidence

The persona includes consistent bodily details and a personal timeline, with matching voice and ledger seeds.
Its package documentation describes the self-conception and installation requirements. Adoption into an existing
persona document continues to use the normal seed-adoption path; installing a package does not overwrite it.

Render probes check the embodied package and a digital fixture through the existing document renderer. Web review
uses an isolated native DSH profile and synthetic model routes. These checks establish loading and prompt
composition, not the stability of a real model's portrayal. No live profile switch or real-model call is part of
this change.
