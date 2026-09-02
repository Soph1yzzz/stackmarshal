# v1.1 Release Checklist

## Product and behavior

- [x] Explicit invocation gate and anti-trigger cases
- [x] research, prepare, build, and resume modes
- [x] deterministic state machine and append-only event log
- [x] capability/candidate schemas and scoring
- [x] supply-chain inspection, pinning, hashes, receipt-bound file rollback, and release symlink rejection
- [x] architecture-freeze and bounded-replan policy
- [x] formal stop states with checkpoint generation
- [x] repository-lineage identity, Git HEAD, dirty-state, and user-local HMAC checks on resume

## Installation and update

- [x] PowerShell and Bash one-command bootstraps
- [x] Git, Python 3.11+, and venv prerequisite detection
- [x] explicit approval before prerequisite installation, PATH changes, modified Skill replacement, or downgrade
- [x] latest-stable discovery and explicit semantic-version pinning
- [x] dedicated managed venv with no global/active-environment installation
- [x] strict SHA256SUMS verification for shared installer and payloads
- [x] safe Skill ZIP extraction and CLI/Skill version synchronization
- [x] staged atomic replacement, pre-commit rollback, modified Skill backup, and bounded cleanup
- [x] install, update, same-version repair, CLI-only, Skill-only, no-PATH, and explicit downgrade modes
- [x] post-install doctor and ignored isolated installation audit

## Quality

- [x] Ruff
- [x] mypy strict
- [x] full automated test suite, including installer, security regression, and permanent live-orchestration E2E contracts
- [x] branch-aware Core coverage at or above the configured 85% release gate
- [x] package build and Twine validation
- [x] `pyproject.toml`-authoritative version contract across Core, Skill, smoke path, CI, and living docs
- [x] staged release gate (`candidate`, `immutable`, `published`) with machine-readable evidence
- [x] schema meta-validation
- [x] Linux, macOS, and Windows CI matrix
- [x] installer Release build plus bootstrap smoke on each CI operating system
- [x] CodeQL workflow
- [x] commit-pinned GitHub Actions

## Security and release contract

- [x] Threat model, installation audit, and SECURITY.md
- [x] adversarial prompt/supply-chain/installer cases and fail-closed approval
- [x] zero required runtime dependencies
- [x] deterministic source, Skill, bootstrap, and Python package artifacts
- [x] portable SHA256SUMS, SBOM, provenance, and release manifest
- [x] every release receives focused source-backed security review of changed trust boundaries plus relevant adversarial/regression tests
- [x] full Codex Security repository scan is risk-triggered, not mandatory for every version
- [x] public GitHub Actions and CodeQL success on the release commit is mandatory
- [x] release manifest records passing component version-coherence evidence
- [x] terminal StackMarshal builds finalize bookkeeping before COMPLETE and record a non-mutating terminal repository seal
- [x] tag-to-commit, GitHub asset digests, downloaded checksums, and clean-install verification are mandatory

### Security scan trigger

The default release path is the full automated quality gate, CodeQL, relevant adversarial tests,
and a focused source-backed security review of the changed trust boundaries. A full Codex Security
repository scan is reserved for changes that materially alter security or execution authority,
including installer/bootstrap/update/PATH behavior, command approval or privilege boundaries,
checkpoint/signing/secret handling, workspace/path/archive containment, network/publication or
supply-chain behavior, authentication/cryptography, or a large architectural refactor. When a
trigger is present, the owner and maintainer explicitly decide whether the additional full scan is
worth its model/usage cost; a lower-cost model may be used only when that scan mode is validated to
work adequately. If the full scan is skipped, the release evidence records why and identifies the
compensating focused review and tests. A known unresolved material security finding still blocks
release regardless of scan mode.

When a full scan is used, its target code-bearing commit remains immutable. A later documentation-
only governance/evidence commit does not require another full scan when the diff is verified to be
non-executable and the final commit still passes CI, CodeQL, and the focused security review. CI
and CodeQL run IDs, optional full-scan metadata, tag-to-commit verification, and published asset
verification are recorded in the GitHub Release body. Version-specific counts, coverage
percentages, commits, and asset digests belong in immutable release notes/evidence rather than this
living checklist.
