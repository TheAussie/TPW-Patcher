#!/usr/bin/env python3
"""
Read-only compatibility scan: checks whether a TP.exe matches all the byte
signatures that Patch-TPW-LevelMusic.py (v1), Patch-TPW-LevelMusic-v2.py (v2),
and Patch-TPW-LevelMusic-v3.py (v3) depend on -- WITHOUT applying any patch.

This is useful for checking a TP.exe from a different distribution (e.g. a
different "Win8/10 patch" build) before running the real patchers, since v2's
and v3's own --dry-run modes require the *previous* patch to already be
applied and would just fail with "vN not present" on a fresh EXE.

Usage:
    py Test-TPW-PatchCompat.py "D:\\path\\to\\TP.exe"

Exit code 0 = all signatures match (v1, v2, v3 should all apply cleanly, in
that order, on an unpatched copy of this EXE).
Exit code 1 = at least one mismatch found (details printed).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def read_u16(data: bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def read_u32(data: bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_pe(data: bytearray):
    if data[:2] != b"MZ":
        raise ValueError("Not an MZ executable.")

    e_lfanew = read_u32(data, 0x3C)
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("Missing PE signature.")

    file_header = e_lfanew + 4
    num_sections = read_u16(data, file_header + 2)
    size_opt = read_u16(data, file_header + 16)
    opt = file_header + 20
    magic = read_u16(data, opt)
    if magic != 0x10B:
        raise ValueError(f"Expected PE32 optional header magic 0x10B, got 0x{magic:X} (not 32-bit).")

    image_base = read_u32(data, opt + 28)
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
        sections.append({
            "name": name,
            "virtual_size": virtual_size,
            "virtual_address": virtual_address,
            "size_raw": size_raw,
            "ptr_raw": ptr_raw,
        })

    return {
        "image_base": image_base,
        "size_of_headers": size_of_headers,
        "sec_table": sec_table,
        "num_sections": num_sections,
        "sections": sections,
    }


def rva_to_file_offset(rva: int, sections: list[dict]) -> int | None:
    for sec in sections:
        start = sec["virtual_address"]
        span = max(sec["virtual_size"], sec["size_raw"])
        end = start + span
        if start <= rva < end:
            return sec["ptr_raw"] + (rva - start)
    return None


def rel32(target_va: int, after_va: int) -> bytes:
    delta = target_va - after_va
    return struct.pack("<i", delta & 0xFFFFFFFF if delta < 0 else delta)


# --- Known-good signatures, derived from the working v1/v2/v3 patchers -----

IMAGE_BASE_EXPECTED = 0x00400000

# v1: original callsite at 0x00415BA2 is `call FUN_0051C400` (e8 + rel32)
V1_CALLSITE_VA = 0x00415BA2
V1_CALLSITE_NEXT_VA = 0x00415BA7
FUN_0051C400_VA = 0x0051C400
V1_EXPECTED_CALLSITE = b"\xE8" + rel32(FUN_0051C400_VA, V1_CALLSITE_NEXT_VA)

# v2: original FUN_0051E790 entry starts `mov eax,[esp+4]; mov ...`
FUN_0051E790_VA = 0x0051E790
V2_EXPECTED_E790_ENTRY = b"\x8B\x44\x24\x04\x8B"

# v3: FUN_0051E730 entry fingerprint, and its ret+NOP region
FUN_0051E730_VA = 0x0051E730
V3_EXPECTED_E730_ENTRY_FINGERPRINT = bytes.fromhex("A1 44 3A 80 00 8B 0D A0 3A 80 00".replace(" ", ""))
FUN_0051E730_RET_VA = 0x0051E764
V3_EXPECTED_E730_RET_REGION = b"\xC3" + b"\x90" * 11


def check(label: str, expected: bytes, actual: bytes | None, results: list[tuple[str, bool, str]]) -> None:
    if actual is None:
        results.append((label, False, "address not mapped to any section"))
        return
    ok = actual == expected
    detail = f"expected {expected.hex(' ')}, found {actual.hex(' ')}"
    results.append((label, ok, detail))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: py Test-TPW-PatchCompat.py <path-to-TP.exe>", file=sys.stderr)
        return 2

    path = Path(argv[0]).resolve()
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    data = bytearray(path.read_bytes())

    print(f"Target: {path}")
    print(f"Size:   {len(data):,} bytes")
    print("")

    try:
        pe = parse_pe(data)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    results: list[tuple[str, bool, str]] = []

    # --- ImageBase
    ib_ok = pe["image_base"] == IMAGE_BASE_EXPECTED
    results.append((
        "ImageBase == 0x00400000",
        ib_ok,
        f"found 0x{pe['image_base']:08X}",
    ))

    # --- .fix section must not already exist (fresh EXE expected)
    fix_sections = [s for s in pe["sections"] if s["name"] == b".fix"]
    results.append((
        "No pre-existing .fix section",
        not fix_sections,
        "found .fix section -- this EXE may already be patched" if fix_sections else "ok",
    ))

    # --- Room for one more section header (v1 needs this)
    new_sec_header_off = pe["sec_table"] + pe["num_sections"] * 40
    room_ok = new_sec_header_off + 40 <= pe["size_of_headers"]
    results.append((
        "Room for one more PE section header (v1)",
        room_ok,
        f"new header would start at file offset 0x{new_sec_header_off:X}, "
        f"SizeOfHeaders=0x{pe['size_of_headers']:X}",
    ))

    if ib_ok:
        # --- v1 callsite signature
        v1_rva = V1_CALLSITE_VA - pe["image_base"]
        v1_off = rva_to_file_offset(v1_rva, pe["sections"])
        v1_actual = bytes(data[v1_off:v1_off + 5]) if v1_off is not None else None
        check(f"v1 callsite @ VA 0x{V1_CALLSITE_VA:08X} (file off "
              f"{'0x%X' % v1_off if v1_off is not None else '?'}) == `call FUN_0051C400`",
              V1_EXPECTED_CALLSITE, v1_actual, results)

        # --- v2 original FUN_0051E790 entry signature
        e790_rva = FUN_0051E790_VA - pe["image_base"]
        e790_off = rva_to_file_offset(e790_rva, pe["sections"])
        e790_actual = bytes(data[e790_off:e790_off + 5]) if e790_off is not None else None
        check(f"v2 FUN_0051E790 entry @ VA 0x{FUN_0051E790_VA:08X} (file off "
              f"{'0x%X' % e790_off if e790_off is not None else '?'}) == original bytes",
              V2_EXPECTED_E790_ENTRY, e790_actual, results)

        # --- v3 FUN_0051E730 entry fingerprint
        e730_rva = FUN_0051E730_VA - pe["image_base"]
        e730_off = rva_to_file_offset(e730_rva, pe["sections"])
        e730_actual = bytes(data[e730_off:e730_off + len(V3_EXPECTED_E730_ENTRY_FINGERPRINT)]) if e730_off is not None else None
        check(f"v3 FUN_0051E730 entry @ VA 0x{FUN_0051E730_VA:08X} (file off "
              f"{'0x%X' % e730_off if e730_off is not None else '?'}) fingerprint",
              V3_EXPECTED_E730_ENTRY_FINGERPRINT, e730_actual, results)

        # --- v3 FUN_0051E730 ret+NOP region
        e730ret_rva = FUN_0051E730_RET_VA - pe["image_base"]
        e730ret_off = rva_to_file_offset(e730ret_rva, pe["sections"])
        e730ret_actual = bytes(data[e730ret_off:e730ret_off + len(V3_EXPECTED_E730_RET_REGION)]) if e730ret_off is not None else None
        check(f"v3 FUN_0051E730 ret+NOPs @ VA 0x{FUN_0051E730_RET_VA:08X} (file off "
              f"{'0x%X' % e730ret_off if e730ret_off is not None else '?'}) == `ret` + 11x `nop`",
              V3_EXPECTED_E730_RET_REGION, e730ret_actual, results)
    else:
        results.append(("(skipped v1/v2/v3 byte checks -- ImageBase mismatch)", False, ""))

    # --- Print results
    all_ok = True
    for label, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        line = f"  [{status}] {label}"
        if detail and detail != "ok":
            line += f"\n         {detail}"
        print(line)

    print("")
    if all_ok:
        print("All signatures match. v1, then v2, then v3 should apply cleanly to an")
        print("unpatched copy of this TP.exe, in that order.")
        return 0
    else:
        print("One or more signatures do NOT match. Applying v1/v2/v3 as-is is NOT")
        print("recommended on this TP.exe -- the patchers would either refuse to run")
        print("(if they hit the same mismatches) or, in the worst case, patch the")
        print("wrong bytes if a mismatch happens to coincidentally pass a weaker check.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
