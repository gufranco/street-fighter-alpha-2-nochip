import importlib.util
import statistics
import sys
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


def table_for(path):
    name = Path(path).name.lower()
    if "sfz2" in name or name.startswith("jp-"):
        return jpstreams.STREAMS
    if "sfa2" in name or name.startswith("usa-"):
        return usastreams.STREAMS
    raise ValueError(f"cannot tell which region {name} belongs to")


def load(table=None):
    entries = sorted(jpstreams.STREAMS if table is None else table)
    for source, length in entries:
        if length <= 0:
            raise ValueError(f"stream {source:#08x} has a non-positive length {length}")
    return entries


def duplicate_sources(entries):
    seen = set()
    repeated = []
    for source, _ in entries:
        if source in seen:
            repeated.append(source)
        seen.add(source)
    return repeated


def window_key(source):
    return WINDOW_BASE + (source >> 16), source & 0xFFFF


def undecodable(rom, entries):
    broken = []
    for source, length in entries:
        try:
            sdd1.decompress(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            broken.append(source)
    return broken


def scan_cost(entries):
    if not entries:
        return 0, 0
    keys = [window_key(source) for source, _ in entries]
    slots = sdd1tables.allocate(keys)
    distances = [(slot - addr) & 0xFFFF for (_, addr), slot in zip(keys, slots, strict=True)]
    return int(statistics.median(distances)), max(distances)


def report(rom_path):
    rom = dump.read(Path(rom_path))
    entries = load(table_for(rom_path))

    repeated = duplicate_sources(entries)
    broken = undecodable(rom, entries)
    median, worst = scan_cost(entries)

    print(f"  streams        {len(entries):,}")
    print(f"  duplicates     {len(repeated)}")
    print(f"  undecodable    {len(broken)}")
    print(f"  scan distance  median {median}, worst {worst} (budget {SCAN_BUDGET})")

    failed = bool(repeated) or bool(broken) or worst > SCAN_BUDGET
    print("  RESULT         " + ("FAIL" if failed else "OK"))
    return 1 if failed else 0


def main(argv, say=print, complain=None):
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    if len(argv) != 2:
        complain("usage: mapcheck.py <rom>")
        return 2
    return report(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
