# Theme Park World — In-Park Level Music Investigation

## Status: RESOLVED (v1 + v2 + v3 applied)

Level music now works via three layered, permanent binary patches to `TP.exe`:

- **v1** fixes a save/park-state restore routine that clobbered the freshly-created
  level-music object handle immediately after creation.
- **v2** fixes a per-tick selector that could overwrite a *still-valid* handle
  with `0`.
- **v3** fixes the remaining **first-time level entry** bug: the level-music
  object created at level load can be created *before* the level's
  `\music\MusicHD.sdt` is opened by the asset loader, so it permanently fails
  from the second tick onward. v3 detects this and re-creates the object one
  tick later, after the asset is guaranteed to be loaded.

## Executive Summary

Three distinct bugs were found and fixed, all centered on the global
`DAT_00803aa0` (the level-music object/request handle):

1. **v1 (save/park restore clobber)** — `FUN_0051c400` (save/park sound-state
   restore) ran immediately after `FUN_0051e730` (level music startup) and
   overwrote the freshly-created, valid object handle with stale saved data
   (effectively `0`). Fixed by re-running `FUN_0051e730` after `FUN_0051c400`.
2. **v2 (per-tick selector overwrite)** — `FUN_0051e790`, the periodic
   track-selector, unconditionally stored the result of
   `FUN_0051bc40(DAT_00803aa0,4,iVar5)` back into `DAT_00803aa0` even when that
   call returned `0` and the existing handle was still valid — clobbering a
   working handle mid-level. Fixed by only storing `0` if the old handle was
   already `0`.
3. **v3 (first-time-entry ordering bug)** — even with v1+v2, **first-time**
   entry into a level still had no music. Root cause: on first-time entry,
   `FUN_0051e730` runs *before* the level's `\music\MusicHD.sdt` has been
   opened by the asset loader. The resulting object answers the very first
   `FUN_0051bc40(obj,4,0)` "prime track" call successfully (a no-op success on
   creation), but on every later tick this call permanently returns `0`
   because the audio bank wasn't registered yet at creation time. On
   re-entry, `MusicHD.sdt` is already cached from the prior visit, so whatever
   object gets created next works immediately — which is why **only
   first-time entry** was affected. Fixed by re-creating the object exactly
   once, on the next per-tick selector call after the original creation.

A Frida-based runtime fix for each bug proved the diagnosis and restored music
in real time before any binary patch was written. Each fix was then turned into
a permanent `TP.exe` binary patch, layered in a single `.fix` section, and
tested and confirmed working — including first-time entry into a never-visited
level.

## Original Symptom

- Main menu / lobby music: **worked**
- In-park level music: **broken**, on all four levels (fantasy, hallow, jungle, space)
- `MusicHD.sdt` / `MusicHW.sdt`: never opened during the broken level-music path

ProcMon showed the game successfully accessing the level music category maps:

```
data\levels\hallow\Music\cat_musicBANK.map
data\levels\hallow\Music\cat_musicSFX.map
```

and unsuccessfully attempting:

```
data\levels\hallow\music.wad   -> NAME NOT FOUND
```

The `music.wad` miss turned out to be a red herring — the game never got far
enough to reach the proper SDT load path for level music in the first place.

## Environment

- Install path: `C:\Program Files (x86)\Bullfrog\Theme Park World`
- Graphics: DDrawCompat (`DDraw.dll`, `ddrawcompat.ini`)
- Audio: QMixer.dll (315,392 bytes — updated per community fix)
- `TP.EXE` / `TP_AltRes.EXE`: hex-edited per the community memory-allocation fix
- `TP.exe`: 3,734,528 bytes; `TP.icd` (SafeDisc-era companion payload, not
  touched by this investigation): 3,734,573 bytes
- Image base: `0x00400000`, PE32, no relocation/ASLR — all hardcoded VAs below
  are stable across runs

## Fixes Already Applied Earlier (no effect on level music)

- HyperJeanJean / TPW-TPI-Fixes pack, including updated `QMixer.dll`
- Hex-edited `TP.exe` (memory allocation fix)
- New save profile (rules out profile-specific caching)
- `Config.tcf` "music enabled" byte-flip theory — tested and reverted, no effect
- In-game Graphics/Music Quality set to maximum — no effect
- Mounting the original disc while playing (rules out CD-presence checks)

