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
workspace, reduce immutable budgets, forge checkpoint integrity, expose secrets,
execute candidate instructions, bypass an approval class, accept an unpinned or
hash-mismatched artifact, recurse into uncontrolled capability acquisition, or mark
mandatory criteria complete without evidence.

StackMarshal is not a sandbox. The host Codex environment and operator remain
responsible for OS-level isolation, credentials, network controls, and reviewing
publication or privileged actions.
