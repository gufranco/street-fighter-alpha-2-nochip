import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump
mapper = hardware.load("mapper")
sdd1 = hardware.load("sdd1")

import sdd1map  # noqa: E402
import sdd1tables  # noqa: E402

IMAGE_BANKS = 192
IMAGE_SIZE = IMAGE_BANKS * mapper.BANK

TABLE_BANK = 0x60
TABLE_COUNT = 4

DATA_BANK_FIRST = 0x40
DATA_BANK_LAST = 0x7D
WRAM_BANKS = (0x7E, 0x7F)

WINDOW_BASE = 0xC0
LOROM_BANKS = 0x40
LOROM_MIRROR_BASE = 0x80
ORIGINAL_SIZE = 0x400000

MIN_REGION = 0x1000
READ_AHEAD = 1

FINAL_STREAM_LENGTH = mapper.BANK

Region = namedtuple("Region", "bank start end")
Result = namedtuple("Result", "image destinations tables regions")


class AllocationError(Exception):
    pass


def load_entries(tagged):
    entries = sdd1map.build_map(tagged)
    if not entries or entries[-1].length is not None:
        return entries
    return sdd1map.build_map(tagged, gfx_size=entries[-1].target + FINAL_STREAM_LENGTH)


def entries_from_map(mapping):
    ordered = sorted((int(source), length) for source, length in mapping.items())
    return [
        sdd1map.Entry(index=index, source=source, target=None, length=length)
        for index, (source, length) in enumerate(ordered)
    ]


def data_bank_regions():
    reserved = set(range(TABLE_BANK, TABLE_BANK + TABLE_COUNT)) | set(WRAM_BANKS)
    return [
        Region(bank, 0x0000, mapper.BANK)
        for bank in range(DATA_BANK_FIRST, DATA_BANK_LAST + 1)
        if bank not in reserved
    ]


def spans_of(extra):
    return [
        Region(address >> 16, address & 0xFFFF, (address & 0xFFFF) + len(data))
        for address, data in extra
    ]


def subtract(regions, taken):
    out = []
    for region in regions:
        pieces = [(region.start, region.end)]
        for hole in taken:
            if hole.bank != region.bank:
                continue
            nxt = []
            for start, end in pieces:
                if hole.end <= start or hole.start >= end:
                    nxt.append((start, end))
                    continue
                if start < hole.start:
                    nxt.append((start, hole.start))
                if hole.end < end:
                    nxt.append((hole.end, end))
            pieces = nxt
        out.extend(Region(region.bank, start, end) for start, end in pieces if end > start)
    return out


def reclaimed_regions(rom, entries):
    spans = []
    for entry in entries:
        if entry.length is None:
            continue
        consumed = sdd1.decompress(rom, entry.source, entry.length).end - READ_AHEAD
        end = min(consumed, (entry.source | 0xFFFF) + 1)
        if end <= entry.source:
            continue
        spans.append(
            Region(
                WINDOW_BASE + (entry.source >> 16),
                entry.source & 0xFFFF,
                end - (entry.source & ~0xFFFF),
            )
        )
    return [r for r in merge(spans) if r.end - r.start >= MIN_REGION]


def merge(regions):
    merged = []
    for region in sorted(regions, key=lambda r: (r.bank, r.start)):
        if merged and merged[-1].bank == region.bank and merged[-1].end >= region.start:
            last = merged[-1]
            merged[-1] = Region(last.bank, last.start, max(last.end, region.end))
        else:
            merged.append(region)
    return merged


def allocate(sizes, regions):
    free = sorted(merge(regions), key=lambda region: (region.bank, region.start))
    if not free:
        raise AllocationError("no free regions offered")

    placed = {}
    cursor = [region.start for region in free]

    for key, size in sizes:
        for index, region in enumerate(free):
            if region.end - cursor[index] >= size:
                placed[key] = (region.bank << 16) | cursor[index]
                cursor[index] += size
                break
        else:
            raise AllocationError(
                f"no region can hold {size} bytes for stream {key}; "
                f"largest gap is {max(r.end - cursor[i] for i, r in enumerate(free))}"
            )

    return placed


def place(image, bank, addr, data, banks):
    written = 0
    while written < len(data):
        edge = mapper.HALF if addr < mapper.HALF else mapper.BANK
        chunk = min(len(data) - written, edge - addr)
        offset = mapper.address_to_file(bank, addr, banks)
        image[offset : offset + chunk] = data[written : written + chunk]
        written += chunk
        addr += chunk
        if addr >= mapper.BANK:
            addr = 0
            bank += 1


def build(rom, entries, image_banks=IMAGE_BANKS, extra=()):
    if len(rom) != ORIGINAL_SIZE:
        raise ValueError(f"expected a {ORIGINAL_SIZE} byte rom, got {len(rom)}")

    regions = subtract(data_bank_regions(), spans_of(extra)) + reclaimed_regions(rom, entries)
    ordered = entries[-1:] + entries[:-1] if len(entries) > 1 else list(entries)
    destinations = allocate([(e.index, e.length) for e in ordered], regions)
    tables = sdd1tables.build([(e, destinations[e.index]) for e in entries])

    image = bytearray(image_banks * mapper.BANK)

    for bank in range(LOROM_BANKS):
        source = bank * mapper.HALF
        half = rom[source : source + mapper.HALF]
        place(image, bank, mapper.HALF, half, image_banks)
        place(image, LOROM_MIRROR_BASE + bank, mapper.HALF, half, image_banks)

    for n in range(ORIGINAL_SIZE // mapper.BANK):
        place(
            image,
            WINDOW_BASE + n,
            0x0000,
            rom[n * mapper.BANK : (n + 1) * mapper.BANK],
            image_banks,
        )

    for index, part in enumerate((tables.key, tables.dest_low, tables.dest_high, tables.dest_bank)):
        place(image, TABLE_BANK + index, 0x0000, part, image_banks)

    for entry in entries:
        destination = destinations[entry.index]
        place(
            image,
            destination >> 16,
            destination & 0xFFFF,
            sdd1.decompress(rom, entry.source, entry.length).data,
            image_banks,
        )

    for address, data in extra:
        place(image, address >> 16, address & 0xFFFF, data, image_banks)

    return Result(bytes(image), destinations, tables, regions)


def main() -> int:
    if len(sys.argv) < 4:
        print(
            "usage: rombuild.py <patched-rom> <tagged-rom> <output.sfc>",
            file=sys.stderr,
        )
        return 2

    rom = dump.read(sys.argv[1])
    entries = load_entries(dump.read(sys.argv[2]))
    print(f"  streams   {len(entries):,}")

    result = build(rom, entries)
    graphics = sum(e.length for e in entries)
    banks = {result.destinations[e.index] >> 16 for e in entries}
    print(f"  graphics  {graphics:,} bytes across {len(banks)} banks")
    print(f"  image     {len(result.image):,} bytes ({len(result.image) * 8 // 1048576} Mbit)")

    Path(sys.argv[3]).write_bytes(result.image)
    print(f"  wrote {sys.argv[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
