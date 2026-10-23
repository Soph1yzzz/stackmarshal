# Future Work

Items intentionally outside the v1.2.3 adaptive exploration/evidence scope:

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
- **v1.1.6 — Windows self-update cleanup hotfix**
  - defer only Windows file-lock cleanup failures from the updating CLI's old version directory,
  - use the newly installed version's Python to retry cleanup after the old CLI exits,
  - preserve fail-closed behavior for non-lock cleanup errors and unsafe paths.
- **v1.2.0 — Host-write transport / adapter foundation**
  - preserve the existing direct-filesystem path for normal Codex/CLI operation,
  - add an HMAC-authenticated host-write plan/check/ack boundary for hosts that prohibit shell-side project mutation,
  - bind each mutation to canonical contained paths plus expected preimage and required postimage SHA-256 values,
  - serialize project mutations while a host-write plan is pending,
  - extend Windows installer cleanup to stale same-version swap backups exposed by repair dogfood.
- **v1.2.1 — HostWrite ergonomics / transaction hardening**
  - enforce the pending-plan invariant at project-mutation admission in both direct and host modes, plus exclusive pending-slot creation,
  - replace growing `events.jsonl` full-file plans with compact append/CAS operations and content-addressed recovery preimages,
  - add `host-write recover` and a signed-tail DevSpace edit path without pretending per-file host APIs are multi-file atomic,
  - add signed fingerprint-preserving workspace relocation as a distinct identity migration from repository bootstrap,
  - add a managed extensionless Windows shell shim so bare `stackmarshal` works from Git Bash without creating doctor alias noise.
- **v1.2.2 — Introspection / adaptive harness**
  - add read-only `stackmarshal next` state introspection without prescribing recovery commands,
  - admit mandatory work discovered after the frozen task graph only through bounded `REPLAN`,
  - accept monotonic host-observed tool-call totals without double-counting replayed telemetry,
  - separate Core readiness from Codex Skill/session readiness while keeping explicit integration checks strict.
- **v1.2.3 — Adaptive exploration and evidence integrity**
  - safe early Git bootstrap with ancestor-repository and unborn-HEAD diagnostics,
  - workflow profiles for short experiments, normal builds, and audited releases,
  - reasoned soft exploration limits without removing hard resource/safety caps,
  - signed task-amendment history and read-only workspace evidence reconciliation.
- **v1.2.4 — Invocation/continuation correctness hotfix**
  - fix false negatives for explicit multilingual mechanism requests and explicit non-use cases,
  - distinguish fresh invocation from same-task signed-run continuation admission,
  - expose machine-readable refusal reasons without weakening HMAC, approval, or resume rules.
- **v1.2.5 — Operator UX / fully non-invasive operation**
  - repository-external/local initialization mode beyond the v1.1.5 existing-ignore optimization,
  - separate environment inventory from delivery-quality audit,
  - compact human CLI output with explicit full JSON mode,
  - make actionable shadowed-launcher cleanup guidance visible directly in doctor output.
- **v1.2.6 — Claude Code adapter**
- **v1.2.7 — Gemini CLI adapter**
- **v1.2.8 — Adapter conformance polish**
- **v1.3.0 — Multi-agent orchestration**
- **v1.4.0 — Signed provenance**
- **v2.0.0 — schema/migrations-class changes**

This roadmap records intended release boundaries, not a compatibility promise or delivery date.
Scope may move only if the same safety and migration contracts are preserved explicitly.

These items must not weaken explicit invocation, approval boundaries, supply-chain controls,
or the finite stop harness.
