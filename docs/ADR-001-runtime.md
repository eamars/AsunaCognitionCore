# ADR-001: explicit pinned DSH runtime on Windows

Status: integration probe pending.

The host is Windows/Python 3.12/Node 24.18.0. The Python package index returned
no SDK/runtime distribution. The source runtime carrier lists Linux/macOS
wheels. We use the upstream Python SDK, without modifying its implementation,
from release commit `fb2c4b9e698e30edb738bca4cf0618587db7d203`
(`dsh-v0.1.5-rc.2`) with an explicit project-local npm DSH executable of the
same release. uv excludes the otherwise mandatory runtime wheel; npm's lock
and executable hashes are part of the deployment manifest. There is no implicit
selection of a global executable or the user's default profile.

The external discovery checkout changed from b150a551 to ddefc45f during
read-only discovery. Asuna did not make those changes. All further integration
uses a separate detached checkout under `.runtime/dsh-source`; no moving HEAD
is a build input.

Python remains the sole business coordinator. The lane boundary adapts actual
SDK operations and does not claim generic `session.compact()` or business APIs.
The custom TS plugin supplies prompt composition, controlled tools, and needed
auditable integration hooks. No unrestricted shell tools are enabled.

The user explicitly named `asuna_cognition_core_v2`. This exact new name is
allowlisted in addition to `asuna_v2_test_*`, overriding the bundle's example
prefix. The legacy database name is a separate deny rule. No legacy collections
are read or written for application data.
