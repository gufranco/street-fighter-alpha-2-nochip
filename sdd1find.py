import sys
import zlib
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


PROBE_LENGTH = 8
PROBE_BITS = 25
MIN_PROBE_DISTINCT = 4
CONFIRM_LENGTH = 32
CONFIRM_BITS = 28
EXTEND_LENGTH = 4096
MIN_DISTINCT = 10

Hit = namedtuple("Hit", "source target length")


def window_hash(value, bits):
    return zlib.crc32(value) & ((1 << bits) - 1)


def build_bitmap(data, window, bits):
    bitmap = bytearray((1 << bits) // 8)
    slot_of = window_hash
    for i in range(len(data) - window + 1):
        slot = slot_of(data[i : i + window], bits)
        bitmap[slot >> 3] |= 1 << (slot & 7)
    return bitmap


def probe(bitmap, value, bits):
    slot = window_hash(value, bits)
    return bool(bitmap[slot >> 3] >> (slot & 7) & 1)


def is_distinctive(blob, minimum=MIN_DISTINCT):
    return len(set(blob)) >= minimum


def extend(source, reference, offset, target, limit=EXTEND_LENGTH):
    confirmed = CONFIRM_LENGTH
    length = CONFIRM_LENGTH
    while length < limit:
        length = min(length * 2, limit)
        try:
            blob = sdd1.decompress(source, offset, length).data
        except sdd1.TruncatedStream:
            break
        if reference[target : target + len(blob)] != blob:
            break
        confirmed = length
    return confirmed


def find_streams(source, reference, start=0, stop=None, progress=None):
    stop = len(source) if stop is None else stop
    probe_map = build_bitmap(reference, PROBE_LENGTH, PROBE_BITS)
    confirm_map = build_bitmap(reference, CONFIRM_LENGTH, CONFIRM_BITS)
    decompress = sdd1.decompress
    truncated = sdd1.TruncatedStream
    hits = []

    for offset in range(start, stop):
        if progress is not None and offset % 250000 == 0:
            progress(offset, len(hits))
        try:
            head = decompress(source, offset, PROBE_LENGTH).data
        except truncated:
            continue
        if not is_distinctive(head, MIN_PROBE_DISTINCT):
            continue
        if not probe(probe_map, head, PROBE_BITS):
            continue
        try:
            blob = decompress(source, offset, CONFIRM_LENGTH).data
        except truncated:
            continue
        if not is_distinctive(blob):
            continue
        if not probe(confirm_map, blob, CONFIRM_BITS):
            continue
        target = reference.find(blob)
        if target < 0:
            continue
        hits.append(Hit(offset, target, extend(source, reference, offset, target)))

    return hits


def chains(hits, tolerance=2):
    ordered = sorted(hits, key=lambda hit: hit.source)
    runs = []
    current = []
    for hit in ordered:
        if current:
            last = current[-1]
            follows = abs(hit.target - (last.target + last.length)) <= tolerance
            if not follows:
                runs.append(current)
                current = []
        current.append(hit)
    if current:
        runs.append(current)
    return runs


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: sdd1find.py <source-rom> <reference-rom> [start] [stop]",
            file=sys.stderr,
        )
        return 2

    source = dump.read(sys.argv[1])
    reference = dump.read(sys.argv[2])
    start = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0
    stop = int(sys.argv[4], 0) if len(sys.argv) > 4 else len(source)

    print(f"  source    {sys.argv[1]} {len(source):,} bytes")
    print(f"  reference {sys.argv[2]} {len(reference):,} bytes")
    print(f"  scanning {start:#x}..{stop:#x}", flush=True)

    def report(offset, found):
        print(f"    at {offset:#09x}  hits so far {found}", flush=True)

    hits = find_streams(source, reference, start, stop, progress=report)
    print(f"\n  confirmed streams: {len(hits)}")

    longest = sorted(hits, key=lambda hit: -hit.length)[:20]
    print("\n  deepest confirmations")
    for hit in longest:
        print(
            f"    source {hit.source:#09x} -> reference {hit.target:#09x}  "
            f"{hit.length} bytes verbatim"
        )

    runs = [run for run in chains(hits) if len(run) > 1]
    runs.sort(key=len, reverse=True)
    print(f"\n  contiguous chains of streams: {len(runs)}")
    for run in runs[:10]:
        print(
            f"    {len(run):>4} streams  source {run[0].source:#09x} "
            f"-> reference {run[0].target:#09x}..{run[-1].target + run[-1].length:#09x}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