## Data Integrity Checks (all passed, all irrelevant to the actual bug)

- Each level's `Music\` folder contains `MusicHD.sdt`, `cat_musicBANK.map`,
  `cat_musicSFX.map`, all present, correctly sized, and byte-identical to the
  original disc / win810 patch copies.
- `cat_musicBANK.map` and `MusicHD.sdt` structure both decode correctly and are
  structurally valid (same format as the working `LobbyMusicHD.sdt`, just with
  more tracks — 86 vs 2-3).

## Reverse-Engineering Trace (Ghidra + live Frida)

### Key globals and functions

| Symbol | Address | Role |
|---|---|---|
| `cat_music` string | `00762e68` | category name |
| `DAT_00803a44` | `0x00803A44` | `cat_music` category handle (set once, stays valid) |
| `DAT_00803aa0` | `0x00803AA0` | **level music object/request handle — the global that gets clobbered** |
| `DAT_00802bc8` / `DAT_00802bd4` | `0x00802BC8` / `0x00802BD4` | sound-subsystem ready flags (confirmed valid: `1024` / `1`) |
| `DAT_00802bcc` | `0x00802BCC` | sound-manager object pointer (confirmed valid) |
| `FUN_0051ec50` | - | initializes sound categories (`cat_ambient`, `cat_speech`, `cat_music`, ...), sets `DAT_00803a44` |
| `FUN_0051e730` | `0x0051E730` | **level music startup** - creates `DAT_00803aa0` via `FUN_0051bfc0`, then calls `FUN_0051bc40(obj,4,0)` |
| `FUN_0051e790` | `0x0051E790` | periodic music-track selector - calls `FUN_0051bc40(DAT_00803aa0,4,iVar5)` every ~32 ticks |
| `FUN_0051bfc0` | - | creates the music request object via the sound-manager vtable |
| `FUN_0051bc40` | `0x0051BC40` | command dispatcher -> `FUN_006b5b80` -> vtable dispatch |
| `FUN_006b8a10` | - | vtable target with a `param_3 != 0` guard - initially suspected, later refuted |
| `FUN_0051c400` | `0x0051C400` | **the actual culprit** - save/park sound-state restore/load |

### Refuted theories (in order investigated)

1. **Missing `music.wad`** - present in ProcMon trace but the game never reaches
   the code path that would need it; not the cause.
2. **Broken `MusicHD.sdt` / `MusicHW.sdt`** - files are valid; the game never
   gets far enough to open them.
3. **Sound system not ready** - Frida confirmed `DAT_00802bc8=1024`,
   `DAT_00802bd4=1`, `DAT_00802bcc` non-null, `DAT_00803a44` (cat_music) non-zero
   at the moment `FUN_0051e730` runs. Sound subsystem is fully initialized.
4. **`FUN_0051bc40(obj,4,0)` inside `FUN_0051e730` destroying the object** -
   tested live; the object remains valid (`DAT_00803aa0` unchanged) immediately
   after this call. Not the cause.
5. **Stuck movie/cutscene state** (`*(DAT_007cf83c + 0x1da738) == 4`) - read
   live in-level with no music playing: value was `0`, not `4`. Not the cause.
6. **`FUN_004c81e0()` returning `0` (track index always 0)** - true, but once
   `DAT_00803aa0` stays valid, music plays correctly even with this value `0`.
   Not a blocking issue.

### Root cause

```
1. FUN_0051e730 runs at level load:
     DAT_00803aa0 = FUN_0051bfc0(DAT_00803aa0, DAT_00803a44, 2, 0, 0, 0);  // valid object created
     DAT_00803aa0 = FUN_0051bc40(DAT_00803aa0, 4, 0);                      // object remains valid

2. FUN_0051c400 runs immediately afterward (save/park sound-state restore/load).
   It deserializes a 0x54-byte sound-state block from saved park data directly
   into &DAT_00803aa0:

     0x51C45F  push 0x803AA0
     0x51C466  call 0x5F5E20        ; deserialize into DAT_00803aa0..

3. This overwrites the freshly-created, valid DAT_00803aa0 with stale saved
   data (effectively 0).

4. FUN_0051e790 (periodic selector) then runs with DAT_00803aa0 == 0, and the
   level-music playback path is never reached - MusicHD.sdt is never opened.
```

### Smoking-gun Frida trace

