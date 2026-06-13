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

This patcher modifies your own existing `TP.exe` and creates a backup before changing anything.

Open **PowerShell** in this repository folder, then run:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

If the game is installed under `Program Files`, run PowerShell as **Administrator**.

That is the normal install path. The patcher will:

* detect whether your `TP.exe` is supported
* apply the level-music fixes if needed
* create a timestamped backup next to `TP.exe`
* verify every changed byte after writing
* print the exact rollback command

It is safe to run again. If the patch is already applied, it will detect that and do nothing.

## Preview without changing anything

To check what would happen before writing to the file:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py --dry-run "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

Use this first if you want to confirm the patcher recognises your executable.


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

## Historical scripts

Earlier development used separate v1, v2, and v3 patchers plus compatibility/testing helpers.

This public release only requires:

- `Patch-TPW-LevelMusic-Combined.py`

The combined patcher is self-contained and supersedes the older per-stage scripts for normal use.

## Troubleshooting

- **"Permission denied"** - run PowerShell as Administrator (needed when
  `TP.exe` is under `Program Files`).
- **"Refusing to patch an unrecognized EXE layout/version"** /
  **"...fingerprint"** - the script doesn't recognize this build of `TP.exe`
  (wrong version, already modified by something else, or corrupted). Run
  `Test-TPW-PatchCompat.py` against it for details. Do not force the patch.
- **"already fully applied... No changes made."** - your `TP.exe` already has
  all three fixes; nothing to do.



Reverse engineering, testing, and patch development by TheAussie, with AI-assisted debugging and documentation.
