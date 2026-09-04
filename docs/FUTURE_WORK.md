# Future Work

Items intentionally outside the v1.1.5 dogfood recovery-hardening scope:

- Claude Code, Gemini CLI, Cline, GitHub Copilot, and OpenHands adapters.
- Multi-agent research/build/review orchestration.
- Optional registry-native discovery adapters beyond the host-provided tools.
- Signed provenance attestations and package-registry publication automation.
- Schema-version migrations beyond the v1.1.5 legacy unsigned-state archival boundary.
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
- **v1.1.5 — Dogfood recovery hardening**
  - same-run resume from integrity-validated `CHECKPOINT_READY` / resumable external or approval stops,
  - legacy unsigned run/task state archival without promoting untrusted evidence to signed authority,
  - bounded `VERIFICATION -> CORRECTION -> VERIFICATION` without spending architecture-replan budget,
  - run-level external-block propagation, first-class external-verification blocking, UTF-8 CLI evidence, successful checkpoint exit semantics,
  - avoid `.gitignore` mutation when Git already ignores StackMarshal state, plus explicit high-confidence shadowed-launcher repair.
- **v1.1.6 — Operator UX / fully non-invasive operation**
  - repository-external/local initialization mode beyond the v1.1.5 existing-ignore optimization,
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