```
[0051e730 ENTER] level music startup
DAT_00803aa0 = 0x0,  DAT_00803a44(cat_music) = 0xd

[0051e730 LEAVE]
DAT_00803aa0 = 0x14c0057a   <- valid object created

[0051c400 ENTER] sound-state restore/load
DAT_00803aa0 = 0x14c0057a

[0051c400 LEAVE]
DAT_00803aa0 = 0x0          <- clobbered by stale save-state restore

[0051e790 ENTER hit 1.. N]
DAT_00803aa0 = 0x0          <- level music permanently dead from here on
```

This explains every observation: menu music (not gated by this state) works,
`cat_music` registers correctly, the level-music object is created correctly -
and then silently destroyed before it can ever be used.

## Runtime Fix (proof of diagnosis)

A Frida hook on `FUN_0051c400`'s return called `FUN_0051e730()` again
immediately afterward:

```
[0051c400 leave] DAT_00803aa0=0x0
[LIVE FIX] Calling FUN_0051e730 again...
[after forced 0051e730] DAT_00803aa0=0xb6490f39

[0051e790 enter] DAT_00803aa0=0xb6490f39
[0051e790 leave] DAT_00803aa0=0xb6490f39
```

Level music played correctly. A resident Frida launcher
(`Start-TPW-WithMusicFix-v3-Resident.ps1`) applied this fix across multiple
level loads in a single session, confirming the fix generalizes.

## Permanent Fix: `Patch-TPW-LevelMusic.py`

The single direct callsite to `FUN_0051c400` is at VA `0x00415BA2`
(file offset `0x14FA2`):

```
Original bytes: e8 59 68 10 00    ; call 0x0051C400
Patched bytes:  e8 59 04 bb 00    ; call <stub in new .fix section>
```

The patch appends a new executable `.fix` section to `TP.exe` containing a
20-byte trampoline stub, then redirects the callsite through it:

```asm
push dword ptr [esp+4]   ; re-push param_1 for FUN_0051c400
call 0x0051C400          ; run the original save/state restore unchanged
add esp, 4               ; clean up (cdecl)
push eax                 ; preserve retval
call 0x0051E730          ; immediately re-run level-music startup
pop eax                   ; restore retval
ret
```

This is deliberately **non-destructive**: the original stale restore still
runs in full (preserving whatever other sound-state fields it's responsible
for), and `FUN_0051e730` is simply re-run afterward to recreate the level-music
object. The original return value (`EAX`) is preserved for the caller.

### Verifying original vs. patched bytes

```powershell
$tp = "C:\Program Files (x86)\Bullfrog\Theme Park World\TP.exe"
$fs = [IO.File]::OpenRead($tp)
$fs.Position = 0x14FA2
$buf = New-Object byte[] 5
$null = $fs.Read($buf, 0, 5)
$fs.Close()
($buf | ForEach-Object { $_.ToString("x2") }) -join " "
```

- Unpatched: `e8 59 68 10 00`
- Patched:   `e8 59 04 bb 00`

### Validation results

- [x] First level load - music plays
- [x] Switching to another level - music plays
- [x] Menu/lobby music - unaffected, still works
- [x] Save/load - no crash
- [x] Initial concern that the `.fix` patch caused menu/level-select lag was
      investigated and **ruled out** - the lag had an unrelated cause. The
      patch itself adds no measurable overhead (one extra function call per
      level load).

## v2: Per-Tick Selector Overwrite (`Patch-TPW-LevelMusic-v2.py`)

### Symptom

After v1, first-time level entry music improved on some levels but **mid-level
music could still drop out** on a later `FUN_0051e790` tick, even though
`DAT_00803aa0` had been a valid object handle moments before.

### Root cause

`FUN_0051e790` is a tiny per-tick selector:

```c
DAT_00803aa0 = FUN_0051bc40(DAT_00803aa0, 4, iVar5);
```

`FUN_0051bc40(obj,4,iVar5)` ("prime/select track") can legitimately return `0`
on a given tick even while the object itself (`obj`) is still valid (e.g. no
track change needed this tick). The original code stored that `0` straight
back into `DAT_00803aa0` unconditionally — permanently destroying a
still-valid handle.

### Fix

