# Threat Model

## Assets

Workspace integrity, existing Git changes, credentials, publication authority,
execution budget, live run/task authority, checkpoint truth, provenance, and acceptance evidence.

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
- Release evidence substitution or path escape: flat expected asset-set enforcement, checksum target containment/symlink/duplicate rejection, manifest artifact hash/size checks, component-version coherence, clean provenance, rejection of hidden Git index flags and ignored artifact-contaminating inputs, safe root-level build-output cleanup, and manifest/provenance binding to the expected immutable Git HEAD.
- Release-version drift: `pyproject.toml` is authoritative; CI/release gates fail closed when Core, Skill, smoke resolution, Skill readiness commands, or living documentation diverge.
- Installer archive escape: regular-file-only Skill extraction, canonical path containment, duplicate rejection, and symlink rejection.
- Interrupted update or repair: staged directory swaps, launcher/state snapshots, rollback before commit, and bounded cleanup after success.
- Silent global mutation: explicit approval for missing Git/Python/venv installation, PATH changes, modified Skill replacement, and downgrade.
- Install hooks/binary replacement: manifest inspection, rejection, HMAC-signed receipt, installed-hash verification, and exact-file rollback.
- Secret exfiltration and helper execution: fail-closed command classification, approval, redaction, no secret logging, rejection of Git global-option/alias injection, and explicit rejection of read options that can execute helpers, write output, or escape repository reads.
- Workspace escape/destructive writes or reads: strict run-id grammar, resolved-path containment, symlink/junction rejection across `.stackmarshal` state and `.gitignore` initialization, containment-aware workspace/terminal fingerprints that reject directory junction traversal before recursion, receipt-bound file rollback, and dirty-state capture.
- Infinite loops or repository-driven policy weakening: project configuration may only tighten bounded budgets and cannot select the deep profile, disable mandatory approvals, or weaken guarded autonomy; larger deep budgets require explicit user CLI selection. Progress tests, failure fingerprints, and replan caps remain enforced by the Core.
- Forged live or resume state: canonical live `run.json` and `task-graph.json`, checkpoints, and acquisition receipts are authenticated with a user-local HMAC key kept outside the repository; unsigned or modified authority is rejected before use. Resume additionally validates repository-lineage identity, exact tracked/staged/untracked worktree fingerprint, strict HEAD and dirty-state checks, and lock verification.
- False completion: mandatory acceptance evidence required for `COMPLETE`, live run/task authority must pass HMAC verification, final verification is bound to a terminal deliverable fingerprint, finalization seals StackMarshal-owned bookkeeping before terminal transition, and post-finalization deliverable/build/release mutations invalidate `COMPLETE`.
- Runtime self expansion: no runtime self-update, self-rewrite, recursive invocation, or delegated control. Version installation and update are handled by the separate, versioned bootstrap/installer boundary.

## Residual risk

StackMarshal is not an OS sandbox and cannot cryptographically force an LLM host to
follow prose. The user-local integrity key protects StackMarshal-owned authority against
project-local tampering, not malware already running as the same operating-system user. Operators should use
least-privilege credentials, protected branches, and isolated execution for high-risk repositories.
