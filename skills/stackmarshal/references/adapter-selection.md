# Adapter selection

StackMarshal Core is agent-neutral. For v1, use the Codex adapter to inspect the
host environment and expose deterministic state operations. Prefer an authenticated
GitHub plugin when available, then `gh`, then read-only web search. Prefer installed
local Skills and plugins over acquisition. Registry adapters must use official APIs
or metadata endpoints and must not execute package content during discovery.

An unavailable adapter is a capability-map fact, not permission to bypass safety.
Fallbacks must preserve source pinning, bounded queries, provenance, approval gates,
and rollback. Agent task execution remains with the host Codex process; Core never
executes arbitrary instructions copied from candidates.
