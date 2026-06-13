# SPDX-License-Identifier: MIT

#!/usr/bin/env python3
"""
Patch Theme Park World TP.exe for in-park level music (combined v1+v2+v3),
in a single pass.

This is a self-contained, single-file equivalent of running
Patch-TPW-LevelMusic.py (v1), Patch-TPW-LevelMusic-v2.py (v2), and
Patch-TPW-LevelMusic-v3.py (v3) in sequence. It produces byte-identical
results to that sequence (same .fix section layout, same redirects), so it
is fully interoperable with those scripts and with Patch-TPW-LevelMusic-All.py
-- e.g. a TP.exe patched by this script is detected as "v3" (fully patched)
by the others, and an EXE partially patched by the old scripts (v1-only or
v1+v2) can be finished off by this one.

Root causes fixed (see TPW-LevelMusic-Investigation.md for full detail):

  v1 - FUN_0051c400 (save/park sound-state restore) clobbers the freshly
       created level-music object (DAT_00803aa0) immediately after
       FUN_0051e730 creates it. Fixed by re-running FUN_0051e730 right after
       FUN_0051c400, via a trampoline stub in a new .fix section.

  v2 - FUN_0051e790 (per-tick track selector) unconditionally stores the
       result of FUN_0051bc40(DAT_00803aa0,4,iVar5) back into DAT_00803aa0,
       even when that result is 0 and the existing handle is still valid.
       Fixed by only storing 0 if the old handle was already 0.

  v3 - On FIRST-TIME level entry, FUN_0051e730 can run before the level's
       \\music\\MusicHD.sdt has been opened by the asset loader, so the
       resulting object permanently fails from the second tick onward.
       Fixed by re-creating the object exactly once, on the very next
       FUN_0051e790 tick after the original FUN_0051e730 call returns (by
       which point MusicHD.sdt has always already been opened).

Final .fix section layout (0x1000 bytes, RWX):
  +0x00  v1 trampoline stub (20 bytes) - called from the redirected
         callsite at VA 0x00415BA2
  +0x14  v2 stub (40 bytes) - dead code in the final v3 state, kept for
         byte-for-byte parity with the sequential v1->v2->v3 patch path
  +0x40  v3 flags: REPRIME_PENDING (1 byte), SUPPRESS_REARM (1 byte)
  +0x50  v3 e730-return hook (25 bytes) - jumped to from FUN_0051e730's `ret`
  +0x80  v3 combined v2+v3 stub (68 bytes) - jumped to from FUN_0051e790's
         entry; this is the live FUN_0051e790 implementation
  rest   0xCC padding

Three code sites are redirected:
  - VA 0x00415BA2 (5 bytes): call FUN_0051c400  ->  call <.fix+0x00>
  - VA 0x0051E764 (12 bytes): ret + 11x nop     ->  jmp <.fix+0x50> + 7x nop
  - VA 0x0051E790 (5 bytes): mov eax,[esp+4]... ->  jmp <.fix+0x80>

Usage:
    py Patch-TPW-LevelMusic-Combined.py [--dry-run] "<path to TP.exe>"

Run from an elevated PowerShell if TP.exe is inside Program Files.

Rollback:
    Restore the timestamped backup this script creates next to TP.exe, e.g.:
        Copy-Item "TP.exe.levelmusic-combined-bak-YYYYMMDD-HHMMSS" "TP.exe" -Force
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import struct
import sys
from pathlib import Path

IMAGE_BASE = 0x00400000

# --- v1 site/constants -------------------------------------------------
V1_CALLSITE_VA = 0x00415BA2
V1_CALLSITE_NEXT_VA = 0x00415BA7
FUN_0051C400_VA = 0x0051C400
V1_STUB_OFFSET = 0x00
V1_STUB_SIZE = 20

SECTION_NAME = b".fix\x00\x00\x00\x00"
SECTION_VSIZE = 0x1000
# IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE
SECTION_CHARACTERISTICS = 0xE0000020
IMAGE_SCN_MEM_WRITE = 0x80000000

# --- v2 site/constants ----------------------------------------------------
FUN_0051E790_VA = 0x0051E790
FUN_0051E790_AFTER_VA = 0x0051E795
FUN_0051BC40_VA = 0x0051BC40
DAT_00803AA0_VA = 0x00803AA0
V2_STUB_OFFSET = 0x14
V2_STUB_SIZE = 40
V2_ORIGINAL_E790_ENTRY = b"\x8B\x44\x24\x04\x8B"

# --- v3 site/constants -----------------------------------------------------
FUN_0051E730_VA = 0x0051E730
FUN_0051E730_RET_VA = 0x0051E764
FUN_0051E730_RET_PATCH_LEN = 12
EXPECTED_E730_RET_REGION = b"\xC3" + b"\x90" * 11
EXPECTED_E730_ENTRY_FINGERPRINT = bytes.fromhex("A1 44 3A 80 00 8B 0D A0 3A 80 00".replace(" ", ""))

FLAGS_OFFSET = 0x40
E730_HOOK_OFFSET = 0x50
E730_HOOK_SIZE = 25
E790_STUB_OFFSET = 0x80
E790_STUB_SIZE = 68


class PatchError(RuntimeError):
    pass


class AlreadyApplied(Exception):
    pass


# --- low-level helpers ------------------------------------------------------

def read_u16(data: bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def read_u32(data: bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def write_u16(data: bytearray, off: int, value: int) -> None:
    struct.pack_into("<H", data, off, value & 0xFFFF)


def write_u32(data: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", data, off, value & 0xFFFFFFFF)


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        raise PatchError(f"Invalid alignment: {alignment}")
    return (value + alignment - 1) & ~(alignment - 1)


def rel32(target_va: int, after_va: int) -> bytes:
    delta = target_va - after_va
    if not -(2**31) <= delta < 2**31:
        raise PatchError(f"rel32 target out of range: target=0x{target_va:X}, after=0x{after_va:X}, delta={delta}")
    return struct.pack("<i", delta)


def rel8(target_off: int, after_off: int) -> bytes:
    delta = target_off - after_off
    if not -128 <= delta < 128:
        raise PatchError(f"rel8 target out of range: delta={delta}")
    return struct.pack("<b", delta)


def parse_pe(data: bytearray):
    if data[:2] != b"MZ":
        raise PatchError("Not an MZ executable.")
    e_lfanew = read_u32(data, 0x3C)
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise PatchError("Missing PE signature.")

    file_header = e_lfanew + 4
    num_sections = read_u16(data, file_header + 2)
    size_opt = read_u16(data, file_header + 16)
    opt = file_header + 20
    magic = read_u16(data, opt)
    if magic != 0x10B:
        raise PatchError(f"Expected PE32 optional header magic 0x10B, got 0x{magic:X}. This patch is for 32-bit TP.exe.")

    image_base = read_u32(data, opt + 28)
    section_alignment = read_u32(data, opt + 32)
    file_alignment = read_u32(data, opt + 36)
    size_of_image_off = opt + 56
    size_of_headers = read_u32(data, opt + 60)
    sec_table = opt + size_opt

    sections = []
    for i in range(num_sections):
        off = sec_table + i * 40
        name = bytes(data[off:off + 8]).rstrip(b"\x00")
        virtual_size = read_u32(data, off + 8)
        virtual_address = read_u32(data, off + 12)
        size_raw = read_u32(data, off + 16)
        ptr_raw = read_u32(data, off + 20)
        characteristics = read_u32(data, off + 36)
        sections.append({
            "header_off": off,
            "name": name,
            "virtual_size": virtual_size,
            "virtual_address": virtual_address,
            "size_raw": size_raw,
            "ptr_raw": ptr_raw,
            "characteristics": characteristics,
        })

    return {
        "file_header": file_header,
        "num_sections": num_sections,
        "sec_table": sec_table,
        "image_base": image_base,
        "section_alignment": section_alignment,
        "file_alignment": file_alignment,
        "size_of_image_off": size_of_image_off,
        "size_of_headers": size_of_headers,
        "sections": sections,
    }


def rva_to_file_offset(rva: int, sections: list[dict]) -> int:
    for sec in sections:
        start = sec["virtual_address"]
        span = max(sec["virtual_size"], sec["size_raw"])
        end = start + span
        if start <= rva < end:
            return sec["ptr_raw"] + (rva - start)
    raise PatchError(f"Could not map RVA 0x{rva:X} to a file offset.")


# --- stub builders -----------------------------------------------------------

def build_v1_stub(stub_va: int) -> bytes:
    stub = bytearray()
    stub += b"\xFF\x74\x24\x04"                                      # push dword ptr [esp+4]
    stub += b"\xE8" + rel32(FUN_0051C400_VA, stub_va + 9)             # call FUN_0051C400
    stub += b"\x83\xC4\x04"                                           # add esp, 4
    stub += b"\x50"                                                   # push eax
    stub += b"\xE8" + rel32(FUN_0051E730_VA, stub_va + 18)            # call FUN_0051E730
    stub += b"\x58"                                                   # pop eax
    stub += b"\xC3"                                                   # ret
    if len(stub) != V1_STUB_SIZE:
        raise PatchError(f"Internal error: v1 stub length is {len(stub)}, expected {V1_STUB_SIZE}.")
    return bytes(stub)


def build_v2_stub(stub_va: int) -> bytes:
    stub = bytearray()
    stub += b"\x8B\x44\x24\x04"                                       # mov eax, [esp+4]   (iVar5)
    stub += b"\x8B\x0D" + struct.pack("<I", DAT_00803AA0_VA)          # mov ecx, [DAT_00803AA0]
    stub += b"\x51"                                                   # push ecx (stash old handle)
    stub += b"\x50"                                                   # push eax
    stub += b"\x6A\x04"                                               # push 4
    stub += b"\x51"                                                   # push ecx
    call_after = stub_va + 20
    stub += b"\xE8" + rel32(FUN_0051BC40_VA, call_after)              # call FUN_0051BC40
    stub += b"\x83\xC4\x0C"                                           # add esp, 0xC
    stub += b"\x59"                                                   # pop ecx (restore old handle)
    stub += b"\x85\xC0"                                               # test eax, eax
    stub += b"\x75" + rel8(34, 28)                                    # jne store
    stub += b"\x85\xC9"                                               # test ecx, ecx
    stub += b"\x74" + rel8(34, 32)                                    # je store
    stub += b"\x89\xC8"                                               # mov eax, ecx
    stub += b"\xA3" + struct.pack("<I", DAT_00803AA0_VA)              # store: mov [DAT_00803AA0], eax
    stub += b"\xC3"                                                   # ret
    if len(stub) != V2_STUB_SIZE:
        raise PatchError(f"Internal error: v2 stub length is {len(stub)}, expected {V2_STUB_SIZE}.")
    return bytes(stub)


def build_e730_hook(suppress_va: int, pending_va: int) -> bytes:
    b = bytearray()
    b += b"\x80\x3D" + struct.pack("<I", suppress_va) + b"\x00"      # cmp byte [SUPPRESS_REARM], 0
    b += b"\x74" + rel8(17, 9)                                         # je clear_and_set_pending
    b += b"\xC6\x05" + struct.pack("<I", suppress_va) + b"\x00"       # mov byte [SUPPRESS_REARM], 0
    b += b"\xC3"                                                       # ret
    b += b"\xC6\x05" + struct.pack("<I", pending_va) + b"\x01"        # clear_and_set_pending: mov byte [REPRIME_PENDING], 1
    b += b"\xC3"                                                       # ret
    if len(b) != E730_HOOK_SIZE:
        raise PatchError(f"Internal error: e730 hook length is {len(b)}, expected {E730_HOOK_SIZE}.")
    return bytes(b)


def build_e790_stub(stub_va: int, pending_va: int, suppress_va: int) -> bytes:
    b = bytearray()
    b += b"\x80\x3D" + struct.pack("<I", pending_va) + b"\x00"        # cmp byte [REPRIME_PENDING], 0
    b += b"\x74" + rel8(28, 9)                                          # je v2_body
    b += b"\xC6\x05" + struct.pack("<I", pending_va) + b"\x00"         # mov byte [REPRIME_PENDING], 0
    b += b"\xC6\x05" + struct.pack("<I", suppress_va) + b"\x01"        # mov byte [SUPPRESS_REARM], 1
    call_e730_after = stub_va + 28
    b += b"\xE8" + rel32(FUN_0051E730_VA, call_e730_after)              # call FUN_0051E730

    # v2_body @ offset 28
    b += b"\x8B\x44\x24\x04"                                            # mov eax, [esp+4]
    b += b"\x8B\x0D" + struct.pack("<I", DAT_00803AA0_VA)               # mov ecx, [DAT_00803AA0]
    b += b"\x51"                                                        # push ecx
    b += b"\x50"                                                        # push eax
    b += b"\x6A\x04"                                                    # push 4
    b += b"\x51"                                                        # push ecx
    call_bc40_after = stub_va + 48
    b += b"\xE8" + rel32(FUN_0051BC40_VA, call_bc40_after)              # call FUN_0051BC40
    b += b"\x83\xC4\x0C"                                                # add esp, 0xC
    b += b"\x59"                                                        # pop ecx
    b += b"\x85\xC0"                                                    # test eax, eax
    b += b"\x75" + rel8(62, 56)                                          # jne store
    b += b"\x85\xC9"                                                    # test ecx, ecx
    b += b"\x74" + rel8(62, 60)                                          # je store
    b += b"\x89\xC8"                                                    # mov eax, ecx
    b += b"\xA3" + struct.pack("<I", DAT_00803AA0_VA)                   # store: mov [DAT_00803AA0], eax
    b += b"\xC3"                                                        # ret
    if len(b) != E790_STUB_SIZE:
        raise PatchError(f"Internal error: e790 stub length is {len(b)}, expected {E790_STUB_SIZE}.")
    return bytes(b)


def build_fix_content(fix_va_base: int) -> bytes:
    """Full target contents of the .fix section, for the final v1+v2+v3 state."""
    content = bytearray(b"\xCC" * SECTION_VSIZE)
    content[V1_STUB_OFFSET:V1_STUB_OFFSET + V1_STUB_SIZE] = build_v1_stub(fix_va_base + V1_STUB_OFFSET)
    content[V2_STUB_OFFSET:V2_STUB_OFFSET + V2_STUB_SIZE] = build_v2_stub(fix_va_base + V2_STUB_OFFSET)

    pending_va = fix_va_base + FLAGS_OFFSET
    suppress_va = fix_va_base + FLAGS_OFFSET + 1
    content[FLAGS_OFFSET:FLAGS_OFFSET + 2] = b"\x00\x00"

    e730_hook_va = fix_va_base + E730_HOOK_OFFSET
    content[E730_HOOK_OFFSET:E730_HOOK_OFFSET + E730_HOOK_SIZE] = build_e730_hook(suppress_va, pending_va)

    e790_stub_va = fix_va_base + E790_STUB_OFFSET
    content[E790_STUB_OFFSET:E790_STUB_OFFSET + E790_STUB_SIZE] = build_e790_stub(e790_stub_va, pending_va, suppress_va)

    return bytes(content)


# --- main patch logic --------------------------------------------------------

def patch_exe(path: Path, dry_run: bool = False) -> None:
    if not path.exists():
        raise PatchError(f"File not found: {path}")
    if path.name.lower() != "tp.exe":
        print(f"Warning: target file is named {path.name!r}, not TP.exe.")

    data = bytearray(path.read_bytes())
    pe = parse_pe(data)

    image_base = pe["image_base"]
    if image_base != IMAGE_BASE:
        raise PatchError(
            f"Unexpected ImageBase 0x{image_base:X} (expected 0x{IMAGE_BASE:X}). "
            "Refusing to patch an unrecognized EXE layout/version."
        )

    # --- Fingerprint check (independent of any of our patches).
    e730_rva = FUN_0051E730_VA - image_base
    e730_off = rva_to_file_offset(e730_rva, pe["sections"])
    e730_entry = bytes(data[e730_off:e730_off + len(EXPECTED_E730_ENTRY_FINGERPRINT)])
    if e730_entry != EXPECTED_E730_ENTRY_FINGERPRINT:
        raise PatchError(
            "FUN_0051E730 entry bytes do not match the known fingerprint.\n"
            f"  Expected: {EXPECTED_E730_ENTRY_FINGERPRINT.hex(' ')}\n"
            f"  Found:    {e730_entry.hex(' ')}\n"
            "Refusing to patch an unrecognized EXE layout/version."
        )

    # --- Locate or plan the .fix section.
    fix_sections = [s for s in pe["sections"] if s["name"] == b".fix"]
    has_fix = bool(fix_sections)

    if has_fix:
        fix_sec = fix_sections[0]
        fix_va_base = image_base + fix_sec["virtual_address"]
        if fix_sec["size_raw"] < SECTION_VSIZE:
            raise PatchError(
                f".fix section is smaller than expected (0x{fix_sec['size_raw']:X} < 0x{SECTION_VSIZE:X}). "
                "Unrecognized layout -- refusing to patch."
            )
        v1_stub_actual = bytes(data[fix_sec["ptr_raw"] + V1_STUB_OFFSET: fix_sec["ptr_raw"] + V1_STUB_OFFSET + V1_STUB_SIZE])
        if v1_stub_actual != build_v1_stub(fix_va_base + V1_STUB_OFFSET):
            raise PatchError(
                ".fix section exists but its first 20 bytes don't match the expected v1 stub.\n"
                f"  Expected: {build_v1_stub(fix_va_base).hex(' ')}\n"
                f"  Found:    {v1_stub_actual.hex(' ')}\n"
                "Unrecognized .fix layout -- refusing to patch."
            )
    else:
        fix_sec = None
        fix_va_base = None  # determined below if/when we add the section

    # --- Classify the three redirect sites against their "original" and
    # "already patched" forms.
    v1_callsite_rva = V1_CALLSITE_VA - image_base
    v1_callsite_off = rva_to_file_offset(v1_callsite_rva, pe["sections"])
    v1_callsite = bytes(data[v1_callsite_off:v1_callsite_off + 5])
    expected_v1_callsite_orig = b"\xE8" + rel32(FUN_0051C400_VA, V1_CALLSITE_NEXT_VA)

    e730ret_rva = FUN_0051E730_RET_VA - image_base
    e730ret_off = rva_to_file_offset(e730ret_rva, pe["sections"])
    e730ret = bytes(data[e730ret_off:e730ret_off + FUN_0051E730_RET_PATCH_LEN])

    e790_rva = FUN_0051E790_VA - image_base
    e790_off = rva_to_file_offset(e790_rva, pe["sections"])
    e790 = bytes(data[e790_off:e790_off + 5])

    if has_fix:
        expected_v1_callsite_patched = b"\xE8" + rel32(fix_va_base + V1_STUB_OFFSET, V1_CALLSITE_NEXT_VA)
        expected_e730ret_patched = b"\xE9" + rel32(fix_va_base + E730_HOOK_OFFSET, FUN_0051E730_RET_VA + 5)
        expected_e730ret_patched += b"\x90" * (FUN_0051E730_RET_PATCH_LEN - len(expected_e730ret_patched))
        v2_stub_va = fix_va_base + V2_STUB_OFFSET
        expected_v2_jmp = b"\xE9" + rel32(v2_stub_va, FUN_0051E790_AFTER_VA)
        v3_stub_va = fix_va_base + E790_STUB_OFFSET
        expected_v3_jmp = b"\xE9" + rel32(v3_stub_va, FUN_0051E790_AFTER_VA)
    else:
        expected_v1_callsite_patched = None
        expected_e730ret_patched = None
        expected_v2_jmp = None
        expected_v3_jmp = None

    # v1 callsite state
    if v1_callsite == expected_v1_callsite_orig:
        v1_state = "original"
    elif has_fix and v1_callsite == expected_v1_callsite_patched:
        v1_state = "patched"
    else:
        raise PatchError(
            "Unexpected bytes at v1 callsite (VA 0x{:08X}).\n"
            "  Found:    {}\n"
            "  Expected (original): {}\n"
            "{}"
            "Refusing to patch an unrecognized state.".format(
                V1_CALLSITE_VA,
                v1_callsite.hex(' '),
                expected_v1_callsite_orig.hex(' '),
                f"  Expected (patched):  {expected_v1_callsite_patched.hex(' ')}\n" if expected_v1_callsite_patched else "",
            )
        )

    # FUN_0051E730 ret region state
    if e730ret == EXPECTED_E730_RET_REGION:
        e730ret_state = "original"
    elif has_fix and e730ret == expected_e730ret_patched:
        e730ret_state = "patched"
    else:
        raise PatchError(
            "Unexpected bytes at FUN_0051E730 return region (VA 0x{:08X}).\n"
            "  Found:    {}\n"
            "  Expected (original): {}\n"
            "{}"
            "Refusing to patch an unrecognized state.".format(
                FUN_0051E730_RET_VA,
                e730ret.hex(' '),
                EXPECTED_E730_RET_REGION.hex(' '),
                f"  Expected (patched):  {expected_e730ret_patched.hex(' ')}\n" if expected_e730ret_patched else "",
            )
        )

    # FUN_0051E790 entry state
    if e790 == V2_ORIGINAL_E790_ENTRY:
        e790_state = "original"
    elif has_fix and e790 == expected_v2_jmp:
        e790_state = "v2"
    elif has_fix and e790 == expected_v3_jmp:
        e790_state = "v3"
    else:
        raise PatchError(
            "Unexpected bytes at FUN_0051E790 entry (VA 0x{:08X}).\n"
            "  Found:    {}\n"
            "  Expected (original): {}\n"
            "{}"
            "Refusing to patch an unrecognized state.".format(
                FUN_0051E790_VA,
                e790.hex(' '),
                V2_ORIGINAL_E790_ENTRY.hex(' '),
                (f"  Expected (v2):  {expected_v2_jmp.hex(' ')}\n  Expected (v3):  {expected_v3_jmp.hex(' ')}\n"
                 if expected_v2_jmp else ""),
            )
        )

    # --- Cross-consistency: !has_fix implies all three sites must be "original".
    if not has_fix and (v1_state != "original" or e730ret_state != "original" or e790_state != "original"):
        raise PatchError("Inconsistent state: no .fix section, but a redirect site is already patched. Refusing.")

    # --- Idempotency check: fully applied already?
    if has_fix and v1_state == "patched" and e730ret_state == "patched" and e790_state == "v3":
        target_content = build_fix_content(fix_va_base)
        actual_content = bytes(data[fix_sec["ptr_raw"]:fix_sec["ptr_raw"] + SECTION_VSIZE])
        chars_ok = (fix_sec["characteristics"] & SECTION_CHARACTERISTICS) == SECTION_CHARACTERISTICS
        if actual_content == target_content and chars_ok:
            print("v1+v2+v3 are already fully applied to this TP.exe (combined layout). No changes made.")
            print("")
            print(f"  v1 callsite (0x{V1_CALLSITE_VA:08X}):       {v1_callsite.hex(' ')}")
            print(f"  FUN_0051E730 ret (0x{FUN_0051E730_RET_VA:08X}): {e730ret.hex(' ')}")
            print(f"  FUN_0051E790 entry (0x{FUN_0051E790_VA:08X}):  {e790.hex(' ')}")
            print(f"  .fix VA: 0x{fix_va_base:08X}, characteristics: 0x{fix_sec['characteristics']:08X}")
            raise AlreadyApplied()
        # has_fix + all three redirects "patched"/"v3" but .fix content/characteristics
        # don't fully match our target -- fall through and let the write below
        # bring it into the canonical state (re-writing .fix content is safe/idempotent).

    # --- Plan the .fix section (new or existing).
    new_section_plan = None
    if not has_fix:
        last = pe["sections"][-1]
        new_sec_header_off = pe["sec_table"] + pe["num_sections"] * 40
        if new_sec_header_off + 40 > pe["size_of_headers"]:
            raise PatchError(
                "No room for another section header before SizeOfHeaders. "
                "Use a full PE editor/LIEF approach instead."
            )
        last_va_end = last["virtual_address"] + max(last["virtual_size"], last["size_raw"])
        new_va = align_up(last_va_end, pe["section_alignment"])
        new_raw = align_up(len(data), pe["file_alignment"])
        new_raw_size = align_up(SECTION_VSIZE, pe["file_alignment"])
        new_size_of_image = align_up(new_va + SECTION_VSIZE, pe["section_alignment"])
        fix_va_base = image_base + new_va
        new_section_plan = {
            "header_off": new_sec_header_off,
            "va": new_va,
            "raw": new_raw,
            "raw_size": new_raw_size,
            "size_of_image": new_size_of_image,
        }
        # Recompute "original" expectations now that fix_va_base is known --
        # only used for the print plan below.
        expected_v1_callsite_patched = b"\xE8" + rel32(fix_va_base + V1_STUB_OFFSET, V1_CALLSITE_NEXT_VA)
        expected_e730ret_patched = b"\xE9" + rel32(fix_va_base + E730_HOOK_OFFSET, FUN_0051E730_RET_VA + 5)
        expected_e730ret_patched += b"\x90" * (FUN_0051E730_RET_PATCH_LEN - len(expected_e730ret_patched))
        v3_stub_va = fix_va_base + E790_STUB_OFFSET
        expected_v3_jmp = b"\xE9" + rel32(v3_stub_va, FUN_0051E790_AFTER_VA)

    target_fix_content = build_fix_content(fix_va_base)

    # --- Print plan.
    print("Patch plan (combined v1+v2+v3):")
    print(f"  Target:                {path}")
    print(f"  ImageBase:             0x{image_base:08X}")
    print(f"  .fix VA:               0x{fix_va_base:08X}")
    if new_section_plan:
        print(f"  .fix section:          NEW (RVA 0x{new_section_plan['va']:X}, "
              f"raw offset 0x{new_section_plan['raw']:X}, size 0x{new_section_plan['raw_size']:X})")
    else:
        print(f"  .fix section:          EXISTING (RVA 0x{fix_sec['virtual_address']:X}, "
              f"raw offset 0x{fix_sec['ptr_raw']:X}, size 0x{fix_sec['size_raw']:X})")
        print(f"    characteristics:     0x{fix_sec['characteristics']:08X} -> 0x{fix_sec['characteristics'] | SECTION_CHARACTERISTICS:08X}")
        old_content = bytes(data[fix_sec["ptr_raw"]:fix_sec["ptr_raw"] + SECTION_VSIZE])
        if old_content == target_fix_content:
            print("    content:             already matches target (no change)")
        else:
            print("    content:             will be (re)written to the canonical v1+v2+v3 layout")
    print("")
    print(f"  v1 callsite VA 0x{V1_CALLSITE_VA:08X} (file off 0x{v1_callsite_off:X}):")
    print(f"    old: {v1_callsite.hex(' ')}  [{v1_state}]")
    print(f"    new: {expected_v1_callsite_patched.hex(' ')}  (call .fix+0x{V1_STUB_OFFSET:02X})")
    print("")
    print(f"  FUN_0051E730 ret VA 0x{FUN_0051E730_RET_VA:08X} (file off 0x{e730ret_off:X}):")
    print(f"    old: {e730ret.hex(' ')}  [{e730ret_state}]")
    print(f"    new: {expected_e730ret_patched.hex(' ')}  (jmp .fix+0x{E730_HOOK_OFFSET:02X})")
    print("")
    print(f"  FUN_0051E790 entry VA 0x{FUN_0051E790_VA:08X} (file off 0x{e790_off:X}):")
    print(f"    old: {e790.hex(' ')}  [{e790_state}]")
    print(f"    new: {expected_v3_jmp.hex(' ')}  (jmp .fix+0x{E790_STUB_OFFSET:02X})")

    if dry_run:
        print("")
        print("Dry run only. No files were modified.")
        return

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.levelmusic-combined-bak-{timestamp}")
    shutil.copy2(path, backup)
    print("")
    print(f"Backup created:        {backup}")

    if new_section_plan:
        plan = new_section_plan
        if plan["raw"] > len(data):
            data += b"\x00" * (plan["raw"] - len(data))

        hdr = bytearray(40)
        hdr[0:8] = SECTION_NAME
        write_u32(hdr, 8, SECTION_VSIZE)
        write_u32(hdr, 12, plan["va"])
        write_u32(hdr, 16, plan["raw_size"])
        write_u32(hdr, 20, plan["raw"])
        write_u32(hdr, 24, 0)
        write_u32(hdr, 28, 0)
        write_u16(hdr, 32, 0)
        write_u16(hdr, 34, 0)
        write_u32(hdr, 36, SECTION_CHARACTERISTICS)
        data[plan["header_off"]:plan["header_off"] + 40] = hdr

        write_u16(data, pe["file_header"] + 2, pe["num_sections"] + 1)
        write_u32(data, pe["size_of_image_off"], plan["size_of_image"])

        end_needed = plan["raw"] + plan["raw_size"]
        if len(data) < end_needed:
            data += b"\x00" * (end_needed - len(data))
        section_content = target_fix_content + b"\xCC" * (plan["raw_size"] - len(target_fix_content))
        data[plan["raw"]:plan["raw"] + plan["raw_size"]] = section_content

        fix_content_off = plan["raw"]
        fix_characteristics_off = plan["header_off"] + 36
        new_characteristics = SECTION_CHARACTERISTICS
    else:
        fix_content_off = fix_sec["ptr_raw"]
        data[fix_content_off:fix_content_off + SECTION_VSIZE] = target_fix_content
        fix_characteristics_off = fix_sec["header_off"] + 36
        new_characteristics = fix_sec["characteristics"] | SECTION_CHARACTERISTICS
        write_u32(data, fix_characteristics_off, new_characteristics)

    # Redirect the three sites (only those not already patched).
    if v1_state == "original":
        data[v1_callsite_off:v1_callsite_off + 5] = expected_v1_callsite_patched
    if e730ret_state == "original":
        data[e730ret_off:e730ret_off + FUN_0051E730_RET_PATCH_LEN] = expected_e730ret_patched
    if e790_state != "v3":
        data[e790_off:e790_off + 5] = expected_v3_jmp

    path.write_bytes(data)

    # --- Post-write verification.
    verify = bytearray(path.read_bytes())
    pe2 = parse_pe(verify)
    fix2 = [s for s in pe2["sections"] if s["name"] == b".fix"][0]

    checks = [
        (".fix content", bytes(verify[fix2["ptr_raw"]:fix2["ptr_raw"] + SECTION_VSIZE]), target_fix_content),
        (".fix characteristics", read_u32(verify, fix2["header_off"] + 36), new_characteristics),
        ("v1 callsite", bytes(verify[v1_callsite_off:v1_callsite_off + 5]), expected_v1_callsite_patched),
        ("FUN_0051E730 ret patch", bytes(verify[e730ret_off:e730ret_off + FUN_0051E730_RET_PATCH_LEN]), expected_e730ret_patched),
        ("FUN_0051E790 entry patch", bytes(verify[e790_off:e790_off + 5]), expected_v3_jmp),
    ]
    if new_section_plan:
        checks.append(("section count", pe2["num_sections"], pe["num_sections"] + 1))

    for name, actual, expected in checks:
        if actual != expected:
            raise PatchError(
                f"Verification failed: {name} mismatch after write.\n"
                f"  Expected: {expected if isinstance(expected, int) else expected.hex(' ')}\n"
                f"  Found:    {actual if isinstance(actual, int) else actual.hex(' ')}\n"
                f"A backup was made at {backup} -- restore it if needed."
            )

    print("")
    print("Patch complete OK (v1 + v2 + v3, combined)")
    print(f"Rollback backup:       {backup}")
    print("")
    print("Rollback instructions (if needed):")
    print(f'  Copy-Item "{backup}" "{path}" -Force')
    print("")
    print("Validation checklist:")
    print("  1. Create/use a fresh save and enter a level for the FIRST time.")
    print("     Confirm level music plays immediately (no exit/re-entry needed).")
    print("  2. Exit and re-enter the same level; confirm music still plays.")
    print("  3. Switch levels; confirm music plays on first entry there too.")
    print("  4. Test menu/lobby music; confirm unaffected.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch TP.exe (combined v1+v2+v3) to fix level music.")
    parser.add_argument("tp_exe", nargs="?", default="TP.exe", help="Path to TP.exe. Defaults to ./TP.exe")
    parser.add_argument("--dry-run", action="store_true", help="Print patch plan without modifying the file.")
    args = parser.parse_args(argv)

    try:
        patch_exe(Path(args.tp_exe).resolve(), dry_run=args.dry_run)
        return 0
    except AlreadyApplied:
        return 0
    except PatchError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"\nERROR: Permission denied: {e}", file=sys.stderr)
        print("Try running PowerShell as Administrator if TP.exe is inside Program Files.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
