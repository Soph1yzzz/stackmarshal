# Threat Model

## Assets

Workspace integrity, existing Git changes, credentials, publication authority,
execution budget, live run/task authority, checkpoint truth, HostWrite pending/recovery authority,
workspace-relocation identity, provenance, and acceptance evidence.

## Trust boundaries

User instructions are authoritative within host policy. Local project instructions
are trusted only for their repository scope. External README/Issue/SKILL/registry
metadata are untrusted data. Package scripts and binaries cross an execution boundary.
Global configuration, secrets, billing, privilege, network writes, publication, prerequisite
installation, user PATH changes, replacement of modified Skills, and host-mediated project mutation
cross explicit approval/trust boundaries.

## Principal threats and controls

- Prompt injection: evidence-only handling and no candidate orchestration authority.
- Malicious/typosquatted dependency: canonical source, score, license, pin, hash, PoC.
- Installer/bootstrap substitution: versioned GitHub Release URLs, strict SHA256SUMS parsing, `stackmarshal pin` verification of the selected bootstrap itself, verified shared installer and payloads, canonical GitHub pin targets with inherited repository/release-base overrides removed, dedicated venv, `--no-index --no-deps`, and post-install doctor.
- Release evidence substitution or path escape: flat expected asset-set enforcement, checksum target containment/symlink/duplicate rejection, manifest artifact hash/size checks, component-version coherence, clean provenance, rejection of hidden Git index flags and ignored artifact-contaminating inputs, safe root-level build-output cleanup, and manifest/provenance binding to the expected immutable Git HEAD.
- Release-version drift: `pyproject.toml` is authoritative; CI/release gates fail closed when Core, Skill, smoke resolution, Skill readiness commands, or living documentation diverge.
- Installer archive escape: regular-file-only Skill extraction, canonical path containment, duplicate rejection, and symlink rejection.
- Interrupted update or repair: staged directory swaps, launcher/state snapshots, rollback before commit, and bounded cleanup after success.
- Silent global mutation: explicit approval for missing Git/Python/venv installation, PATH changes, modified Skill replacement, and downgrade; shadowed launcher removal is a separate explicit `repair --remove-shadowed` action and only deletes launchers with high-confidence StackMarshal package evidence.
- Install hooks/binary replacement: manifest inspection, rejection, HMAC-signed receipt, installed-hash verification, and exact-file rollback.
- Secret exfiltration and helper execution: fail-closed command classification, approval, redaction, no secret logging, rejection of Git global-option/alias injection, and explicit rejection of read options that can execute helpers, write output, or escape repository reads.
- Workspace escape/destructive writes or reads: strict run-id grammar, resolved-path containment, symlink/junction rejection across `.stackmarshal` state and `.gitignore` initialization, preexisting Git-ignore detection before mutating `.gitignore`, containment-aware workspace/terminal fingerprints that reject directory junction traversal before recursion, receipt-bound file rollback, dirty-state capture, canonical relative-path validation for host-write plans, and content-addressed recovery blobs kept outside the workspace.
- Infinite loops or repository-driven policy weakening: project configuration may only tighten bounded budgets and cannot select the deep profile, disable mandatory approvals, or weaken guarded autonomy; larger deep budgets require explicit user CLI selection. Progress tests, failure fingerprints, and replan caps remain enforced by the Core. Late task admission requires `REPLAN` and consumes both replan and scope-addition budget; host telemetry can only advance a named monotonic counter and charges its positive delta.
- Forged live, resume, or host-write authority: canonical live `run.json` and `task-graph.json`, checkpoints, acquisition receipts, and host-write plans/receipts are authenticated with a user-local HMAC key kept outside the repository; unsigned or modified authority is rejected before use. Host-write application is bound to expected preimage SHA-256 and acknowledged only after required postimage SHA-256 verification. Growing append operations carry signed whole-file SHA/size plus a bounded tail and append delta; the full recovery preimage is addressed by that same SHA outside the repository. A pending plan blocks all project-mutating commands in both transports, and its slot is created with exclusive filesystem semantics so a concurrent producer cannot replace it. Legacy unsigned state is archived byte-for-byte with SHA-256 evidence instead of being signed into authority. Resume additionally validates checkpoint HMAC, run id, repository-lineage identity, exact Git or non-Git worktree fingerprint, strict HEAD/dirty state, and the signed resume phase before reopening only explicitly resumable statuses.
- Relocation spoofing/identity laundering: workspace moves require a signed permit created before the move and are accepted only when the destination path, terminal deliverable fingerprint, portable repository identity, Git HEAD, dirty state, run id, and source identity still match. Signed checkpoints are migrated under the same proof; relocation and repository bootstrap remain distinct events.
- False completion: mandatory acceptance evidence required for `COMPLETE`, live run/task authority must pass HMAC verification, final verification is bound to a terminal deliverable fingerprint, finalization seals StackMarshal-owned bookkeeping before terminal transition, and post-finalization deliverable/build/release mutations invalidate `COMPLETE`.
- Launcher alias confusion: Windows installs keep the authoritative managed `.cmd` launcher and may add an extensionless shell shim only in the same managed `bin` directory. Doctor inventories both without treating co-located aliases as distinct installations; launchers in other directories remain shadowed-version evidence.
- Runtime self expansion: no implicit self-update during a StackMarshal workflow, self-rewrite, recursive invocation, or delegated control. Explicit operator `stackmarshal pin` is a separate version-management command that verifies a published Release bootstrap and delegates installation/update to the versioned installer boundary.
- Adaptive workflow trust: quick-explore may skip research ceremony but never final acceptance or user approval. Only specifically identified exploration counters can exceed a soft threshold with a durable reason; hard resources, scope and repetition controls stay enforced. Release-audit hashes actual evidence files and detects later changes.
- Git bootstrap and evidence laundering: workspace ownership is checked before `git init`; an ancestor repository is not silently captured, and nested repositories require an explicit action. No automatic `git add` or first commit is issued. Reconciliation observes signed state and checkpoint drift without changing phase, task completion or HMAC authority; amended tasks keep old evidence only as history.

## Residual risk

StackMarshal is not an OS sandbox and cannot cryptographically force an LLM host to
follow prose. The user-local integrity key protects StackMarshal-owned authority against
project-local tampering, not malware already running as the same operating-system user. Operators should use
least-privilege credentials, protected branches, and isolated execution for high-risk repositories.
