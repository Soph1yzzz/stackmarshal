# Future Work

Items intentionally outside the v1.1 release-hardening scope:

- Claude Code, Gemini CLI, Cline, GitHub Copilot, and OpenHands adapters.
- Multi-agent research/build/review orchestration.
- Optional registry-native discovery adapters beyond the host-provided tools.
- Signed provenance attestations and package-registry publication automation.
- Checkpoint migrations when a v1.x schema change is first introduced.
- A hosted dashboard or marketplace.

v1.1.2 deliberately focuses on release and terminal integrity. New adapters and
multi-agent behavior belong in a feature release (v1.2.0 or later), after the Codex
release/operation contract is stable.

## Version roadmap

The current intended sequencing is:

- **v1.2.0 — Adapter framework + Claude Code adapter**
- **v1.2.1 — Gemini CLI adapter**
- **v1.2.2 — Adapter conformance polish**
- **v1.3.0 — Multi-agent orchestration**
- **v1.4.0 — Signed provenance**
- **v2.0.0 — schema/migrations-class changes**

This roadmap records intended release boundaries, not a compatibility promise or delivery date.
Scope may move only if the same safety and migration contracts are preserved explicitly.

These items must not weaken explicit invocation, approval boundaries, supply-chain controls,
or the finite stop harness.
