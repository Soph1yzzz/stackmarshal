# Installation and Update Audit

## Scope

StackMarshal v1.1.0 adds a one-command installation path for the isolated CLI and the matching
Codex Skill. The audit treats installation as a privileged supply-chain boundary rather than a
convenience-only shell script.

The public bootstrap scripts are intentionally small. They detect Git, Python 3.11 or newer,
and Python virtual-environment support; ask before installing a missing prerequisite; resolve a
stable version; download the versioned `SHA256SUMS` and shared `installer.py`; verify the shared
installer; and then delegate to the same Python implementation on every platform.

## Managed layout

The installer does not use the active or global Python environment.

```text
Windows: %LOCALAPPDATA%\StackMarshal
POSIX:   ${XDG_DATA_HOME:-~/.local/share}/stackmarshal

<managed-root>/
├── bin/                         launcher only
├── versions/v<version>/venv/    isolated CLI
├── backups/                     at most one modified Skill backup
└── install-state.json           installed version, hashes, and paths
```

The Skill is installed under `${CODEX_HOME:-~/.codex}/skills/stackmarshal`. CLI and Skill
versions are recorded separately and must match after a full installation.

## Safety properties verified

- Git and Python are detected before acquisition; missing prerequisites require an explicit
  prompt unless the operator deliberately uses `--yes` / `-Yes`.
- Windows uses `winget` only after approval. Linux and macOS use a supported package manager only
  after approval. Unsupported environments fail with an actionable message.
- Debian/Ubuntu's separately packaged `pythonX.Y-venv` condition is detected before the actual
  installation and can be repaired after approval.
- Every downloaded payload is tied to a versioned GitHub Release and verified against the
  release's strict, duplicate-rejecting `SHA256SUMS` parser.
- Wheel installation uses `--no-index --no-deps` inside a newly created dedicated virtual
  environment. StackMarshal has zero required runtime dependencies.
- Skill ZIP extraction rejects absolute paths, `..`, backslashes, duplicate entries, symlinks,
  and non-regular files.
- CLI and Skill directory replacement is staged and atomic. A failure before the state commit
  restores the previous launcher, CLI version, Skill, and installer state.
- A changed or installer-unmanaged Skill is never silently overwritten. With approval, it is
  backed up before replacement; only the newest managed backup is retained.
- Same-version execution is a repair. A newer version is an update. Downgrades fail closed unless
  `--allow-downgrade` / `-AllowDowngrade` is explicit.
- PATH changes are user-scoped and separately approved. `--no-path` / `-NoPath` keeps tests and
  controlled deployments fully isolated.
- A post-install doctor verifies the CLI version, Skill tree hash, persisted state, and temporary
  staging cleanup.

## Fresh-install experiments

All local installation targets were placed under ignored `.stackmarshal/runs/installer-lab-*`
directories and were excluded from Git and release archives.

### Windows 11

- Built a local v1.1.0 Release fixture and served it over a loopback HTTP endpoint.
- Installed through the PowerShell bootstrap into paths containing spaces.
- Verified the dedicated venv, `stackmarshal.cmd`, CLI version `1.1.0`, matching Skill, hashes,
  state, doctor result, and staging cleanup.
- Re-ran the same version as a repair.
- Verified the CI-compatible `scripts/smoke_installer.py` flow.
- Detected and fixed a real Windows native-argument quoting bug in Python discovery.

### Ubuntu under WSL

- Reproduced Python 3.12 without the separately packaged `python3.12-venv` component.
- Verified that the bootstrap detects the missing capability and, after explicit approval,
  installs the exact venv support package.
- Repeated installation as a normal, non-root user after prerequisite repair.
- Verified the POSIX launcher, CLI/Skill version agreement, state, hashes, and staging cleanup.
- Modified the installed Skill, re-ran repair, and verified that the modification was preserved in
  the managed backup while the active Skill returned to the verified release content.
- Purged the three experiment-only packages that were absent before the test:
  `python3.12-venv`, `python3-pip-whl`, and `python3-setuptools-whl`.

The package-manager operation also applied available security updates to already installed Python
3.12 system packages. Those used packages were not downgraded to older vulnerable revisions.

## Adversarial and failure tests

Automated tests cover malformed and duplicate checksums, checksum mismatch, downgrade refusal,
ZIP traversal and symlink attempts, directory-swap rollback/finalization, modified Skill backup,
bootstrap prerequisite/verification contracts, and cleanup after a failed acquisition. Windows
symlink cases that require an unavailable local privilege are repeated under Linux.

The CI matrix runs the complete suite on Windows, macOS, and Ubuntu with Python 3.11, 3.12, and
3.13. On Python 3.11 for each OS, CI also builds the complete Release asset set and performs a
fresh one-command bootstrap smoke test against a temporary local Release server.

## v1.1.3 runtime provenance addendum

MandateMarshal field dogfooding exposed a separate post-install risk: more than one StackMarshal
launcher/package/Skill version can coexist on a development machine even when each individual
installation path is internally valid.

v1.1.3 therefore expands `stackmarshal doctor` beyond the original CLI/Skill readiness comparison.
It now inventories the active CLI entrypoint, managed installer state, PATH-resolved command,
additional StackMarshal launcher candidates, and nearby installed-distribution version metadata.
Known disagreement is reported as `version_skew` and requires repair before doctor returns ready.

The inventory is deliberately non-executing for sibling PATH candidates. StackMarshal does not run
an arbitrary executable merely because it is named `stackmarshal`; version evidence is derived
from the current invocation, installer-managed launcher text/state, and bounded package metadata
inspection. This keeps doctor from widening the supply-chain trust boundary while diagnosing it.

## Residual limitations

- The first bootstrap script is trusted through HTTPS delivery from the GitHub Release. It then
  verifies the shared installer and every payload; this does not protect against compromise of the
  GitHub account or Release itself.
- Automatic prerequisite installation necessarily changes the operating system and may require
  administrator credentials. It is never attempted without approval unless `--yes` / `-Yes` was
  explicitly supplied.
- The installer supports maintained mainstream package managers. Unknown distributions fail
  safely and require manual installation of Git, Python 3.11+, and venv support.
- Codex must be restarted after Skill installation or update so host-side caches are refreshed.