Redirect the 5-byte function entry at VA `0x0051E790`
(`8B 44 24 04 8B` → `E9 <rel32>`, a `jmp`) to a new 40-byte stub appended to
the `.fix` section (created by v1). The stub replicates the original call, but
only stores the `0` return value if the *old* handle (`DAT_00803aa0` before the
call) was also `0`:

```asm
mov   eax, [esp+4]          ; iVar5
mov   ecx, [DAT_00803aa0]    ; old handle
push  ecx                    ; stash old handle
push  eax
push  4
push  ecx
call  FUN_0051bc40
add   esp, 0xC
pop   ecx                    ; restore old handle
test  eax, eax
jne   store                  ; non-zero result: always store it
test  ecx, ecx
je    store                  ; old handle was already 0: store 0 too
mov   eax, ecx                ; old handle was valid, result was 0: keep old
store:
mov   [DAT_00803aa0], eax
ret
```

### Result

v2 alone fixed the "valid handle gets clobbered mid-level by a `0` result"
case, but **did not** fix first-time level-entry music on its own — that
required v3 (below).

## v3: First-Time-Entry Ordering Bug (`Patch-TPW-LevelMusic-v3.py`)

### Symptom

Even with v1 + v2 applied, **first-time entry into a never-visited level**
still had no music. Exiting and re-entering the same level fixed it for that
session — the bug only ever affected the *first* visit to a level.

### Investigation: ordering trace

A combined Frida trace (`tpw-v3-ordering-trace.js`) instrumented, with a global
sequence counter, every relevant event: `FUN_0051e730` enter/leave,
`FUN_0051bc40` enter/leave (with return address, `obj`, `cmd`, `arg`, `retval`),
`FUN_0051e790` enter/leave (per tick), `FUN_0051c400` enter/leave, and
`CreateFileA`/`CreateFileW` filtered for `MusicHD.sdt` / `MusicHW.sdt` /
`cat_music*.map` (tagging each event `BEFORE-MusicHD` / `AFTER-MusicHD` based
on whether the level's real `\music\MusicHD.sdt` had been opened with a valid
handle yet — carefully distinguished from the substring-colliding
`\sound\LobbyMusicHD.sdt`).

On a clean first-time entry into hallow, the trace showed:

```
#15-18  FUN_0051e730 (1st call)  -> creates aa0=0x2bce00cd
                                     bc40(0x2bce00cd,4,0) succeeds (1st-call pattern)
#19-20  CreateFileW "\music\MusicHD.sdt" -> handle=0x1094   (AFTER this point: MusicHD seen)
#21     musicHDSeen = true
#22     FUN_0051e790 tick #1 ENTER, aa0 still = 0x2bce00cd
```

Combined with earlier traces, the established pattern for `bc40(obj,4,0)` is:
it **succeeds on the call immediately following object creation** regardless
of whether `MusicHD.sdt` has been opened yet (a no-op "success" on init), but
on the *next* tick it either:

- returns `0` permanently, if `obj` was created **before** `MusicHD.sdt` was
  opened (first-time entry — the bug), or
- continues returning `obj` (success) on every tick, if `obj` was created
  **after** `MusicHD.sdt` was opened (re-entry, or the v3-fixed case).

### Runtime test: delayed re-prime

A Frida runtime test was added to the same trace: once `MusicHD.sdt` had been
seen, on the very next `FUN_0051e790` tick, call `FUN_0051e730()` again (before
running the tick's normal selector body):

```
#22  FUN_0051e790 tick #1 ENTER, aa0=0x2bce00cd  (pre-MusicHD object)
#23  *** V3 TEST: re-triggering FUN_0051e730 on tick #1 ***
#24  *** re-call returned ***  aa0=0x2bd30447    (new, post-MusicHD object)
#25..#161  ticks #1-#30 (30 consecutive ticks):
       bc40(0x2bd30447,4,0) returns 0x2bd30447 — success every time
```

Music played audibly for the entire run, including a natural second
`e730`/`c400`/`e730` cycle later in the same session (objects
`0x2c550116` → `0x2c590cd`), which also succeeded on every subsequent tick.

### Root cause (confirmed)

On first-time level entry, `FUN_0051e730` creates the level-music object
*before* the level's `\music\MusicHD.sdt` has been opened by the asset loader.
That object's `bc40(obj,4,0)` "prime track" call permanently returns `0` from
the second tick onward because the underlying audio bank wasn't registered at
creation time. By the time `FUN_0051e790` tick #1 fires, `MusicHD.sdt` has
*always* already been opened (level loading, including all asset/category file
opens, happens synchronously before the per-tick loop starts) — so re-creating
the object exactly once, on tick #1, after the original creation, is sufficient
and requires no file-open hook in the final patch.

### Fix: combined v2+v3 stub, "delayed re-prime"

v3 extends the `.fix` section created by v1 and adds:

- Two 1-byte flags: `REPRIME_PENDING` and `SUPPRESS_REARM` (`.fix` is marked
  writable via `IMAGE_SCN_MEM_WRITE` to support these).
- A small hook on `FUN_0051e730`'s `ret` (VA `0x0051E764`, with 11 trailing NOP
  bytes giving 12 bytes of free space — enough for a 5-byte `jmp` to a 25-byte
  stub):
  ```
  on FUN_0051e730 return:
    if SUPPRESS_REARM != 0:
        SUPPRESS_REARM = 0        ; this was our own re-prime call -- don't re-arm
    else:
        REPRIME_PENDING = 1       ; a natural call -- arm the delayed re-prime
    ret
  ```
