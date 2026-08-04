# Threat Model

## Assets

Workspace integrity, existing Git changes, credentials, publication authority,
execution budget, checkpoint truth, provenance, and acceptance evidence.

## Trust boundaries

User instructions are authoritative within host policy. Local project instructions
are trusted only for their repository scope. External README/Issue/SKILL/registry
metadata are untrusted data. Package scripts and binaries cross an execution boundary.
Global configuration, secrets, billing, privilege, network writes, and publication
cross explicit approval boundaries.

## Principal threats and controls

- Prompt injection: evidence-only handling and no candidate orchestration authority.
- Malicious/typosquatted dependency: canonical source, score, license, pin, hash, PoC.
- Install hooks/binary replacement: manifest inspection, rejection, receipt, rollback.
- Secret exfiltration: fail-closed command classification, approval, redaction, no secret logging, and rejection of symlinked release inputs.
- Workspace escape/destructive writes: strict run-id grammar, resolved-path containment, receipt-bound file rollback, and dirty-state capture.
- Infinite loops: immutable budgets, progress tests, failure fingerprints, replan caps.
- Forged resume state: schema validation, user-local HMAC signature, repository-lineage identity, HEAD, dirty-state, and lock checks.
- False completion: mandatory acceptance evidence required for `COMPLETE`.
- Self expansion: no self-update, self-rewrite, recursive invocation, or delegated control.

## Residual risk

StackMarshal is not an OS sandbox and cannot cryptographically force an LLM host to
follow prose. The checkpoint signing key protects against project-local tampering, not
malware already running as the same operating-system user. Operators should use
least-privilege credentials, protected branches, and isolated execution for high-risk repositories.
