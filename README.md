# TP.exe Level Music Patch - Usage Guide

These scripts fix Theme Park World's in-park level music, which on modern
Windows either never plays, or stops permanently after the first tick of a
level. See [TPW-LevelMusic-Investigation.md](docs/TPW-LevelMusic-Investigation.md)
for the full technical writeup of the three underlying bugs (v1/v2/v3).

## Requirements

* Python 3.
* A supported 32-bit `TP.exe` from Theme Park World / Sim Theme Park.
* Your own installed copy of the game.

This project does **not** include or distribute `TP.exe`, `TP.icd`, or any game assets.

The patcher is safe to run on:

* a completely unpatched `TP.exe`
* a `TP.exe` already partially patched by the older v1/v2 scripts
* an already fully patched `TP.exe`

If the patch is already applied, the script will detect that and do nothing.

## TL;DR - just fix my game

The patcher modifies your existing `TP.exe` and creates a timestamped backup before writing anything.

### Windows PowerShell

From this repository folder:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

If the game is installed under `Program Files`, run PowerShell as **Administrator**.

Preview without changing anything:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py --dry-run "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

### Linux / macOS terminal

If you are running the Windows version of the game through Wine or a Wine-style wrapper, patch the `TP.exe` inside that prefix/bottle.

Example default Wine path:

```bash
python3 ./Patch-TPW-LevelMusic-Combined.py "$HOME/.wine/drive_c/Program Files (x86)/Bullfrog/Theme Park World/TP.exe"
```

Preview without changing anything:

```bash
python3 ./Patch-TPW-LevelMusic-Combined.py --dry-run "$HOME/.wine/drive_c/Program Files (x86)/Bullfrog/Theme Park World/TP.exe"
```

For custom Wine prefixes, CrossOver bottles, Whisky bottles, Porting Kit installs, or other wrappers, replace the path with the actual location of your `TP.exe`.

## What the patcher does

The combined patcher applies all three level-music fixes in one pass.

It will:

* detect whether your `TP.exe` is supported
* apply the fixes only if needed
* create a timestamped backup next to `TP.exe`
* verify every changed byte after writing
* print the exact rollback command for your backup

## Rolling back

Use the exact backup filename printed by the script for your run.

### Windows PowerShell

From the game folder:

```powershell
Copy-Item "TP.exe.levelmusic-combined-bak-20260614-024502" "TP.exe" -Force
```

### Linux / macOS terminal

From the game folder:

```bash
cp -f "TP.exe.levelmusic-combined-bak-20260614-024502" "TP.exe"
```

Example Wine path:

```bash
cd "$HOME/.wine/drive_c/Program Files (x86)/Bullfrog/Theme Park World"
cp -f "TP.exe.levelmusic-combined-bak-20260614-024502" "TP.exe"
```

Wrapper paths vary. Find the folder containing `TP.exe`, then restore the backup over it.


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
