import itertools
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


MARKER = b"SDD1"
MARKER_SIZE = 8
PACKED_GAPS = (-1, 0)
BANK_SIZE = 0x10000

Entry = namedtuple("Entry", "index source target length")


def find_markers(tagged: bytes | bytearray) -> list[tuple[int, int]]:
    markers = []
    at = tagged.find(MARKER)
    while at >= 0:
        target = int.from_bytes(tagged[at + 4 : at + MARKER_SIZE], "little")
        markers.append((at, target))
        at = tagged.find(MARKER, at + 1)
    return markers


def build_map(tagged: bytes | bytearray, gfx_size: int | None = None) -> list[Entry]:
    markers = find_markers(tagged)
    targets = [target for _, target in markers]
    if targets != sorted(targets) or len(set(targets)) != len(targets):
        raise ValueError("marker targets are not strictly increasing")
    if gfx_size is not None and markers and gfx_size <= targets[-1]:
        raise ValueError("declared graphics size is below the last target")

    entries = []
    for index, (source, target) in enumerate(markers):
        if index + 1 < len(markers):
            length = targets[index + 1] - target
        elif gfx_size is not None:
            length = gfx_size - target
        else:
            length = None
        entries.append(Entry(index, source, target, length))
    return entries


def audit(rom: bytes | bytearray, entries: list[Entry]) -> dict[str, int]:
    report = {"measured": 0, "packed": 0, "padded": 0, "overrun": 0, "skipped": 0}
    for entry, following in itertools.pairwise(entries):
        if entry.length is None or not 0 < following.source - entry.source < BANK_SIZE:
            report["skipped"] += 1
            continue
        report["measured"] += 1
        gap = following.source - sdd1.decompress(rom, entry.source, entry.length).end
        if gap in PACKED_GAPS:
            report["packed"] += 1
        elif gap > 0:
            report["padded"] += 1
        else:
            report["overrun"] += 1
    return report


def rebuild(rom: bytes | bytearray, entries: list[Entry], gfx_size: int | None = None) -> bytes:
    lengths = [entry.length for entry in entries]
    if any(length is None for length in lengths):
        raise ValueError("cannot rebuild while any stream length is unknown")
    known = [(entry, length) for entry, length in zip(entries, lengths, strict=True) if length]
    if gfx_size is None:
        gfx_size = known[-1][0].target + known[-1][1] if known else 0

    blob = bytearray(gfx_size)
    for entry, length in known:
        if entry.target + length > gfx_size:
            raise ValueError(f"stream {entry.index} runs past the end of a {gfx_size} byte blob")
        data = sdd1.decompress(rom, entry.source, length).data
        blob[entry.target : entry.target + length] = data
    return bytes(blob)


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: sdd1map.py <tagged-rom> <source-rom> [output.bin]",
            file=sys.stderr,
        )
        return 2

    tagged = dump.read(sys.argv[1])
    rom = dump.read(sys.argv[2])
    entries = build_map(tagged)
    if not entries:
        print("no S-DD1 markers found", file=sys.stderr)
        return 1

    declared = entries[-1].target
    print(f"  streams        {len(entries):,}")
    print(f"  source span    {entries[0].source:#09x} .. {entries[-1].source:#09x}")
    print(f"  graphics bytes {declared:,} before the final stream")
    modes: dict[int, int] = {}
    for entry in entries[:-1]:
        planes = sdd1.decompress(rom, entry.source, 2).bitplanes
        modes[planes] = modes.get(planes, 0) + 1
    print(f"  bitplane modes {modes}")

    report = audit(rom, entries)
    measured = report["measured"] or 1
    print("\n  packing check, does each stream end where the next begins")
    print(f"    packed  {report['packed']:>5}  {100 * report['packed'] / measured:5.2f}%")
    print(f"    padded  {report['padded']:>5}  {100 * report['padded'] / measured:5.2f}%")
    print(f"    overrun {report['overrun']:>5}  {100 * report['overrun'] / measured:5.2f}%")

    if len(sys.argv) > 3:
        complete = entries[:-1]
        blob = rebuild(rom, complete)
        Path(sys.argv[3]).write_bytes(blob)
        print(f"\n  wrote {sys.argv[3]} ({len(blob):,} bytes)")
        print("  note: the final stream is omitted, its length is not recoverable")
        print("        from the marker table alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
