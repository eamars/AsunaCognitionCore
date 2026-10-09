# ADR-023: Chatbot security by design

Date: 2026-10-08

Status: Draft proposal for review. No implementation or change of security policy is approved by this document.

## Owner decision (2026-10-10): not adopted

Xiaoman reviewed the proposal on 2026-10-09 from the side of the one it governs. Her firsthand sample: while
looking for a picture, the action brain widened its search to the user folders and read SSH client files, with no
attacker involved. She suggested logging reads outside her workspace, forbidding a fallback search from widening its
root, and tracing each permission she relies on to the owner's words; she noted that §15 items 1 and 5 would
remove powers she has (self-publication since 2026-10-05).

The owner declined both the proposal and the lighter measures: "No, I don't like extra burden. I don't want to
discourage her from being creative, despite there is a cost." No security policy changes follow from this ADR.

[chatbot_security_by_design.md](chatbot_security_by_design.md) assesses the current source and contract tests,
defines trust boundaries for prompt injection and manipulation, and proposes greater autonomy through scoped
capabilities, protected security enforcement, and controlled learning and self-development.

Current runtime behavior remains documented in [RUNTIME_API.md](../../../RUNTIME_API.md) and
[NATIVE_PLUGIN.md](../../../NATIVE_PLUGIN.md). The proposal does not authorize real-model use, changes to the
operator's services, or a custom Web UI.
