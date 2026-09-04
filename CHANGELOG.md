# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and Semantic Versioning.

## [1.1.5] - 2026-09-04

### Added

- Add real same-run resume with `stackmarshal resume <run-id>` for integrity-validated `CHECKPOINT_READY`, external-blocked, verification-external-blocked, and approval-wait checkpoints.
- Add `stackmarshal migrate` to preserve legacy unsigned run/task evidence in a read-only hash-manifested archive without promoting it to signed execution authority.
- Add bounded `VERIFICATION -> CORRECTION -> VERIFICATION` for small verification fixes without consuming architecture-replan budget.
- Add first-class `VERIFICATION_EXTERNAL_BLOCKED` stop semantics for network/service-dependent verification gates.
- Add `stackmarshal repair --remove-shadowed` for explicitly removing only high-confidence stale StackMarshal PATH launchers after managed repair.

### Fixed

- Propagate mandatory `BLOCKED_EXTERNAL:` / `VERIFICATION_EXTERNAL_BLOCKED:` task blockers into run-level stop reasons and signed checkpoints.
- Return success for successful explicit checkpoint creation and state clearly that the terminal checkpoint was created successfully.
- Force UTF-8 CLI stdout/stderr evidence so Japanese invocation text survives Windows legacy console encodings.
- Avoid project `.gitignore` mutation when Git already ignores StackMarshal state through `.git/info/exclude`, global excludes, or an existing ignore rule.
- Bind non-Git checkpoints to a real workspace fingerprint instead of `None`, so post-checkpoint changes invalidate resume.

### Changed

- Move the remaining fully non-invasive init, delivery-audit, and compact-output roadmap work from v1.1.5 to v1.1.6 after dogfood exposed higher-priority recovery correctness issues.

## [1.1.4] - 2026-09-03

### Added

- Add `stackmarshal pin latest`, exact-version `stackmarshal pin <version>`, and `stackmarshal pin status` using the existing verified atomic installer.
- Add human `stackmarshal version` output that reports runtime, managed pin, Skill, launcher, and `OK` / `DRIFTED` status while preserving script-friendly `stackmarshal --version`.
- Verify the selected published Release bootstrap against its `SHA256SUMS` before `pin` executes it.

### Changed

- Treat stale StackMarshal launchers later on `PATH` as visible shadowed-version warnings rather than blocking skew when the resolved managed launcher, Skill, and runtime are aligned.
- Move the previously planned non-invasive init, delivery audit, and compact CLI work from v1.1.4 to v1.1.5 without expanding this release scope.

## [1.1.3] - 2026-09-02

### Fixed

- Preserve leading Git porcelain status columns so terminal-seal dirty paths are recorded exactly instead of dropping the first filename character.
- Expand `doctor` with non-executing launcher/package/managed-install provenance and explicit multi-version StackMarshal skew detection.
- Detect Windows reserved device names during workspace fingerprinting and report the actual cause while remaining fail-closed.
- Authenticate canonical live `run.json` and `task-graph.json` with the user-local integrity key so unsigned or modified repository state cannot become execution/completion authority.

### Documentation

- Add Case Study #2 for MandateMarshal v0.2 durable-runtime/crash-recovery field dogfooding, including the completion gate rejecting stale verification after a late source change.
- Split the roadmap so runtime-trust fixes land in v1.1.3 and non-invasive init, delivery audit, and compact CLI output remain v1.1.4 work.
- Adopt risk-triggered full repository security scans while keeping focused source review, adversarial regressions, CI, and CodeQL mandatory for every release.

## [1.1.2] - 2026-08-23

### Added

- v1.1.2 release-version contract with `pyproject.toml` as authority and fail-closed Core/Skill/docs coherence checks.
- Staged candidate/immutable/published release gate with machine-readable evidence, safe build-output cleanup, and immutable Git-state contamination checks.
- Explicit VERIFICATION finalization and non-mutating terminal repository seal before COMPLETE.
- Workspace-state symlink/junction containment across initialization, runtime state, finalization, version sync, and release-gate evidence writes.
- Fail-closed Git read-command option handling for helper execution, output writes, alias/global-option injection, and repository-read escapes.
- Repository configuration guardrails that permit tighter budgets but require explicit user CLI selection for deep/looser execution budgets and preserve mandatory approvals/guarded autonomy.
- Permanent nested-workspace live-orchestration E2E regression contract.

### Changed

- Finalization now classifies unsafe managed-state paths as `INVALID_STATE` consistently across platforms, including symlink-capable Linux/macOS CI.
- Release manifests include component version-coherence evidence.
- Living release checklist uses stable gate requirements instead of stale release-specific counts.
- Future work now lives at the repository-contract path `docs/FUTURE_WORK.md`.

## [1.1.1] - 2026-08-16

### Added

- One authoritative live run across nested-repository bootstrap and first-commit lineage migration.
- Core-owned live activity/budget accounting and canonical task graph with evidence-gated COMPLETE.
- Versioned restart-pending marker and stale-host readiness refusal after Skill update.

### Changed

- Live phase snapshots distinguish real orchestration from retrospective transition replay.
- COMPLETE fails closed on stale mandatory tasks, missing live activity, untouched tool budgets, and missing implementation change evidence.

## [1.1.0] - 2026-08-05

### Added

- One-command Windows PowerShell and macOS/Linux Bash installation for the CLI and matching Codex Skill.
- Stable-version discovery, explicit version pinning, same-version repair, update, and guarded downgrade flows.
- Explicit approval before installing missing Git, Python, or venv support and before changing PATH or replacing a modified Skill.
- Dedicated managed virtual environments, strict Release checksum verification, safe Skill ZIP extraction, atomic directory swaps, rollback, modified-Skill backup, and post-install doctor checks.
- Cross-platform installer smoke tests and fresh-install audit evidence.

### Changed

- Release assets now include `install.ps1`, `install.sh`, and the shared `installer.py`.
- The recommended installation path no longer writes into the active or global Python environment.
- Skill and CLI release versions are synchronized and recorded in installer state.

## [1.0.0] - 2026-08-04

### Added

- Explicit multilingual StackMarshal invocation gate and mode inference.
- Deterministic state machine, event log, budgets, progress evaluation, and stop harness.
- Candidate scoring, supply-chain inspection, lock verification, acquisition receipts, and rollback.
- User-local HMAC-signed checkpoints and acquisition receipts, repository-lineage identity, exact worktree fingerprints, and resume inspection.
- Agent-neutral Core with the initial Codex adapter.
- Installable Codex Skill with bounded fallback scripts.
- Cross-platform CLI, JSON Schemas, 94% branch-aware test coverage, and adversarial tests.
- English primary README and Japanese secondary README.
- Reproducible release assets, symlink rejection, portable LF SHA-256 checksums, SBOM, and provenance metadata.
- Linux, macOS, Windows CI and CodeQL workflows with commit-pinned Actions.
- Fail-closed command approval, strict run IDs, signing-key isolation, and hash-verified receipt-bound non-recursive rollback.
