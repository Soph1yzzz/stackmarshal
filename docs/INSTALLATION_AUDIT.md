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

## v1.1.4 pin/version addendum

v1.1.4 turns those diagnostics into the normal update workflow. After the first bootstrap,
`stackmarshal pin latest` or `stackmarshal pin <version>` resolves a published stable Release,
downloads that Release's `SHA256SUMS`, verifies the platform bootstrap itself, and only then
executes the existing installer. Canonical GitHub repository/release-base environment overrides
are removed from the delegated bootstrap so an inherited environment cannot silently redirect the
verified pin to another repository. The atomic installer remains the only implementation of venv,
Skill, rollback, PATH, downgrade, and restart-marker behavior.

`stackmarshal version` and `stackmarshal pin status` compare the running CLI with the installer
state, installed Skill, and PATH-resolved launcher. Older launchers later on PATH remain visible as
shadowed warnings but do not create a false repair blocker when the resolved managed launcher and
authoritative components agree.

## v1.1.5 shadowed-launcher repair addendum

v1.1.5 adds `stackmarshal repair` as the operator-facing convergence command. It re-runs the exact
managed version through the same verified atomic installer rather than creating a second repair
implementation. `stackmarshal repair --remove-shadowed` may additionally remove PATH launchers only
when they are outside the managed root and nearby package metadata or launcher evidence identifies
them as StackMarshal. Unknown or provenance-free executables are skipped and reported, not deleted.
The removal flag is explicit because deleting a launcher outside the managed install is a global
filesystem mutation.

## v1.1.6 Windows self-update cleanup addendum

A real managed v1.1.4 -> v1.1.5 pin update showed that Windows can keep the updater CLI's old
versioned venv `python.exe` open until the parent CLI exits. Authority had already converged to the
new version, but the old managed directory could remain after best-effort cleanup with WinError 5.

v1.1.6 keeps synchronous cleanup as the default. Only Windows sharing/access lock errors are
deferred. A shell-free helper is launched with the newly installed version's Python and retries the
strictly validated old `vMAJOR.MINOR.PATCH` directories for a bounded period after the updater exits.
The helper refuses the current version, validates containment under the managed `versions/` root,
and does not convert unrelated cleanup failures into success. Release acceptance requires a real
Windows managed pin update demonstrating that the old managed version directory disappears.

## Residual limitations

- The one-time first bootstrap script is trusted through HTTPS delivery from the GitHub Release.
  Subsequent `stackmarshal pin` updates additionally verify the selected bootstrap against the
  Release `SHA256SUMS`. Neither path protects against compromise of the GitHub account or Release
  itself.
- Automatic prerequisite installation necessarily changes the operating system and may require
  administrator credentials. It is never attempted without approval unless `--yes` / `-Yes` was
  explicitly supplied.
- The installer supports maintained mainstream package managers. Unknown distributions fail
  safely and require manual installation of Git, Python 3.11+, and venv support.
- Codex must be restarted after Skill installation or update so host-side caches are refreshed.