- A new combined 68-byte stub replacing v2's `FUN_0051e790` stub:
  ```
  if REPRIME_PENDING != 0:
      REPRIME_PENDING = 0
      SUPPRESS_REARM = 1
      call FUN_0051e730            ; delayed re-prime, creates a fresh working object
  ; then v2's body, unchanged:
  mov eax, [esp+4]                  ; iVar5
  mov ecx, [DAT_00803aa0]            ; old handle
  ... call FUN_0051bc40(old,4,iVar5), keep old handle if result==0 and old!=0 ...
  mov [DAT_00803aa0], eax
  ret
  ```
- `FUN_0051e790`'s entry jmp (originally pointed at v2's stub) is repointed at
  this new combined stub. v1's and v2's original stub bytes are left in place
  but become dead code.

The `SUPPRESS_REARM` flag is what prevents an infinite loop: without it, the
delayed re-prime's own call to `FUN_0051e730` would itself set
`REPRIME_PENDING=1` again, causing every subsequent tick to re-create the music
object forever.

On any *natural* call to `FUN_0051e730` (first-time level load, or the
v1/c400-driven re-entry cycle), the next tick performs one extra delayed
re-prime. On re-entry this is a harmless extra object creation/switch (the
trace showed re-entry already succeeds without it); on first-time entry it is
the actual fix.

### Validation results

- [x] First-time entry into a never-visited level — music plays immediately,
      no exit/re-entry workaround needed (confirmed via the Frida runtime test
      across 30+ consecutive ticks, then re-confirmed audibly by ear)
- [x] Exit and re-enter the same level — music still plays
- [x] A natural second `e730`/`c400`/`e730` cycle within the same session —
      also succeeds on every subsequent tick
- [x] `Patch-TPW-LevelMusic-v3.py` is defensive like v1/v2: requires v1 and v2
      to be present in their exact expected forms, verifies all `.fix`
      destination regions are still `0xCC` padding before writing, is
      idempotent (detects and reports a clean "already applied" if re-run),
      creates a timestamped backup, and verifies every changed byte after
      writing

## Save-State Side Note: "Healed" Saves

While iterating on the Frida fix, one previously-broken save started working
*without* any patch applied. Explanation: while the resident Frida fix was
active, level music initialized correctly, and the game subsequently wrote
**fresh, valid sound-state data** back into that save's park state on its next
autosave - "healing" that specific save. A different (not-yet-resaved) save
remained broken, confirming the corruption is per-save/per-park, living in
files such as `autosave.TPWS` / `gms.dat` / `Config.tcf` under
`save\users\<profile>\...`. The exact internal format of the stale block
wasn't decoded, but the EXE patch makes this moot - `DAT_00803aa0` gets
recreated every level load regardless of what the save contains.

## Rollback Procedure

