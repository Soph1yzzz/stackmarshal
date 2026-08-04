# StackMarshal v1.1.0

StackMarshal v1.1.0 adds a safe, version-aware one-command installation and update path for the
isolated CLI and the matching Codex Skill.

## Recommended installation

Windows PowerShell:

```powershell
irm https://github.com/Soph1yzzz/stackmarshal/releases/latest/download/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://github.com/Soph1yzzz/stackmarshal/releases/latest/download/install.sh | bash
```

Run the same command again to update to the latest stable release or repair the current version.
Use `-Version v1.1.0` on PowerShell or `--version v1.1.0` on Bash for a pinned installation.

## Installer safety and behavior

- Detects Git, Python 3.11+, and Python venv support before installation.
- Asks before installing a missing prerequisite, changing the user PATH, replacing a modified or
  unmanaged Skill, or downgrading.
- Resolves only stable semantic-version tags by default.
- Downloads versioned Release assets and verifies the shared installer, wheel, and Skill archive
  against strict `SHA256SUMS` entries.
- Installs the CLI into a dedicated managed virtual environment with `--no-index --no-deps`.
- Safely extracts the Skill with traversal, duplicate, symlink, and non-regular-file rejection.
- Uses staged directory swaps and restores previous managed content if installation fails before
  the state commit.
- Preserves a modified Skill in a managed backup when replacement is approved.
- Runs post-install doctor checks for CLI version, Skill hash, installer state, and cleanup.
- Supports full installation, CLI-only, Skill-only, repair, update, explicit downgrade, and
  no-PATH modes.

## Verification

- 61 automated tests collected locally: 59 passed and two Windows symlink cases were skipped only
  because the local account lacks symlink privilege; the corresponding paths are exercised on
  Linux.
- Ruff and mypy strict pass.
- Branch-aware Core coverage remains 94%.
- Windows PowerShell and Ubuntu/WSL fresh-install experiments passed using isolated paths.
- A modified Skill repair preserved the user change in backup and restored verified active
  content.
- Checksum mismatch and downgrade attempts fail closed and remove temporary staging.
- CI builds complete Release assets and runs a fresh bootstrap smoke test on Windows, macOS, and
  Ubuntu at Python 3.11, in addition to the 3 OS × 3 Python test matrix.

See `docs/INSTALLATION_AUDIT.md`, `docs/THREAT_MODEL.md`, and `SECURITY.md` for details.
