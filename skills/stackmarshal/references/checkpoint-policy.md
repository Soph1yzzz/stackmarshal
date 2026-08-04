# Checkpoint and resume policy

Checkpoint metadata includes run ID, timestamp, project identity, Git HEAD, dirty
snapshot, mode, budget used/remaining, completed phases, current phase, requirements,
acceptance status, capability map, selected/rejected candidates, decisions, tasks,
failures, changed files, tests, stop reason, one next action, do-not-repeat entries,
and resume command.

Resume validates schema and integrity, repository identity, Git HEAD and worktree,
locks, and provenance. Skip completed environment audits, unchanged candidate
research, rejected candidates, failed PoCs, passed tests, and frozen decisions.
Refresh only when commits, dependency versions, requirements, checkpoint freshness,
or security information changed. Unknown future schemas are rejected; v1.x schema
changes require explicit migrations.
