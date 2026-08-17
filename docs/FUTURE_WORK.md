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

These items must not weaken explicit invocation, approval boundaries, supply-chain controls,
or the finite stop harness.
