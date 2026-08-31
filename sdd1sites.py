import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

cpu = hardware.load("mos65xx")
dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")

import sdd1map  # noqa: E402

REGISTER_BASE = 0x4800
REGISTER_COUNT = 8
ARM_REGISTER = 0x4801
ENABLE_REGISTER = 0x4800
STA_ABSOLUTE = 0x8D
DMA_START = "sta $420b"
FIXED_ADDRESS_BIT = 0x08
RESYNC_BACK = 80
RESYNC_FORWARD = 12

Found = namedtuple("Found", "offset address register")


def lorom_address(offset: int) -> int:
    return (offset // 0x8000) << 16 | (0x8000 + offset % 0x8000)


def compressed_mask(rom: bytes | bytearray, entries: list[Any]) -> bytearray:
    mask = bytearray(len(rom))
    for entry in entries:
        if entry.length is None:
            continue
        end = min(sdd1.decompress(rom, entry.source, entry.length).end, len(rom))
        for i in range(entry.source, end):
            mask[i] = 1
    return mask


def find_register_writes(rom: bytes | bytearray, mask: bytearray) -> list[Any]:
    found = []
    for index in range(REGISTER_COUNT):
        register = REGISTER_BASE + index
        pattern = bytes([STA_ABSOLUTE, register & 0xFF, register >> 8])
        at = rom.find(pattern)
        while at >= 0:
            if not mask[at]:
                found.append(Found(at, lorom_address(at), register))
            at = rom.find(pattern, at + 1)
    found.sort(key=lambda f: f.offset)
    return found


def window(
    rom: bytes | bytearray,
    offset: int,
    back: int = RESYNC_BACK,
    forward: int = RESYNC_FORWARD,
) -> Any:
    best: tuple[int, int, bool, bool] | None = None
    for distance in range(back, 3, -1):
        start = offset - distance
        if start < 0:
            continue
        for m in (True, False):
            for x in (True, False):
                listing = cpu.disassemble(
                    rom[: offset + forward], start, lorom_address(start), m=m, x=x
                )
                if any(i.offset == offset for i in listing) and (
                    best is None or distance > best[0]
                ):
                    best = (distance, start, m, x)
    if best is None:
        return cpu.disassemble(rom[: offset + forward], offset, lorom_address(offset))
    _, start, m, x = best
    return cpu.disassemble(rom[: offset + forward], start, lorom_address(start), m=m, x=x)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: sdd1sites.py <source-rom> <tagged-rom>", file=sys.stderr)
        return 2

    rom = dump.read(sys.argv[1])
    entries = sdd1map.build_map(dump.read(sys.argv[2]))
    mask = compressed_mask(rom, entries)
    print(f"  compressed data covers {sum(mask):,} of {len(rom):,} bytes")

    found = find_register_writes(rom, mask)
    by_register: dict[int, list[Any]] = {}
    for item in found:
        by_register.setdefault(item.register, []).append(item)
    for register in sorted(by_register):
        places = by_register[register]
        print(
            f"  ${register:04X} written from {len(places)} places: "
            f"{', '.join(f'${f.address:06X}' for f in places)}"
        )

    print("\n  arm sites in detail")
    for item in [f for f in found if f.register == ARM_REGISTER]:
        print(f"\n  === ${item.address:06X}  file {item.offset:#09x}")
        for line in window(rom, item.offset):
            if line.offset < item.offset - 40:
                continue
            mark = "   <<<" if line.offset == item.offset else ""
            raw = rom[line.offset : line.offset + line.size].hex(" ")
            print(f"    ${line.address:06X}  {raw:<11} {line.text}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
