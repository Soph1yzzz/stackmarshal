# Threat Model

## Assets

Workspace integrity, existing Git changes, credentials, publication authority,
execution budget, checkpoint truth, provenance, and acceptance evidence.

## Trust boundaries

User instructions are authoritative within host policy. Local project instructions
are trusted only for their repository scope. External README/Issue/SKILL/registry
metadata are untrusted data. Package scripts and binaries cross an execution boundary.
Global configuration, secrets, billing, privilege, network writes, publication, prerequisite
installation, user PATH changes, and replacement of modified Skills cross explicit approval
boundaries.

## Principal threats and controls

- Prompt injection: evidence-only handling and no candidate orchestration authority.
- Malicious/typosquatted dependency: canonical source, score, license, pin, hash, PoC.
- Installer/bootstrap substitution: versioned GitHub Release URLs, strict SHA256SUMS parsing, verified shared installer and payloads, dedicated venv, `--no-index --no-deps`, and post-install doctor.
- Installer archive escape: regular-file-only Skill extraction, canonical path containment, duplicate rejection, and symlink rejection.
- Interrupted update or repair: staged directory swaps, launcher/state snapshots, rollback before commit, and bounded cleanup after success.
- Silent global mutation: explicit approval for missing Git/Python/venv installation, PATH changes, modified Skill replacement, and downgrade.
- Install hooks/binary replacement: manifest inspection, rejection, HMAC-signed receipt, installed-hash verification, and exact-file rollback.
- Secret exfiltration: fail-closed command classification, approval, redaction, no secret logging, and rejection of symlinked release inputs.
- Workspace escape/destructive writes: strict run-id grammar, resolved-path containment, receipt-bound file rollback, and dirty-state capture.
- Infinite loops: immutable budgets, progress tests, failure fingerprints, replan caps.
- Forged resume state: schema validation, user-local HMAC signature, repository-lineage identity, exact tracked/staged/untracked worktree fingerprint, strict HEAD and dirty-state checks, and lock verification.
- False completion: mandatory acceptance evidence required for `COMPLETE`.
- Runtime self expansion: no runtime self-update, self-rewrite, recursive invocation, or delegated control. Version installation and update are handled by the separate, versioned bootstrap/installer boundary.

## Residual risk

StackMarshal is not an OS sandbox and cannot cryptographically force an LLM host to
follow prose. The checkpoint signing key protects against project-local tampering, not
malware already running as the same operating-system user. Operators should use
least-privilege credentials, protected branches, and isolated execution for high-risk repositories.
