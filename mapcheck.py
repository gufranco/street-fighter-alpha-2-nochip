import importlib.util
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sdd1tables = _load("sdd1tables")
jpstreams = _load("jpstreams")
usastreams = _load("usastreams")

WINDOW_BASE = 0xC0
SCAN_BUDGET = 64

RECOVERED_JP = (
    0x13CB9F,
    0x15E82D,
    0x1A19F1,
    0x1A2243,
    0x1A44B7,
    0x1A86EC,
    0x1A9E7D,
    0x1AB840,
    0x1AC0F5,
    0x1AC3CF,
    0x1ACCD1,
    0x192B62,
    0x15D7FD,
)


def table_for(path: str | Path) -> Any:
    name = Path(path).name.lower()
    if "sfz2" in name or name.startswith("jp-"):
        return jpstreams.STREAMS
    if "sfa2" in name or name.startswith("usa-"):
        return usastreams.STREAMS
    raise ValueError(f"cannot tell which region {name} belongs to")


def load(table: Any = None) -> list[tuple[int, int]]:
    entries = sorted(jpstreams.STREAMS if table is None else table)
    for source, length in entries:
        if length <= 0:
            raise ValueError(f"stream {source:#08x} has a non-positive length {length}")
    return entries


def duplicate_sources(entries: list[tuple[int, int]]) -> list[int]:
    seen = set()
    repeated = []
    for source, _ in entries:
        if source in seen:
            repeated.append(source)
        seen.add(source)
    return repeated


def window_key(source: int) -> tuple[int, int]:
    return WINDOW_BASE + (source >> 16), source & 0xFFFF


def undecodable(rom: bytes | bytearray, entries: list[tuple[int, int]]) -> list[int]:
    broken = []
    for source, length in entries:
        try:
            sdd1.decompress(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            broken.append(source)
    return broken


def scan_cost(entries: list[tuple[int, int]]) -> tuple[int, int]:
    if not entries:
        return 0, 0
    keys = [window_key(source) for source, _ in entries]
    slots = sdd1tables.allocate(keys)
    distances = [(slot - addr) & 0xFFFF for (_, addr), slot in zip(keys, slots, strict=True)]
    return int(statistics.median(distances)), max(distances)


def report(
    rom_path: str | Path,
    say: Callable[[str], None] = print,
    read: Callable[[Path], Any] | None = None,
    entries: list[tuple[int, int]] | None = None,
) -> int:
    """Everything wrong with one cartridge's table, and whether that is a failure.

    The stream, the cartridge reader and the table are parameters, so each
    finding can be driven without a dump on the machine.

    The scan is not measured when a source repeats, because two entries under
    one key have no placement and the allocator raises rather than returning a
    distance. The repeat already fails the run, and reporting it is worth more
    than falling over on the way to the verdict.
    """
    read = dump.read if read is None else read
    rom = read(Path(rom_path))
    entries = load(table_for(rom_path)) if entries is None else entries

    repeated = duplicate_sources(entries)
    broken = undecodable(rom, entries)
    median, worst = (0, 0) if repeated else scan_cost(entries)

    say(f"  streams        {len(entries):,}")
    say(f"  duplicates     {len(repeated)}")
    say(f"  undecodable    {len(broken)}")
    say(f"  scan distance  median {median}, worst {worst} (budget {SCAN_BUDGET})")

    failed = bool(repeated) or bool(broken) or worst > SCAN_BUDGET
    say("  RESULT         " + ("FAIL" if failed else "OK"))
    return 1 if failed else 0


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
    examine: Callable[..., int] = report,
) -> int:
    """The command line, with both streams and the check passed in."""
    complain = say if complain is None else complain
    if len(argv) != 2:
        complain("usage: mapcheck.py <rom>")
        return 2
    return examine(argv[1], say)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
