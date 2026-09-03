# Future Work

Items intentionally outside the v1.1.4 version-management scope:

- Claude Code, Gemini CLI, Cline, GitHub Copilot, and OpenHands adapters.
- Multi-agent research/build/review orchestration.
- Optional registry-native discovery adapters beyond the host-provided tools.
- Signed provenance attestations and package-registry publication automation.
- Checkpoint migrations when a v1.x schema change is first introduced.
- A hosted dashboard or marketplace.

v1.1.3 closes the three runtime-trust defects discovered during the MandateMarshal v0.2 field dogfood:
Git porcelain status-column preservation, launcher/CLI/Skill/managed-install version-skew diagnosis,
and explicit fail-closed Windows reserved-device-name diagnostics. A later pre-release security review
also added authenticated live run/task authority to the same hardening release. These completed items
are release history, not future roadmap scope; see [RELEASE_NOTES_v1.1.3.md](RELEASE_NOTES_v1.1.3.md).

## Version roadmap

The next intended sequencing is:

- **v1.1.4 — Pin/version workflow**
  - `stackmarshal pin latest`, exact-version pinning, and pin status,
  - human `stackmarshal version` drift view while preserving script-friendly `--version`,
  - reuse of the verified atomic installer rather than a second update implementation.
- **v1.1.5 — Operator UX / non-invasive operation**
  - local/non-invasive initialization that does not dirty the target repository,
  - separate environment inventory from delivery-quality audit,
  - compact human CLI output with explicit full JSON mode.
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
