# TP.exe Level Music Patch - Usage Guide

These scripts fix Theme Park World's in-park level music, which on modern
Windows either never plays, or stops permanently after the first tick of a
level. See [TPW-LevelMusic-Investigation.md](TPW-LevelMusic-Investigation.md)
for the full technical writeup of the three underlying bugs (v1/v2/v3).

## Requirements

- Python 3 (any recent 3.x). Run with `py` or `python` from PowerShell.
- A 32-bit `TP.exe` from Theme Park World, unmodified or already partially
  patched by these same scripts.
- If `TP.exe` lives under `C:\Program Files (x86)\...`, run PowerShell **as
  Administrator** so the script can write the patched file back in place.

## TL;DR - just fix my game

From this folder, in PowerShell:

```powershell
py Patch-TPW-LevelMusic-Combined.py "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

That's it. This single script applies all three fixes (v1+v2+v3) in one
pass. It is safe to run on:

- a completely unpatched `TP.exe`
- a `TP.exe` already partially patched (v1-only, or v1+v2) by the older
  per-version scripts below
- an already fully-patched `TP.exe` (it detects this and does nothing)

It always:

- creates a timestamped backup next to `TP.exe` before writing anything
  (e.g. `TP.exe.levelmusic-combined-bak-20260614-024502`)
- verifies every changed byte after writing
- prints exact rollback instructions

### Preview without changing anything

```powershell
py Patch-TPW-LevelMusic-Combined.py --dry-run "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

This prints the full patch plan (old/new bytes, file offsets, target
addresses) without touching the file, and works even on a completely fresh,
unpatched `TP.exe`.

### Rolling back

If anything looks wrong, restore the backup the script created:

```powershell
Copy-Item "TP.exe.levelmusic-combined-bak-20260614-024502" "TP.exe" -Force
```

(Use the exact backup filename printed by the script for that run.)

## Validation checklist (after patching)

1. Start a fresh save, enter a level for the **first time** - level music
   should start immediately, with no need to leave and re-enter.
2. Exit and re-enter the same level - music should still play.
3. Switch to a different level - music should also play there on first
   entry.
4. Menu/lobby music should be unaffected.

## Other scripts in this folder

You generally don't need these - `Patch-TPW-LevelMusic-Combined.py` above
supersedes them for normal use. They're kept for documentation, granular
rollback, and compatibility testing.

- **`Patch-TPW-LevelMusic.py`** (v1), **`Patch-TPW-LevelMusic-v2.py`** (v2),
  **`Patch-TPW-LevelMusic-v3.py`** (v3) - the original per-bug patchers.
  Each supports `--dry-run`, refuses to run unless its prerequisite patch is
  present, and is individually idempotent/rollback-able. Running v1, then
  v2, then v3 against a fresh `TP.exe` produces a byte-identical result to
  `Patch-TPW-LevelMusic-Combined.py`.

- **`Patch-TPW-LevelMusic-All.py`** - an orchestrator that inspects `TP.exe`,
  figures out which of v1/v2/v3 are already applied, and runs only the
  remaining ones in order (or reports "Already fully patched" if v3 is
  already present). Supports `--dry-run`.

  ```powershell
  py Patch-TPW-LevelMusic-All.py --dry-run "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
  py Patch-TPW-LevelMusic-All.py "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
  ```

- **`Test-TPW-PatchCompat.py`** - read-only scanner for checking a `TP.exe`
  from a *different* distribution/build before patching it. Confirms whether
  it matches the byte signatures all the patchers rely on, without modifying
  anything:

  ```powershell
  py Test-TPW-PatchCompat.py "D:\path\to\some-other-build\TP.exe"
  ```

  Exit code `0` means v1/v2/v3 (or the combined patcher) should apply cleanly
  to an unpatched copy of that file.

## Troubleshooting

- **"Permission denied"** - run PowerShell as Administrator (needed when
  `TP.exe` is under `Program Files`).
- **"Refusing to patch an unrecognized EXE layout/version"** /
  **"...fingerprint"** - the script doesn't recognize this build of `TP.exe`
  (wrong version, already modified by something else, or corrupted). Run
  `Test-TPW-PatchCompat.py` against it for details. Do not force the patch.
- **"already fully applied... No changes made."** - your `TP.exe` already has
  all three fixes; nothing to do.
