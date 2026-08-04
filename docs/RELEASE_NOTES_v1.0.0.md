# StackMarshal v1.0.0

StackMarshal is a bounded, research-first workflow for Codex that maps required capabilities,
evaluates reusable Skills, MCP servers, plugins, libraries, CLIs, and reference OSS, freezes
architecture, implements within explicit budgets, verifies acceptance criteria, and returns
either `COMPLETE` or a resumable formal stop state.

## Highlights

- Explicit-only multilingual invocation with `$stackmarshal` as a reliable fallback.
- Deterministic Python 3.11+ Core with zero required runtime dependencies.
- Bounded state machine, budget counters, failure fingerprints, stagnation detection, and
  safety-first stop priority.
- Candidate scoring, provenance locks, install-hook inspection, isolated acquisition receipts,
  exact-file rollback, and hash verification.
- Fail-closed command approval for unknown, destructive, interpreter, network, publication,
  privileged, secret-access, and billable actions.
- User-local HMAC signatures for checkpoints and acquisition receipts.
- Repository-lineage identity plus exact tracked, staged, and untracked worktree fingerprints
  for safe resume.
- Reproducible Skill/source archives, wheel/sdist, portable LF SHA-256 checksums, CycloneDX
  SBOM, and provenance metadata.
- Commit-pinned GitHub Actions across Windows, macOS, and Linux, plus CodeQL.
- English primary documentation and a complete Japanese README.

## Installation

Install the Skill directory with the Codex Skill installer, or install the Python package from
the attached wheel/source archive. Verify downloaded files against `SHA256SUMS` before use.

## Security

The release was reviewed with the Codex Security repository-wide workflow. The initial scan
found five reportable issues in approval classification, release symlink handling, rollback,
run-state path handling, and checkpoint authenticity. All were remediated with adversarial
regression tests before the final release scan.

See `SECURITY.md`, `docs/THREAT_MODEL.md`, and `docs/ACCEPTANCE_REPORT.md` for the trust model,
limitations, and evidence.
