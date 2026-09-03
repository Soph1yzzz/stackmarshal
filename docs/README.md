# StackMarshal documentation

Use this index to jump directly to the part of StackMarshal you need to evaluate, operate, audit, or extend.

## Architecture

Start with [ARCHITECTURE.md](ARCHITECTURE.md) for the Core/adapter/Skill split, deterministic state model, bounded workflow, and major design boundaries.

## Case Study

- [Case Study #1 — RepoHealth](CASE_STUDY_01_REPOHEALTH.md) records the controlled Phase 3B dogfooding evidence, including what passed, what did not run remotely, and which integration gaps were discovered. A [Japanese version](CASE_STUDY_01_REPOHEALTH.ja.md) is also available.
- [Case Study #2 — MandateMarshal v0.2](CASE_STUDY_02_MANDATEMARSHAL.md) records field use during durable-runtime/crash-recovery development, including a real stale-verification rejection and the runtime-trust defects that drove v1.1.3. A [Japanese version](CASE_STUDY_02_MANDATEMARSHAL.ja.md) is also available.

## Security

- [THREAT_MODEL.md](THREAT_MODEL.md) — trust boundaries, assets, attacker model, and mitigations.
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md) — repository security review and adversarial findings.
- [INSTALLATION_AUDIT.md](INSTALLATION_AUDIT.md) — installer/update/repair security and reproducibility evidence.
- [../SECURITY.md](../SECURITY.md) — supported versions and vulnerability-reporting policy.

## Traceability

Use [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) to map requirements to implementation and evidence. For verification history, also see [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md) and [FORWARD_TEST_REPORT.md](FORWARD_TEST_REPORT.md).

## Release

- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — current release process and required gates.
- [RELEASE_NOTES_v1.1.4.md](RELEASE_NOTES_v1.1.4.md) — v1.1.4 pin/version workflow and managed version-skew convergence.
- [RELEASE_NOTES_v1.1.3.md](RELEASE_NOTES_v1.1.3.md) — v1.1.3 runtime-trust hardening derived from MandateMarshal field use.
- [RELEASE_NOTES_v1.1.2.md](RELEASE_NOTES_v1.1.2.md) — v1.1.2 release and terminal-integrity hardening.
- [RELEASE_NOTES_v1.1.1.md](RELEASE_NOTES_v1.1.1.md) — RepoHealth-driven live-orchestration hardening.
- [RELEASE_NOTES_v1.1.0.md](RELEASE_NOTES_v1.1.0.md) and [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md) — earlier release history.

## Future Work

Read [FUTURE_WORK.md](FUTURE_WORK.md) for intentionally deferred scope and the version roadmap. Proposed design changes should follow [RFC_PROCESS.md](RFC_PROCESS.md).

## Other audit material

- [NEXTPATCH_EXPERIMENT_REPORT.md](NEXTPATCH_EXPERIMENT_REPORT.md) — clean-room reproduction and regression evidence for the RepoHealth integration gaps.
- [NAME_CLEARANCE.md](NAME_CLEARANCE.md) — project naming/trademark review record.
