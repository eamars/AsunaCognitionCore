# ADR-023: Chatbot security by design

Date: 2026-10-08

Status: Draft proposal for review. No implementation or change of security policy is approved by this document.

[chatbot_security_by_design.md](chatbot_security_by_design.md) assesses the current source and contract tests,
defines trust boundaries for prompt injection and manipulation, and proposes greater autonomy through scoped
capabilities, protected security enforcement, and controlled learning and self-development.

Current runtime behavior remains documented in [RUNTIME_API.md](../../../RUNTIME_API.md) and
[NATIVE_PLUGIN.md](../../../NATIVE_PLUGIN.md). The proposal does not authorize real-model use, changes to the
operator's services, or a custom Web UI.
