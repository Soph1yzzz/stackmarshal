# Stop policy

Standard observable limits: research rounds 3, broad candidates 12, deep reviews 3,
repository clones 1, acquisition attempts per capability 2, research reentries 1,
architecture replans 2, task attempts 3, same failure repetitions 2, stagnation
cycles 2, scope additions 5, tool calls 120, changed-files soft limit 80.

Every cycle must increase accepted criteria or passing tests, reduce unfinished work,
blockers, or uncertainty, establish a root cause, or select a safe fallback. After
two non-improving cycles, allow one replan; stop after another non-improving cycle.
Normalize command class, error class, target, message, suspected cause, and environment
into a failure fingerprint. Do not repeat a fingerprint at its limit.

Stop priority: safety, cancellation, approval, invalid state, budget, repeated
failure, stagnation, scope drift, external blocker. Flush state, inspect changes,
rollback broken acquisition, create a checkpoint, record one next action and a
do-not-repeat list, then show the resume command.
