# TPW Patcher - Always-Read Claude Context

## Project

TPW Patcher is a preservation/compatibility patch project for **Theme Park World / Sim Theme Park**.

Primary current goal:

- Fix the long-standing bug where **menu/lobby music works but in-park level music is silent**.
- Provide a public-safe patcher that modifies the user's own legally-owned `TP.exe`.
- Do **not** distribute `TP.exe`, `TP.icd`, SDT/WAD files, save files, or any game assets.

Current core artifacts:

- `Patch-TPW-LevelMusic-Combined.py` — final combined v1+v2+v3 patcher.
- `Patch-TPW-LevelMusic-README.md` — user-facing usage instructions.
- `TPW-LevelMusic-Investigation.md` — technical investigation report.
- Optional future: GUI frontend/wrapper for normal users.

## Developer Context

- The human developer is doing hands-on testing, game validation, listening checks, screenshots/log captures, and release decisions.
- Treat the human tester as the source of truth for whether the fix actually works in-game.
- Explain risky changes in plain English before editing.
- Keep work scoped, incremental, and reversible.
- Do not assume a broad rewrite is wanted.
- Prefer exact paths, exact commands, and explicit validation steps.
- Avoid dumping giant summaries into chat; write summary files instead.

## Current Status

The level-music bug has been resolved locally with a permanent static patch to `TP.exe`.

The combined patcher should apply all fixes in one pass:

- v1: save/park sound-state restore clobber fix.
- v2: per-tick selector zero-handle overwrite fix.
- v3: first-time level-entry delayed re-prime fix.

The patch was validated by:

- Ghidra analysis.
- Frida runtime tracing.
- Frida runtime fix tests.
- Static binary patch testing.
- Fresh first-entry in-game listening validation.
- Re-entry and level-switch validation.

## Core Technical Summary

The bug centers on global `DAT_00803AA0`, the level-music object/request handle.

Important addresses for the tested executable layout:

| Symbol / Function | Address | Role |
|---|---:|---|
| `DAT_00803AA0` | `0x00803AA0` | Level-music object/request handle |
| `DAT_00803A44` | `0x00803A44` | `cat_music` category handle |
| `FUN_0051E730` | `0x0051E730` | Level music startup / object creation |
| `FUN_0051E790` | `0x0051E790` | Per-tick track selector |
| `FUN_0051BC40` | `0x0051BC40` | Sound command dispatcher |
| `FUN_0051C400` | `0x0051C400` | Save/park sound-state restore/load |
| v1 callsite | `0x00415BA2` | Direct call to `FUN_0051C400` |
| `FUN_0051E730` return hook site | `0x0051E764` | v3 delayed re-prime flag hook |

### v1 root cause

`FUN_0051C400` deserializes stale saved sound-state into `DAT_00803AA0` immediately after `FUN_0051E730` creates a valid level-music object.

Fix:

- Redirect the `FUN_0051C400` callsite through a `.fix` trampoline.
- Run original `FUN_0051C400` unchanged.
- Preserve `EAX`.
- Re-run `FUN_0051E730` afterward.

### v2 root cause

`FUN_0051E790` originally did the equivalent of:

```c
DAT_00803AA0 = FUN_0051BC40(DAT_00803AA0, 4, iVar5);
```

If `FUN_0051BC40` returned `0` while the old handle was still valid, the original code destroyed the still-valid handle.

Fix:

- Redirect `FUN_0051E790` to a stub that preserves the old handle when the result is `0` and the old handle was nonzero.

### v3 root cause

On first-time entry into a never-visited level, `FUN_0051E730` can create the music object **before** the level's real `\music\MusicHD.sdt` has been opened/registered by the asset loader.

That object may appear valid and the immediate first `FUN_0051BC40(obj,4,0)` can succeed, but later selector ticks fail permanently.

Fix:

- Hook `FUN_0051E730` return to arm a one-tick delayed re-prime flag.
- On the next `FUN_0051E790` tick, consume the flag and call `FUN_0051E730` once.
- Use a suppress flag so the re-prime call does not re-arm itself forever.
- Then run the v2-preserve-handle selector logic.

## Combined Patcher Direction

The preferred release patcher is:

```text
Patch-TPW-LevelMusic-Combined.py
```

It should be self-contained. It must not require running separate v1/v2/v3 scripts.

Required supported input states:

| Current `TP.exe` state | Expected behavior |
|---|---|
| True original | Apply v1 + v2 + v3 |
| v1 only | Apply/finish v2 + v3 |
| v1 + v2 | Apply/finish v3 |
| Fully patched | Report already applied and exit cleanly |
| Unknown/weird layout | Refuse safely |

## Binary Patcher Safety Rules

For any patcher changes, preserve or improve these safety features:

- `--dry-run` support.
- Fingerprint/expected-byte checks.
- Clear original/v1/v2/v3/final state detection.
- Refuse unknown EXE layouts.
- Create a timestamped backup before writing.
- Never modify game assets, saves, SDT/WAD files, or `TP.icd`.
- Verify every changed byte after writing.
- Print exact VAs, file offsets, old bytes, new bytes, and stub locations.
- Print rollback instructions.
- Be idempotent: already-patched files should report cleanly, not double-patch.
- Do not silently overwrite unexpected bytes or unknown `.fix` layouts.
- Do not distribute patched game binaries.

