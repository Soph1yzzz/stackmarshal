# StackMarshal v1.1.6

StackMarshal v1.1.6 is a focused Windows self-update cleanup hotfix.

## Fixed: old managed version left behind after `pin`

On Windows, `stackmarshal pin <new-version>` runs from the currently installed version's managed venv. While that CLI process is still alive, Windows can keep the old venv's `python.exe` locked. The installer had already switched the authoritative launcher, Skill, pin state, and managed CLI to the new version, but its best-effort old-version cleanup could receive `WinError 5` and leave the previous version directory under `versions/`.

v1.1.6 keeps the atomic update boundary unchanged and changes only cleanup behavior:

1. Old managed versions are removed synchronously as before.
2. Only Windows sharing/access lock failures (`PermissionError`, WinError 5/32) are eligible for deferred cleanup.
3. The installer starts a bounded, shell-free cleanup helper using the **newly installed version's Python**, not the old locked venv.
4. The helper validates strict `vMAJOR.MINOR.PATCH` directory names, refuses the current version, verifies containment under the managed `versions/` directory, and retries for a bounded period after the old CLI exits.
5. Non-lock cleanup failures are not silently deferred; existing fail-closed/visible behavior is preserved.

This removes the stale old-version directory automatically after a successful Windows self-update instead of waiting for another manual repair or later update.

## Verification

The hotfix adds regressions for:

- Windows lock errors being deferred while the same error remains fatal/non-deferred on non-Windows paths,
- the cleanup helper deleting only the requested old version while preserving the current version,
- scheduling the helper with the newly installed venv Python and no shell/stdin/stdout/stderr inheritance,
- existing installer checksum, rollback, downgrade, archive-containment, Skill, and release smoke contracts.

The final release must also demonstrate a real managed Windows `stackmarshal pin 1.1.6` update and verify that only `v1.1.6` remains in the managed versions directory after the updater exits.

## Scope discipline

No state-machine, resume, migration, task, verification, or pin-resolution semantics change in this release. The operator UX / fully non-invasive initialization work previously planned for v1.1.6 moves unchanged to v1.1.7.
