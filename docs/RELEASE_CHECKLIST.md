# v1.0 Release Checklist

## Product and behavior

- [x] Explicit invocation gate and anti-trigger cases
- [x] research, prepare, build, and resume modes
- [x] deterministic state machine and append-only event log
- [x] capability/candidate schemas and scoring
- [x] supply-chain inspection, pinning, hashes, receipt-bound file rollback, and release symlink rejection
- [x] architecture-freeze and bounded-replan policy
- [x] formal stop states with checkpoint generation
- [x] repository-lineage identity, Git HEAD, dirty-state, and user-local HMAC checks on resume

## Quality

- [x] Ruff
- [x] mypy strict
- [x] 44 collected automated tests, including Codex Security regression groups
- [x] 94% branch-aware coverage
- [x] package build and Twine validation
- [x] schema meta-validation
- [x] Linux, macOS, and Windows CI matrix
- [x] CodeQL workflow
- [x] commit-pinned GitHub Actions

## Security and release

- [x] Threat model and SECURITY.md
- [x] adversarial prompt/supply-chain cases and fail-closed command approval
- [x] zero required runtime dependencies
- [x] deterministic source and Skill archives
- [x] SHA256SUMS, SBOM, provenance, release manifest
- [x] GitHub/PyPI/npm exact-name screening on 2026-08-04
- [x] Codex Security final scan has no unresolved reportable finding
- [x] GitHub Actions and CodeQL pass on the public repository
- [x] GitHub v1.0.0 Release assets and checksums are published

The release commit is immutable after its final security scan. Final scan metadata, fresh CI and
CodeQL run IDs, the tag-to-commit check, and the published asset verification are recorded in
the GitHub v1.0.0 release notes.
