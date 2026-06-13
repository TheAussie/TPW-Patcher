# TPW Patcher - Agent Instructions

## Purpose

This repository/project contains tooling and documentation for fixing the in-park level music bug in **Theme Park World / Sim Theme Park**.

The project goal is to provide a safe, public-friendly patcher that modifies the user's own `TP.exe` and does not distribute any game files.

Agents must keep work scoped, auditable, and reversible.

## Always Read First

Before editing, read:

1. `AGENTS.md` / this file.
2. `CLAUDE.md` if present.
3. The current task prompt.
4. Relevant project files, usually:
   - `Patch-TPW-LevelMusic-Combined.py`
   - `Patch-TPW-LevelMusic-README.md`
   - `TPW-LevelMusic-Investigation.md`

Do not assume previous chat context is available unless it is included in files or the prompt.

## Current Project State

The level-music fix is implemented as a combined v1+v2+v3 binary patch.

The preferred patcher is:

```text
Patch-TPW-LevelMusic-Combined.py
```

It is intended to:

- Apply all fixes from a true original `TP.exe`.
- Finish partially patched v1 or v1+v2 executables.
- Detect final already-patched executables and exit cleanly.
- Refuse unknown byte layouts.
- Create backups and verify changed bytes.

## Core Findings To Preserve

Do not remove or blur the core technical finding:

- The bug centers on `DAT_00803AA0`, the level-music object/request handle.
- v1 fixes `FUN_0051C400` clobbering the freshly-created handle from stale saved sound-state.
- v2 fixes `FUN_0051E790` unconditionally storing `0` over a still-valid handle.
- v3 fixes first-time level entry by re-running `FUN_0051E730` one selector tick later, after `\music\MusicHD.sdt` is available.

Important tested executable addresses:

| Item | Address |
|---|---:|
| `DAT_00803AA0` | `0x00803AA0` |
| `DAT_00803A44` | `0x00803A44` |
| `FUN_0051E730` | `0x0051E730` |
| `FUN_0051E790` | `0x0051E790` |
| `FUN_0051BC40` | `0x0051BC40` |
| `FUN_0051C400` | `0x0051C400` |
| v1 callsite | `0x00415BA2` |
| v3 `FUN_0051E730` return hook | `0x0051E764` |

## Legal / Public Release Rules

Public-safe releases may include:

- Python patch scripts.
- Markdown documentation.
- Investigation reports.
- Optional trace scripts or sanitized logs.

Public releases must not include:

- `TP.exe`
- `TP.icd`
- patched executables
- original executables
- SDT/WAD files
- copied game assets
- full game archives
- unsanitized save files

Use clear wording:

```text
This tool patches your own legally-owned TP.exe in place. It does not include or distribute any game files.
```

Do not claim universal support. Say:

```text
The patcher supports the tested executable layout and refuses unknown byte layouts.
```

## Binary Patcher Hard Rules

When editing patcher logic, preserve or improve these behaviors:

- Dry-run mode.
- Fingerprint/expected-byte checks.
- Patch-state detection.
- Refuse unknown executable layouts.
- Timestamped backup before writing.
- Post-write byte verification.
- Idempotency / clean already-applied handling.
- Rollback instructions.
- Exact VA/file-offset/old-byte/new-byte plan output.
- No silent overwrites of unexpected bytes.
- No game asset modification.

Never replace a defensive check with a looser check unless the prompt explicitly asks and explains why.

## Combined Patcher State Handling

The combined patcher should support these states:

| State | Behavior |
|---|---|
| Original tested EXE | Apply v1 + v2 + v3 |
| v1 only | Apply v2 + v3 |
| v1 + v2 | Apply v3 |
| Fully patched | Report already applied, exit 0 |
| Unknown / mismatched | Refuse safely, exit nonzero |

Do not convert the combined patcher into a wrapper that requires separate v1/v2/v3 scripts. It must remain self-contained unless the task explicitly says otherwise.

## Documentation Rules

Public documentation should:

- Start with a normal-user explanation.
- Clearly say what the patch fixes.
- Clearly say no game files are included.
- Keep the technical evidence available.
- Move dense reverse-engineering details into technical sections or appendices.
- Preserve addresses, key functions, byte patches, and validation evidence.
- Avoid overclaiming support for untested EXE versions.

Important nuance to preserve:

- Early pre-v1/v2 traces made it look like `MusicHD.sdt` was never reached.
- Later v3 traces showed first-entry after v1/v2 does open real `\music\MusicHD.sdt`, but too late for the first-created music object.
- v3 fixes that ordering issue with a one-tick delayed re-prime.

