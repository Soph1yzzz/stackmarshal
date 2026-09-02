# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |
| < 1.0 | No |

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
**Report a vulnerability** flow in the repository Security tab. Include:

- affected version or commit;
- operating system and Python version;
- minimal reproduction;
- impact and reachable attack path;
- whether secrets, network writes, publication, or privilege are involved;
- any proposed mitigation.

Do not include real credentials or personal data. Use synthetic values and redact
logs. Maintainers will acknowledge a complete report within seven days and will
coordinate remediation and disclosure. This is a best-effort OSS response target,
not a paid support SLA.

## Security boundaries

StackMarshal treats external repository and registry content as untrusted data. A
report is especially relevant when code can bypass explicit invocation, escape the
workspace, traverse a run identifier, reduce immutable budgets, forge HMAC-authenticated
live run/task state or checkpoints, expose secrets through release inputs, execute candidate instructions,
bypass a fail-closed approval class, expand rollback beyond receipt-created files,
accept an unpinned or hash-mismatched artifact, escape installer staging or Skill extraction,
silently install prerequisites/change PATH/overwrite modified Skills/downgrade, leave a partial
update after failure, recurse into uncontrolled capability acquisition, or mark mandatory criteria
complete without evidence.

StackMarshal is not a sandbox. The user-local integrity signing key protects live run state,
canonical task state, checkpoints, and acquisition receipts against repository-local tampering;
it does not protect against malware already executing as the same OS user. The host Codex
environment and operator remain responsible for OS-level isolation, credentials, network
controls, and reviewing publication or privileged actions.

## Release security assurance

Every release must pass the automated quality gates, relevant adversarial security regressions,
a focused source-backed review of changed trust boundaries, CI, and CodeQL. Full Codex Security
repository scans are risk-triggered rather than required for every patch. Changes to installer or
update authority, command/privilege boundaries, integrity/secret handling, path/archive
containment, network/publication/supply-chain behavior, authentication/cryptography, or major
architecture trigger an explicit owner/maintainer decision about the additional full scan and its
model/usage cost. Skipping it never permits an unresolved material security finding; compensating
review evidence must be recorded in the release evidence.
