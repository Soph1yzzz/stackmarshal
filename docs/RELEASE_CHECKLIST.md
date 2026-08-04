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
- [x] 61 collected automated tests, including installer and Codex Security regression groups
- [x] 94% branch-aware Core coverage
- [x] package build and Twine validation
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
- [x] final Codex Security scan on the immutable release commit is mandatory
- [x] public GitHub Actions and CodeQL success on the release commit is mandatory
- [x] tag-to-commit, GitHub asset digests, downloaded checksums, and clean-install verification are mandatory

The release commit is immutable after its final security scan. Authoritative scan metadata, CI
and CodeQL run IDs, tag-to-commit verification, and published v1.1.0 asset verification are
recorded in the GitHub Release body so no post-scan metadata commit is required.
