# Checkpoint and resume policy

Checkpoint metadata includes run ID, timestamp, project identity, Git HEAD, dirty
snapshot, mode, budget used/remaining, completed phases, current phase, signed resume phase, requirements,
acceptance status, capability map, selected/rejected candidates, decisions, tasks,
failures, changed files, tests, stop reason, one next action, do-not-repeat entries,
and resume command.

Resume is an explicit operator action: `stackmarshal resume <run-id>`. It validates schema, the
user-local HMAC signature, run id, repository-lineage identity, Git HEAD, dirty state, and the exact
Git tracked/staged/untracked or non-Git workspace fingerprint before restoring the signed resume
phase. Only `CHECKPOINT_READY`, `BLOCKED_EXTERNAL`, `VERIFICATION_EXTERNAL_BLOCKED`, and
`APPROVAL_REQUIRED` may reopen; unsafe/exhausted/stagnated/repeated-failure/scope-drift/invalid/
cancelled/complete states remain terminal. The signing key is stored outside the repository;
missing, replaced, or mismatched keys cause a hard rejection. Skip completed environment audits, unchanged candidate
research, rejected candidates, failed PoCs, passed tests, and frozen decisions.
Refresh only when commits, dependency versions, requirements, checkpoint freshness,
or security information changed. Unknown future schemas are rejected. Legacy unsigned v1 state is
archived with `stackmarshal migrate` without being promoted into signed authority; future schema
changes require similarly explicit migration rules.
