# Output contract

A run ends with exactly one canonical status.

`COMPLETE` requires evidence for every mandatory acceptance criterion and the
relevant build, lint, type, unit, integration, E2E, and security checks. Never
substitute confidence or narrative for evidence.

Every non-complete terminal result states the formal status, precise stop reason,
checkpoint paths, remaining mandatory blocker, one next action, do-not-repeat list,
and resume command. Do not say that StackMarshal guarantees every project will be
finished; it guarantees finite execution and a resumable formal state.