## Public Release Safety

Public releases may include:

- Patch scripts.
- README files.
- Investigation reports.
- Optional trace scripts/tools.
- Safe sample logs if they contain no private data or game assets.

Public releases must not include:

- `TP.exe`.
- `TP.icd`.
- Patched executables.
- Original executables.
- SDT/WAD files.
- Game assets.
- Save files unless explicitly sanitized and legally safe.
- Any copied game data.

Use wording like:

```text
This tool patches your own legally-owned TP.exe in place. It does not include or distribute any game files.
```

Avoid claiming the patch supports every version/release. Use:

```text
Supports the tested executable layout. Unknown byte layouts are refused safely.
```

## Documentation Rules

Public docs should be clear for normal users first, then technical users.

Preferred report structure:

1. Status / supported scope.
2. User-facing summary.
3. What this fixes.
4. What is not included.
5. Quick v1/v2/v3 technical summary.
6. Root-cause timeline.
7. Evidence and validation.
8. Patch implementation overview.
9. Patcher safety features.
10. Rollback.
11. Technical appendix.
12. Credits / investigation notes.

Important clarity issue:

- Early investigation notes may say `MusicHD.sdt` was never opened.
- Final public docs must explain the nuance:
  - Before v1/v2, the clobbered handle prevented usable level-music playback from progressing correctly.
  - After v1/v2, first-time entry does open real `\music\MusicHD.sdt`, but too late for the already-created music object.
  - v3 re-creates the object one tick later.

## GUI Frontend Direction

A GUI frontend is a later/future task.

It should be a thin wrapper around the existing patcher logic, not a second patch implementation.

Suggested GUI features:

- Select `TP.exe`.
- Run compatibility check / dry run.
- Apply patch.
- Show detected patch state.
- Show backup path and rollback command.
- Show clear legal-safe note that no game files are included.
- Open README/report.

Do not build a GUI until the CLI patcher and docs are stable.

## Agent Workflow

When working in this project:

1. Read this file first.
2. Read the current task prompt carefully.
3. Inspect relevant files before editing.
4. Explain the intended change briefly before major/risky edits.
5. Make the smallest safe change.
6. Preserve safety checks and rollback behavior.
7. Validate with dry-run and, if safe, real run on a copied executable first.
8. Write a Markdown summary file.
9. Respond briefly in chat and point to the summary file.

Do not dump long summaries into chat.

Use summary files:

- Claude Code: `claude-summary.md`
- Codex: `codex-summary.md`
- Gemini CLI: `gemini-summary.md`

Summary file must include:

- Exact files changed.
- What changed.
- Why it works.
- Validation commands run.
- Validation results.
- Manual checks still needed.
- Known compromises.
- Suggested next scoped task.

## Validation Expectations

For patcher/docs work, typical validation includes:

```powershell
py -3.12 .\Patch-TPW-LevelMusic-Combined.py .\TP.exe --dry-run
```

On a copied executable in a writable temp folder:

```powershell
Copy-Item "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe" "$env:TEMP\TPW-Patcher-Test\TP.exe" -Force
py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$env:TEMP\TPW-Patcher-Test\TP.exe" --dry-run
py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$env:TEMP\TPW-Patcher-Test\TP.exe"
py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$env:TEMP\TPW-Patcher-Test\TP.exe" --dry-run
```

Expected:

- Dry-run prints plan and writes nothing.
- Apply creates backup and verifies changes.
- Second run reports already applied cleanly.

Manual in-game validation:

- Fresh first-time level entry plays music immediately.
- Exit/re-enter same level plays music.
- Switch to a different level and music plays.
- Menu/lobby music still works.
- No stuck/overlapping music when returning to menu/hub.

## Source Control Safety

- The worktree may contain user changes.
- Do not revert user changes.
- Do not clean unrelated dirty files.
- Do not commit unless explicitly asked.
- Never commit game binaries or assets.
- Never commit generated backups or patched executables.
- Keep public release bundles game-file-free.

Before committing, check:

```bash
git status --short
git diff --stat
git diff
```

## Destructive Command Safety

Never delete or modify the user's real game install unless the task explicitly asks for it.

Prefer copied executables in temp folders for testing.

Never run broad deletion commands against:

- the Theme Park World install directory
- save directories
- game asset directories
- backup folders

## Known Later Ideas

Do not implement these unless explicitly requested:

- GUI frontend.
- Release packaging.
- GitHub Actions.
- EXE bundling with PyInstaller.
- Auto-detect installed TPW path from registry.
- Linux/Wine-specific launcher helpers.
- Compatibility scanner for many executable versions.
- Patch support for alternate EXE builds.
- Installer/uninstaller.
- Website/release page.

## Philosophy

Keep the project boring, safe, and reversible.

```text
ChatGPT = prompt architect / sanity checker
Claude/Codex/Gemini = implementation agent
Human = in-game QA and final release decision
Markdown files = context diet
```

Small clean passes beat giant cursed rewrites.

Do not turn the Theme Park Goblin into Patch Furnace Deluxe Edition in one pass.
