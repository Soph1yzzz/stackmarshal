# Contributing to StackMarshal

Thank you for helping improve bounded, safe agent workflows.

## Before opening a change

1. Search existing issues and discussions.
2. For architectural or schema changes, open an RFC first.
3. Keep v1 Core agent-neutral; place Codex-specific behavior in adapters or the Skill.
4. Never remove or silently increase stop limits to make a scenario pass.
5. Add tests for every state transition, stop condition, security boundary, and migration.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX: source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check src tests
mypy src/stackmarshal
coverage run -m pytest
coverage report --fail-under=85
python -m build
python -m twine check dist/*
```

## Pull requests

A pull request should contain one coherent change, explain the user-visible behavior,
list security and compatibility implications, update traceability or schemas when
needed, and include evidence from all relevant tests. Generated artifacts should not
be committed unless the release process explicitly requires them.

Do not place secrets, private repository content, personal paths, or unlicensed
third-party code in tests or documentation. External samples must be treated as
untrusted data and minimized.

## Commit style

Use clear imperative subjects, for example:

```text
Add checkpoint integrity validation
Reject postinstall hooks during candidate inspection
Document Windows resume behavior
```

## Release changes

Versioning follows Semantic Versioning. Breaking schema changes require a major
version or an explicit migration path. Release pull requests update `CHANGELOG.md`,
the acceptance matrix, security evidence, SBOM/provenance, and checksums.
