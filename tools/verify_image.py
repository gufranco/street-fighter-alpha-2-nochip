import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump
mapper = hardware.load("mapper")
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jpstreams = load("jpstreams")
usastreams = load("usastreams")
gamefixes = load("gamefixes")

WINDOW_BASE = 0xC0
TABLE_BANK = 0x60
SCAN_BUDGET = 64


def window_read(image, banks, bank, address):
    return image[mapper.address_to_file(bank, address, banks)]


def resolve(image, banks, source):
    bank = WINDOW_BASE + (source >> 16)
    cursor = source & 0xFFFF
    for step in range(SCAN_BUDGET + 1):
        slot = (cursor + step) & 0xFFFF
        if window_read(image, banks, TABLE_BANK, slot) == bank:
            low = window_read(image, banks, TABLE_BANK + 1, slot)
            high = window_read(image, banks, TABLE_BANK + 2, slot)
            target = window_read(image, banks, TABLE_BANK + 3, slot)
            return (target << 16) | (high << 8) | low, step
    return None, None


def carries_game_fixes(path):
    return "-both-" in Path(path).name.lower()


def region_of(path):
    name = Path(path).name.lower()
    if name.startswith("jp-") or "sfz2" in name:
        return jpstreams.STREAMS, ROOT / "roms" / "sfz2-jp-final.sfc"
    if name.startswith("usa-") or "sfa2" in name:
        return usastreams.STREAMS, ROOT / "roms" / "sfa2-usa-final.sfc"
    raise ValueError(f"cannot tell which region {name} belongs to")


def main(argv: list[str]) -> int:
    image_path = Path(argv[1]) if len(argv) > 1 else ROOT / "build" / "all" / "jp-both-free.sfc"
    streams, retail_path = region_of(image_path)
    retail = dump.read(retail_path)
    if carries_game_fixes(image_path):
        retail = gamefixes.apply(retail)
    image = dump.read(image_path)
    banks = len(image) // mapper.BANK

    wrong = []
    unresolved = []
    for source, length in streams:
        destination, _ = resolve(image, banks, source)
        if destination is None:
            unresolved.append(source)
            continue
        want = sdd1.decompress(retail, source, length).data
        got = bytes(
            window_read(image, banks, (destination + offset) >> 16, (destination + offset) & 0xFFFF)
            for offset in range(len(want))
        )
        if got != want:
            first = next(i for i, (a, b) in enumerate(zip(got, want, strict=True)) if a != b)
            wrong.append((source, destination, first))

    print(f"  image {image_path.name}, {len(streams):,} streams")
    print(f"  unresolved lookups: {len(unresolved)}")
    for source in unresolved[:10]:
        print(f"     {source:#08x}")
    print(f"  streams whose bytes in the image are wrong: {len(wrong)}")
    for source, destination, first in wrong[:10]:
        print(f"     {source:#08x} at {destination:#08x}, first bad byte {first}")
    return 1 if wrong or unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
