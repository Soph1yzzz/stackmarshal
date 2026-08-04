# Acquisition policy

Record kind, canonical identifier, source URL, registry, version, commit SHA,
content hash, license, permissions, selection reason, rejected alternatives, and
verification. Inspect manifests and install hooks before execution. Prefer a
temporary directory, virtual environment, Git worktree, then container for PoCs.
Capture files changed, network effects, uninstall behavior, platform support, and a
rollback receipt.

Automatic acquisition is limited to project-local, pinned, reversible changes with
no postinstall, secrets, external binary, elevation, or excessive permission.
Global Skill/MCP/plugin configuration, external binaries, secrets, billing,
publication, deployment, network exposure, administrator privileges, or unknown
licenses require explicit approval. Failed partial acquisition must be rolled back
before checkpointing.
