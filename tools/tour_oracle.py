import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = "build/all/jp-sa-cart.sfc"
RETAIL = ROOT / "roms" / "sfz2-jp-final.sfc"
TABLE = ROOT / "build" / "harvest" / "table.txt"
DMA = re.compile(r"^DMA ch=\d src=(\w\w):(\w{4}) n=(\d+) b=\w\w fixed=1")
WINDOW_BASE = 0xC0

PASSES = (
    ("budget7200", ["-e", "SFTOURBUDGET=7200"], 129600),
    ("budget9000", ["-e", "SFTOURBUDGET=9000"], 162000),
    ("budget5400", ["-e", "SFTOURBUDGET=5400"], 97200),
    ("confirm7200", ["-e", "SFTOURBUDGET=7200", "-e", "SFTOURCONFIRM=1"], 129600),
    ("confirm12000", ["-e", "SFTOURBUDGET=12000", "-e", "SFTOURCONFIRM=1"], 216000),
    ("long18000", ["-e", "SFTOURBUDGET=18000"], 324000),
)


def run(name: str, extra: list[str], frames: int) -> dict[int, int]:
    log = ROOT / "build" / "harvest" / f"tour-{name}.txt"
    with log.open("wb") as handle:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "-e",
                "SFTOUR=1",
                "-e",
                "SFDMA=1",
                *extra,
                "-v",
                f"{ROOT}:/work",
                "street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
                ORACLE,
                str(frames),
                "-1",
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return requests(log.read_text(errors="replace").splitlines())


def requests(lines: list[str]) -> dict[int, int]:
    """Every decompression the cartridge asked for, and the largest it asked for.

    Only transfers whose source address never advances are decompressions, which
    is the condition the chip works under, and only sources inside the cartridge
    window are cartridge data. A transfer from below the window is the game
    moving something else, and counting it would put fiction into the table.
    """
    wanted: dict[int, int] = {}
    for line in lines:
        found = DMA.match(line)
        if not found:
            continue
        bank = int(found.group(1), 16)
        if bank < WINDOW_BASE:
            continue
        source = (bank - WINDOW_BASE) * 0x10000 + int(found.group(2), 16)
        wanted[source] = max(wanted.get(source, 0), int(found.group(3)))
    return wanted


def main() -> int:
    rom = dump.read(RETAIL)
    table: dict[int, int] = {}
    for line in TABLE.read_text().splitlines():
        written_source, written_length = line.split()
        table[int(written_source)] = int(written_length)

    seen: dict[int, int] = {}
    for name, extra, frames in PASSES:
        wanted = run(name, extra, frames)
        seen.update({s: max(seen.get(s, 0), n) for s, n in wanted.items()})
        print(f"  {name}: {len(wanted)} addresses, {len(seen)} cumulative", flush=True)

    added = grown = 0
    for source, length in sorted(seen.items()):
        try:
            produced = sdd1.decompress(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            print(f"    {source:#08x} does not decode, skipped", flush=True)
            continue
        if len(produced.data) != length:
            continue
        if source not in table:
            table[source] = length
            added += 1
            print(f"    added    {source:#08x} length {length}", flush=True)
        elif table[source] < length:
            print(f"    restored {source:#08x} to {length}", flush=True)
            table[source] = length
            grown += 1

    TABLE.write_text("\n".join(f"{s} {n}" for s, n in sorted(table.items())) + "\n")
    (ROOT / "build" / "harvest" / "tour-requests.txt").write_text(
        "\n".join(f"{s} {n}" for s, n in sorted(seen.items())) + "\n"
    )
    print(
        f"  tour evidence {len(seen)} addresses; table {len(table)} streams, {added} added, {grown} restored"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
