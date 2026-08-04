# StackMarshal v1.0 Acceptance Report

## Invocation

- PASS: explicit Japanese, English, Simplified Chinese, and `$stackmarshal` triggers.
- PASS: ordinary implementation, explanation, comparison, and README-edit anti-triggers.

## Workflow

- PASS: requirements/acceptance contract in the Skill and traceability matrix.
- PASS: bounded research gate and evidence bundle.
- PASS: capability categories for Skill, MCP, plugin, library, CLI, and reference OSS.
- PASS: weighted candidate scoring, hard disqualifiers, provenance/lock format.
- PASS: architecture-freeze, task-graph, implementation, verification, and formal-stop policies.

## Safety

- PASS: external repository text is explicitly untrusted.
- PASS: install hooks and download-to-shell patterns are detected.
- PASS: global, network, secret, billing, publication, privileged, interpreter, unknown, and destructive actions require approval unless explicitly proven safe.
- PASS: unpinned, unlicensed, excessive-permission, and unreviewable candidates are rejected.
- PASS: workspace escape, run-id traversal, release symlinks, secret logging, self-recursion, and self-modification are prohibited.
- PASS: acquisition receipts, hashes, exact-file rollback, and recursive-deletion rejection are implemented and tested.

## Stop harness and resume

- PASS: research, candidate, tool, replan, task-attempt, failure, stagnation, and scope budgets.
- PASS: safety-first stop priority and terminal status codes.
- PASS: every formal CLI stop creates checkpoint JSON and Markdown.
- PASS: user-local HMAC checkpoint integrity, repository-lineage identity, Git HEAD, dirty state, completed work, and do-not-repeat state.
- PASS: unknown future state/checkpoint schemas are rejected.

## Distribution and quality

- PASS: installable `skills/stackmarshal/` folder and dependency-free fallback.
- PASS: Python package and `stackmarshal` executable with zero runtime dependencies.
- PASS: English primary README and Japanese secondary README.
- PASS: Apache-2.0, SECURITY, CONTRIBUTING, Code of Conduct, RFC process, issue/PR templates.
- PASS: 40 collected tests, Ruff, mypy strict, 95% branch-aware coverage, build, and Twine validation.
- PASS: Linux/macOS/Windows CI matrix and commit-pinned CodeQL workflow.
- PASS: reproducible Skill/source archives, wheel/sdist, SHA256SUMS, SBOM, and provenance.

## Final publication gates

The release is marked COMPLETE only after the Codex Security final report has no unresolved
reportable finding and the public GitHub CI/CodeQL runs plus v1.0.0 Release assets are verified.
