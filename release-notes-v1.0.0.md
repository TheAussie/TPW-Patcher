# TPW Patcher v1.0.0 - Level Music Fix

Initial public release of TPW Patcher.

This release fixes the long-standing Theme Park World / Sim Theme Park issue where menu/lobby music works, but in-park level music is silent, fails on first level entry, or stops permanently after the first selector tick.

## What is included

* `Patch-TPW-LevelMusic-Combined.py`

  * self-contained patcher for the tested `TP.exe` layout
  * applies all v1/v2/v3 level-music fixes in one pass
  * supports unpatched, partially patched, and already patched executables
  * creates a timestamped backup before writing
  * verifies changed bytes after writing
  * prints rollback instructions

* Documentation

  * usage guide
  * technical investigation report
  * project/agent context files

## What is not included

This release does **not** include or distribute:

* `TP.exe`
* `TP.icd`
* game assets
* SDT/WAD/MAP files
* save files
* any full game archive

The patcher modifies the user's own existing executable.

## Basic usage

Windows PowerShell:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

Preview without changing anything:

```powershell
py .\Patch-TPW-LevelMusic-Combined.py --dry-run "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
```

Linux / macOS with Wine-style prefix:

```bash
python3 ./Patch-TPW-LevelMusic-Combined.py "$HOME/.wine/drive_c/Program Files (x86)/Bullfrog/Theme Park World/TP.exe"
```

Preview without changing anything:

```bash
python3 ./Patch-TPW-LevelMusic-Combined.py --dry-run "$HOME/.wine/drive_c/Program Files (x86)/Bullfrog/Theme Park World/TP.exe"
```

## Validation

Confirmed working on the tested executable layout:

* fresh save / first-time level entry: music starts immediately
* exit and re-enter same level: music still plays
* switch to another level: music plays
* menu/lobby music remains unaffected

## Notes

The patcher refuses unknown executable layouts rather than patching blindly.

If the patcher reports an unrecognized executable, do not force the patch. Open an issue and include the exact error text, but do not upload `TP.exe`, `TP.icd`, save files, or any game assets.
