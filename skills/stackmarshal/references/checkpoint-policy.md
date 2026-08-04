# Checkpoint and resume policy

Checkpoint metadata includes run ID, timestamp, project identity, Git HEAD, dirty
snapshot, mode, budget used/remaining, completed phases, current phase, requirements,
acceptance status, capability map, selected/rejected candidates, decisions, tasks,
failures, changed files, tests, stop reason, one next action, do-not-repeat entries,
and resume command.

Resume validates schema, the user-local HMAC signature, repository-lineage identity,
Git HEAD, dirty state, and the exact tracked/staged/untracked worktree fingerprint, plus
locks and provenance. The signing key is stored outside the repository; missing, replaced,
or mismatched keys cause a hard rejection. Skip completed
environment audits, unchanged candidate
research, rejected candidates, failed PoCs, passed tests, and frozen decisions.
Refresh only when commits, dependency versions, requirements, checkpoint freshness,
or security information changed. Unknown future schemas are rejected; v1.x schema
changes require explicit migrations.
