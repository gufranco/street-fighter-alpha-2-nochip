import sys
import zlib
from collections import namedtuple
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


def window_hash(value: bytes | bytearray, bits: int) -> int:
    return zlib.crc32(value) & ((1 << bits) - 1)


def build_bitmap(data: bytes | bytearray, window: int, bits: int) -> bytearray:
    bitmap = bytearray((1 << bits) // 8)
    slot_of = window_hash
    for i in range(len(data) - window + 1):
        slot = slot_of(data[i : i + window], bits)
        bitmap[slot >> 3] |= 1 << (slot & 7)
    return bitmap


def probe(bitmap: bytearray, value: bytes | bytearray, bits: int) -> bool:
    slot = window_hash(value, bits)
    return bool(bitmap[slot >> 3] >> (slot & 7) & 1)


def is_distinctive(blob: bytes | bytearray, minimum: int = MIN_DISTINCT) -> bool:
    return len(set(blob)) >= minimum


def extend(
    source: bytes | bytearray,
    reference: bytes | bytearray,
    offset: int,
    target: int,
    limit: int = EXTEND_LENGTH,
) -> int:
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


def find_streams(
    source: bytes | bytearray,
    reference: bytes | bytearray,
    start: int = 0,
    stop: int | None = None,
    progress: Any = None,
    probe_bits: int = PROBE_BITS,
    confirm_bits: int = CONFIRM_BITS,
) -> list[Any]:
    """Every offset in the source whose decompressed output appears in the reference.

    Two bitmaps narrow the search before anything is decompressed twice. Their
    widths are parameters because they are a tuning knob: a narrow one reports
    more false positives, which the search then has to reject by looking the
    output up in the reference for real.
    """
    stop = len(source) if stop is None else stop
    probe_map = build_bitmap(reference, PROBE_LENGTH, probe_bits)
    confirm_map = build_bitmap(reference, CONFIRM_LENGTH, confirm_bits)
    decompress = sdd1.decompress
    truncated = sdd1.TruncatedStream
    hits: list[Any] = []

    for offset in range(start, stop):
        if progress is not None and offset % 250000 == 0:
            progress(offset, len(hits))
        try:
            head = decompress(source, offset, PROBE_LENGTH).data
        except truncated:
            continue
        if not is_distinctive(head, MIN_PROBE_DISTINCT):
            continue
        if not probe(probe_map, head, probe_bits):
            continue
        try:
            blob = decompress(source, offset, CONFIRM_LENGTH).data
        except truncated:
            continue
        if not is_distinctive(blob):
            continue
        if not probe(confirm_map, blob, confirm_bits):
            continue
        target = reference.find(blob)
        if target < 0:
            continue
        hits.append(Hit(offset, target, extend(source, reference, offset, target)))

    return hits


def chains(hits: list[Any], tolerance: int = 2) -> list[Any]:
    ordered = sorted(hits, key=lambda hit: hit.source)
    runs: list[Any] = []
    current: list[Any] = []
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


def main(
    argv: list[str] | None = None,
    read: Callable[[Any], Any] | None = None,
    say: Callable[..., None] = print,
) -> int:
    """Find every compressed stream in one cartridge whose output is in another.

    The arguments and the cartridge reader are parameters, so the refusal and a
    whole scan can be driven without either dump on the machine.
    """
    argv = sys.argv if argv is None else argv
    read = dump.read if read is None else read
    if len(argv) < 3:
        say(
            "usage: sdd1find.py <source-rom> <reference-rom> [start] [stop]",
            file=sys.stderr,
        )
        return 2

    source = read(argv[1])
    reference = read(argv[2])
    start = int(argv[3], 0) if len(argv) > 3 else 0
    stop = int(argv[4], 0) if len(argv) > 4 else len(source)

    say(f"  source    {argv[1]} {len(source):,} bytes")
    say(f"  reference {argv[2]} {len(reference):,} bytes")
    say(f"  scanning {start:#x}..{stop:#x}")

    def report(offset: int, found: int) -> None:
        say(f"    at {offset:#09x}  hits so far {found}")

    hits = find_streams(source, reference, start, stop, progress=report)
    say(f"\n  confirmed streams: {len(hits)}")

    longest = sorted(hits, key=lambda hit: -hit.length)[:20]
    say("\n  deepest confirmations")
    for hit in longest:
        say(
            f"    source {hit.source:#09x} -> reference {hit.target:#09x}  "
            f"{hit.length} bytes verbatim"
        )

    runs = [run for run in chains(hits) if len(run) > 1]
    runs.sort(key=len, reverse=True)
    say(f"\n  contiguous chains of streams: {len(runs)}")
    for run in runs[:10]:
        say(
            f"    {len(run):>4} streams  source {run[0].source:#09x} "
            f"-> reference {run[0].target:#09x}..{run[-1].target + run[-1].length:#09x}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
