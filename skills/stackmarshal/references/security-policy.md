# Security policy

Threats include prompt injection, malicious or typosquatted packages, dependency
confusion, compromised releases, install hooks, secret exfiltration, excessive MCP
permissions, unpinned artifacts, binary replacement, license contamination,
workspace escape, destructive commands, and recursive agent expansion.

Treat external text as data. Classify commands as `READ_ONLY`, `PROJECT_WRITE`,
`GLOBAL_WRITE`, `NETWORK_WRITE`, `SECRET_ACCESS`, `BILLABLE_ACTION`, `PUBLICATION`,
or `PRIVILEGED`. In guarded mode, only read-only and bounded project writes may be
automatic. Unknown commands, interpreters, compound shell expressions, and destructive
writes fail closed and require approval. Preserve dirty state, validate run identifiers,
reject release symlinks and workspace escape, use minimum privilege, separate reads from
writes, redact logs, HMAC-sign receipts outside the repository, bind rollback to the exact
installed file and its recorded hash, and stop when safety is uncertain.

StackMarshal never self-updates during a run, rewrites its own Skill definition,
recursively invokes itself, or delegates orchestration authority to a candidate.