## Development Workflow

Agents should follow this process:

1. Inspect relevant files first.
2. Explain the intended change briefly.
3. Make the smallest safe change.
4. Preserve existing behavior outside the target task.
5. Validate using appropriate commands.
6. Write a Markdown summary file.
7. Respond briefly in chat and point to the summary file.

Do not dump a long final summary into chat.

Use the appropriate summary filename:

```text
claude-summary.md
codex-summary.md
gemini-summary.md
```

The summary must include:

- Files changed.
- What changed.
- Why it works.
- Commands run.
- Command results.
- Manual checks needed or completed.
- Known compromises.
- Follow-up tasks.

## Validation Commands

For docs-only edits:

- No binary patch test required unless the docs change claims about behavior.
- Check spelling/links manually.
- Ensure public docs do not recommend publishing game binaries/assets.

For patcher edits, prefer testing on a copied `TP.exe`, not the real install.

PowerShell example:

```powershell
$src = "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
$work = "$env:TEMP\TPW-Patcher-Test"
New-Item -ItemType Directory -Force $work | Out-Null
Copy-Item $src "$work\TP.exe" -Force

py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$work\TP.exe" --dry-run
py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$work\TP.exe"
py -3.12 .\Patch-TPW-LevelMusic-Combined.py "$work\TP.exe" --dry-run
```

Expected:

- First dry-run prints a valid plan and writes nothing.
- Apply creates a backup and verifies changes.
- Second dry-run/run reports already applied cleanly.

Manual validation must be done by the human tester in-game:

- Fresh first-time level entry plays music immediately.
- Exit/re-enter same level still plays music.
- Different level first-entry plays music.
- Menu/lobby music still works.
- No stuck/overlapping music when leaving levels.

## Source Control Safety

Before editing or final reporting, inspect when practical:

```bash
git status --short
git diff --stat
```

Do not:

- Revert user changes.
- Clean unrelated dirty files.
- Commit unless explicitly asked.
- Commit binaries, backups, or game assets.
- Commit local-only temp files.
- Commit generated release ZIPs unless explicitly requested.

## Destructive Command Safety

Never run destructive commands against the user's real game directory unless explicitly requested.

Avoid:

- deleting game files
- deleting save files
- replacing `TP.exe` without a backup
- removing backup files
- bulk cleanup commands
- `git reset --hard`
- `git clean -fd`

When in doubt, work on a copy in a temp directory.

## Dependency Safety

The current patcher is pure Python standard library.

Do not add dependencies unless explicitly approved.

Avoid adding:

- GUI frameworks
- binary parsing libraries
- build systems
- packaging tools
- network dependencies

A future GUI may be approved later, but the patcher core should remain auditable and simple.

## GUI Frontend Guardrails

GUI work is a later task.

If asked to build a GUI:

- Keep it as a thin wrapper around the existing patcher logic.
- Do not create a second independent patch implementation.
- Preserve dry-run, backup, and rollback behavior.
- Display detected state and exact backup path.
- Make the legal/no-game-files note visible.
- Let the human tester judge usability.

## Release Packaging Rules

A public release bundle should include only safe files, for example:

```text
Patch-TPW-LevelMusic-Combined.py
Patch-TPW-LevelMusic-README.md
TPW-LevelMusic-Investigation.md
```

Optional safe extras:

```text
tpw-v3-ordering-trace.js
sanitized logs
compatibility scanner
```

Never include game files.

If documentation mentions private archives, label it clearly:

```text
Private archive only — do not publish game files.
```

## Agent Selection Guidance

- Claude Code: careful reasoning, docs cleanup, patcher architecture, avoiding cursed rewrites.
- Codex: narrow exact-file code edits, tests, small bug fixes.
- Gemini CLI: cheap/high-quota inspection, grep-style searches, quick report cleanup.

For risky binary patcher edits, prefer investigation and dry-run validation before writing.

## Known Later Tasks

Do not implement unless explicitly requested:

- GUI frontend.
- Installer.
- PyInstaller packaging.
- GitHub Actions release workflow.
- Compatibility scanner for many game versions.
- Registry install-path autodetection.
- Linux/Wine helper scripts.
- Website/docs site.
- Alternate executable patch support.
- Auto-updater.

## Philosophy

This is preservation tooling, not a throwaway hack.

Keep it:

- safe
- reversible
- transparent
- public-safe
- source-available
- boring where possible

Small clean passes beat giant cursed rewrites.
