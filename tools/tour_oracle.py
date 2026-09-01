import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent.parent


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


def run(
    name: str,
    extra: list[str],
    frames: int,
    execute: Callable[..., Any] = subprocess.run,
) -> dict[int, int]:
    """Run one tour pass and read every decompression it asked for.

    The reaching out is a parameter so the parsing, which is the part worth
    testing, can be driven against a recorded log rather than a container.
    """
    log = ROOT / "build" / "harvest" / f"tour-{name}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as handle:
        execute(
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
                "snes-street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
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


def main(
    rom: bytes | bytearray | None = None,
    table_path: Path | None = None,
    seen_path: Path | None = None,
    tour: Callable[..., dict[int, int]] = run,
    say: Callable[[str], None] = print,
    decode: Callable[..., Any] = sdd1.decompress,
) -> int:
    """Widen the table with everything the tour saw the cartridge ask for.

    The cartridge, both files and the tour itself are parameters, so the rule
    that decides what to add and what to grow can be driven without a container
    and without the ROM. An entry already held at that length is left alone; a
    shorter one is grown; anything that does not decode is skipped.
    """
    rom = dump.read(RETAIL) if rom is None else rom
    table_path = TABLE if table_path is None else table_path
    seen_path = ROOT / "build" / "harvest" / "tour-requests.txt" if seen_path is None else seen_path
    table: dict[int, int] = {}
    for line in table_path.read_text().splitlines():
        if not line.strip():
            continue
        written_source, written_length = line.split()
        table[int(written_source)] = int(written_length)

    seen: dict[int, int] = {}
    for name, extra, frames in PASSES:
        wanted = tour(name, extra, frames)
        seen.update({s: max(seen.get(s, 0), n) for s, n in wanted.items()})
        say(f"  {name}: {len(wanted)} addresses, {len(seen)} cumulative")

    added = grown = 0
    for source, length in sorted(seen.items()):
        try:
            produced = decode(rom, source, length)
        except (sdd1.TruncatedStream, IndexError, ValueError):
            say(f"    {source:#08x} does not decode, skipped")
            continue
        if len(produced.data) != length:
            continue
        if source not in table:
            table[source] = length
            added += 1
            say(f"    added    {source:#08x} length {length}")
        elif table[source] < length:
            say(f"    restored {source:#08x} to {length}")
            table[source] = length
            grown += 1

    table_path.write_text("\n".join(f"{s} {n}" for s, n in sorted(table.items())) + "\n")
    seen_path.write_text("\n".join(f"{s} {n}" for s, n in sorted(seen.items())) + "\n")
    say(
        f"  tour evidence {len(seen)} addresses; "
        f"table {len(table)} streams, {added} added, {grown} restored"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
