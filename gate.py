import importlib.util
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
rombuild = _load("rombuild")
jpstreams = _load("jpstreams")
usastreams = _load("usastreams")
requests_jp = _load("requests_jp")

SCAN_BUDGET = 64
WINDOW_BASE = 0xC0

RETAIL = {
    "usa": ROOT / "roms" / "sfa2-usa-final.sfc",
    "jp": ROOT / "roms" / "sfz2-jp-final.sfc",
}

TAGGED = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"


def table(region: str) -> list[tuple[int, int]]:
    return sorted(jpstreams.STREAMS if region == "jp" else usastreams.STREAMS)


def requests(region: str) -> dict[int, int]:
    return dict(requests_jp.REQUESTS) if region == "jp" else {}


def duplicates(entries: list[tuple[int, int]]) -> list[int]:
    seen = set()
    repeated = []
    for source, _ in entries:
        if source in seen:
            repeated.append(source)
        seen.add(source)
    return repeated


def undecodable(
    rom: bytes | bytearray,
    entries: list[tuple[int, int]],
    decode: Callable[..., Any] = sdd1.decompress,
) -> list[tuple[int, int, str]]:
    """Every entry in the table that the decompressor will not reproduce.

    The decompressor is a parameter so both ways an entry can be wrong, raising
    and returning the wrong length, can be driven without a cartridge that
    happens to contain one.
    """
    broken: list[tuple[int, int, str]] = []
    for source, length in entries:
        try:
            produced = decode(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            broken.append((source, length, "raised"))
            continue
        if len(produced.data) != length:
            broken.append((source, length, f"produced {len(produced.data)}"))
    return broken


def uncovered(
    entries: list[tuple[int, int]], wanted: dict[int, int]
) -> list[tuple[int, int, int | None]]:
    have = dict(entries)
    missing: list[tuple[int, int, int | None]] = []
    for address, length in sorted(wanted.items()):
        stored = have.get(address)
        if stored is None or stored < length:
            missing.append((address, length, stored))
    return missing


def worst_scan(entries: list[tuple[int, int]]) -> int:
    if not entries:
        return 0
    keys = [(WINDOW_BASE + (source >> 16), source & 0xFFFF) for source, _ in entries]
    slots = sdd1tables.allocate(keys)
    found = max((slot - address) & 0xFFFF for (_, address), slot in zip(keys, slots, strict=True))
    assert isinstance(found, int)
    return found


def check(
    region: str,
    entries: list[tuple[int, int]] | None = None,
    wanted: dict[int, int] | None = None,
    retail: Path | None = None,
    decode: Callable[..., Any] = sdd1.decompress,
) -> list[str]:
    """Everything wrong with one region's table, or an empty list.

    The table, the observed requests and the cartridge are parameters so each
    finding can be driven on its own. A missing cartridge is not a finding: the
    decode check is simply not run, and the others still are.

    The scan check is skipped when a source repeats, because two entries under
    one key have no placement at all and the allocator raises rather than
    returning a distance. The repeat is the thing to fix first, and reporting it
    is worth more than falling over on the way to the next check.
    """
    entries = table(region) if entries is None else entries
    findings = []

    repeated = duplicates(entries)
    if repeated:
        findings.append(f"{len(repeated)} repeated sources, first {repeated[0]:#08x}")

    retail = RETAIL[region] if retail is None else retail
    if retail.exists():
        broken = undecodable(dump.read(retail), entries, decode)
        if broken:
            source, length, why = broken[0]
            findings.append(
                f"{len(broken)} entries do not decode, first {source:#08x} length {length} {why}"
            )

    missing = uncovered(entries, requests(region) if wanted is None else wanted)
    if missing:
        address, length, stored = missing[0]
        findings.append(
            f"{len(missing)} observed requests are not covered, "
            f"first {address:#08x} needs {length}, table has {stored}"
        )

    if not repeated:
        worst = worst_scan(entries)
        if worst > SCAN_BUDGET:
            findings.append(f"worst key scan is {worst} slots against a budget of {SCAN_BUDGET}")

    return findings


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
    examine: Callable[[str], list[str]] = check,
    listing: Callable[[str], list[tuple[int, int]]] = table,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    wanted = argv[1:] or sorted(RETAIL)
    unknown = [region for region in wanted if region not in RETAIL]
    if unknown:
        complain(f"unknown region: {', '.join(unknown)}")
        return 2

    failed = False
    for region in wanted:
        findings = examine(region)
        entries = listing(region)
        if findings:
            failed = True
            say(f"  {region}: {len(entries):,} streams, FAIL")
            for finding in findings:
                say(f"    {finding}")
        else:
            say(f"  {region}: {len(entries):,} streams, ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
