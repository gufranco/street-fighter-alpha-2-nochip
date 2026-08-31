import importlib.util
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


def table(region):
    return sorted(jpstreams.STREAMS if region == "jp" else usastreams.STREAMS)


def requests(region):
    return dict(requests_jp.REQUESTS) if region == "jp" else {}


def duplicates(entries):
    seen = set()
    repeated = []
    for source, _ in entries:
        if source in seen:
            repeated.append(source)
        seen.add(source)
    return repeated


def undecodable(rom, entries):
    broken = []
    for source, length in entries:
        try:
            produced = sdd1.decompress(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            broken.append((source, length, "raised"))
            continue
        if len(produced.data) != length:
            broken.append((source, length, f"produced {len(produced.data)}"))
    return broken


def uncovered(entries, wanted):
    have = dict(entries)
    missing = []
    for address, length in sorted(wanted.items()):
        stored = have.get(address)
        if stored is None or stored < length:
            missing.append((address, length, stored))
    return missing


def worst_scan(entries):
    if not entries:
        return 0
    keys = [(WINDOW_BASE + (source >> 16), source & 0xFFFF) for source, _ in entries]
    slots = sdd1tables.allocate(keys)
    return max((slot - address) & 0xFFFF for (_, address), slot in zip(keys, slots, strict=True))


def check(region):
    entries = table(region)
    findings = []

    repeated = duplicates(entries)
    if repeated:
        findings.append(f"{len(repeated)} repeated sources, first {repeated[0]:#08x}")

    retail = RETAIL[region]
    if retail.exists():
        broken = undecodable(dump.read(retail), entries)
        if broken:
            source, length, why = broken[0]
            findings.append(
                f"{len(broken)} entries do not decode, first {source:#08x} length {length} {why}"
            )

    missing = uncovered(entries, requests(region))
    if missing:
        address, length, stored = missing[0]
        findings.append(
            f"{len(missing)} observed requests are not covered, "
            f"first {address:#08x} needs {length}, table has {stored}"
        )

    worst = worst_scan(entries)
    if worst > SCAN_BUDGET:
        findings.append(f"worst key scan is {worst} slots against a budget of {SCAN_BUDGET}")

    return findings


def main(argv, say=print, complain=None):
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    wanted = argv[1:] or sorted(RETAIL)
    unknown = [region for region in wanted if region not in RETAIL]
    if unknown:
        complain(f"unknown region: {', '.join(unknown)}")
        return 2

    failed = False
    for region in wanted:
        findings = check(region)
        entries = table(region)
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