Each patch (v1/v2/v3) makes its own timestamped backup before writing. To roll
back to *before v1 was ever applied* (removing all three patches at once,
since v2 and v3 both depend on and extend v1's `.fix` section):

```powershell
cd "C:\Program Files (x86)\Bullfrog\Theme Park World"

Get-Process TP -ErrorAction SilentlyContinue | Stop-Process -Force

$bak = Get-ChildItem .\TP.EXE.levelmusic-bak-* |
  Sort-Object LastWriteTime -Descending |
  Select-Object -Last 1

Copy-Item $bak.FullName .\TP.exe -Force
```

(`Select-Object -Last 1` picks the *oldest* backup, i.e. the original
pre-v1 file, since backups are named with ascending timestamps:
`...levelmusic-bak-*` from v1, `...levelmusic-v2-bak-*` from v2,
`...levelmusic-v3-bak-*` from v3.)

Verify rollback by checking file offset `0x14FA2` reads back to
`e8 59 68 10 00`.

To roll back **only v3** (keeping v1+v2), restore the most recent
`TP.EXE.levelmusic-v3-bak-*` instead:

```powershell
$bak = Get-ChildItem .\TP.EXE.levelmusic-v3-bak-* |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Copy-Item $bak.FullName .\TP.exe -Force
```

`Patch-TPW-LevelMusic-v3.py` also prints the exact `Copy-Item` rollback command
for the backup it just created at the end of every successful run.

## Registry / Install Script Reconciliation (separate, resolved earlier)

While investigating, confirmed the actual working registry state and updated
`Install-ThemeParkWorld.ps1` accordingly:

- `Wow6432Node\Bullfrog Productions Ltd\Theme Park World` (Version/Language) is
  created correctly by `SETUP.EXE` itself - the script's previous hardcoded
  `Version=2.0`/`Language=0x409` write didn't match a real install and is read
  by a Golden Ticket method (`GetGameVersionFromReg`) that is never actually
  called. Removed from the script.
- `CARPET.EXE\BULLFROG.LBM` AppCompat flag - confirmed empty/unset on the
  working install; vestigial Win9x DOS-emulation setting, doesn't apply on
  modern Windows. Removed from the script.
- Kept the `App Paths\TP.exe` `(Default)` / `Path` entries, which match the
  working system and are what `GetInstallLocationFromReg()` actually reads.

## Recommended Archive Contents

Keep together for future reference / re-application after reinstalls:

- `TP.exe` (patched with v1+v2+v3) and original backups
  (`TP.EXE.levelmusic-bak-*`, `TP.EXE.levelmusic-v2-bak-*`,
  `TP.EXE.levelmusic-v3-bak-*`)
- `Patch-TPW-LevelMusic.py` (v1)
- `Patch-TPW-LevelMusic-v2.py` (v2)
- `Patch-TPW-LevelMusic-v3.py` (v3)
- `Patch-TPW-LevelMusic-Combined.py` (single-file v1+v2+v3 patcher, recommended
  for fresh/unpatched EXEs -- produces byte-identical output to running v1,
  v2, v3 in sequence, and can also finish off a v1- or v1+v2-only EXE in one
  pass)
- `Patch-TPW-LevelMusic-All.py` (orchestrator: detects current patch state and
  runs only the v1/v2/v3 scripts still needed)
- `Test-TPW-PatchCompat.py` (read-only scanner: checks whether an unpatched
  TP.exe from another distribution matches the byte signatures v1/v2/v3 and
  the combined patcher depend on)
- `tpw-v3-ordering-trace.js` (Frida trace used to diagnose and validate v3)
- `Start-TPW-WithMusicFix-v3-Resident.ps1` (Frida resident fix / save healer,
  superseded by the v1-v3 binary patches but useful for future debugging)
- This report
- A known-good save backup

## Final Conclusion

```
We did not fix missing files.

v1: fixed bad runtime ordering caused by a stale save/park sound-state restore
    (FUN_0051c400) clobbering the freshly-created level-music object
    (DAT_00803aa0) that FUN_0051e730 had just set up.

v2: fixed FUN_0051e790 (the per-tick track selector) unconditionally storing a
    `0` result over a still-valid DAT_00803aa0 handle.

v3: fixed the first-time-entry-only case, where FUN_0051e730 creates
    DAT_00803aa0 *before* the level's \music\MusicHD.sdt is opened by the
    asset loader, causing the object to permanently fail from the second tick
    onward. Fixed by re-creating the object exactly once, one
    FUN_0051e790 tick after the original creation -- by which point
    MusicHD.sdt has always already been opened.
```

Level music now works on Windows 11 via the permanently patched `TP.exe`
(v1+v2+v3), including on the very first visit to a level, with no Frida or
runtime tooling required at play time.
