import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump
rewrite = hardware.load("romimage").rewrite
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rombuild = load("rombuild")
spcfast = load("spcfast")
shinakuma = load("shinakuma")

RETAIL = ROOT / "roms" / "sfz2-jp-final.sfc"
OUT = ROOT / "build" / "harvest"
FRAMES = 30000
SCAN_BUDGET = 64
WINDOW_BASE = 0xC0

SCAN = re.compile(
    r"^SCAN addr=(\w{4}) "
    r"ch0=(\w\w):(\w{4}):(\d+):fixed\d "
    r"ch1=(\w\w):(\w{4}):(\d+):fixed\d "
    r"ch7=(\w\w):(\w{4}):(\d+):fixed\d"
)
SCANLEN = re.compile(r"^SCANLEN addr=(\w{4}) steps=(\d+)")


def variants(retail: bytes | bytearray) -> dict[str, bytes]:
    fast = spcfast.apply(retail)
    return {
        "base": retail,
        "spc": fast,
        "sa": shinakuma.apply(retail),
        "both": shinakuma.apply(fast),
    }


def build_image(
    cart: bytes | bytearray,
    table: dict[int, int],
    name: str,
    execute: Callable[..., Any] = subprocess.run,
) -> Path:
    """One variant assembled and packed, ready to be driven.

    The shelling out is passed in so a test can watch what was asked for without
    a container being present. Everything either side of it, the staging, the
    repack and the write, runs for real.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    staged = OUT / f"jp-{name}-cart.sfc"
    staged.write_bytes(cart)
    output = f"jp-{name}-harvest.sfc"
    execute(
        [
            sys.executable,
            "build.py",
            "asm/sdd1-bypass-jp.asm",
            str(staged.relative_to(ROOT)),
            output,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    produced = ROOT / "asm" / output
    bypass = dump.read(produced)
    produced.unlink()

    entries = rombuild.entries_from_map({str(source): length for source, length in table.items()})
    image = rombuild.build(bypass, entries).image
    free = OUT / f"jp-{name}-free.sfc"
    free.write_bytes(rewrite.declare_rom_only(image))
    return free


def scan_log(image: Path, execute: Callable[..., Any] = subprocess.run) -> list[str]:
    """What the emulator reported while driving one image, as lines."""
    log = OUT / f"{image.stem}-scan.txt"
    with log.open("wb") as handle:
        execute(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "-e",
                "SFSCAN=1",
                "-e",
                "SFSCANLEN=1",
                "-e",
                "SFGRID=1",
                "-v",
                f"{ROOT}:/work",
                "snes-street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
                str(image.relative_to(ROOT)),
                str(FRAMES),
                "-2",
            ],
            stdout=handle,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return log.read_text(errors="replace").splitlines()


def missed_streams(lines: list[str]) -> dict[int, int]:
    wanted: dict[int, int] = {}
    for index, line in enumerate(lines):
        found = SCANLEN.match(line)
        if not found or int(found.group(2)) <= SCAN_BUDGET:
            continue
        address = found.group(1)
        for back in range(max(0, index - 4), index + 1):
            scan = SCAN.match(lines[back])
            if not scan or scan.group(1) != address:
                continue
            channels = (
                (scan.group(2), scan.group(3), int(scan.group(4))),
                (scan.group(5), scan.group(6), int(scan.group(7))),
                (scan.group(8), scan.group(9), int(scan.group(10))),
            )
            for bank, addr, count in channels:
                if addr == address and count > 0 and int(bank, 16) >= WINDOW_BASE:
                    source = (int(bank, 16) - WINDOW_BASE) * 0x10000 + int(addr, 16)
                    wanted[source] = max(wanted.get(source, 0), count)
            break
    return wanted


def compressed_end(rom: bytes | bytearray, source: int, length: int) -> int:
    end = sdd1.decompress(rom, source, length).end
    assert isinstance(end, int)
    return end


def shorten_to(rom: bytes | bytearray, source: int, length: int, boundary: int) -> int | None:
    low, high = 1, length
    best = None
    while low <= high:
        middle = (low + high) // 2
        end = compressed_end(rom, source, middle)
        if end <= boundary:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best is None or compressed_end(rom, source, best) != boundary:
        return None
    return best


def absorb(
    rom: bytes | bytearray,
    table: dict[int, int],
    source: int,
    length: int,
    say: Callable[[str], None] = print,
) -> bool:
    for other in sorted(table):
        if other >= source:
            break
        end = compressed_end(rom, other, table[other])
        if other < source < end:
            trimmed = shorten_to(rom, other, table[other], source)
            if trimmed is None:
                say(f"    cannot trim {other:#08x} to end at {source:#08x}")
                return False
            say(f"    trimmed {other:#08x} from {table[other]} to {trimmed} bytes")
            table[other] = trimmed
    table[source] = max(table.get(source, 0), length)
    return True


def main(
    rom: bytes | bytearray | None = None,
    table: dict[int, int] | None = None,
    carts: dict[str, bytes] | None = None,
    build: Callable[..., Path] = build_image,
    scan: Callable[..., list[str]] = scan_log,
    say: Callable[[str], None] = print,
    decode: Callable[..., Any] = sdd1.decompress,
    rounds: int = 25,
) -> dict[int, int]:
    """Drive every variant until a round finds nothing new.

    Each collaborator is passed in so the loop can be run without a cartridge or
    a container. The convergence rule is the thing worth testing and it is pure:
    a round that adds nothing stops, and the round cap is the backstop under it.
    """
    rom = dump.read(RETAIL) if rom is None else rom
    table = dict(load("jpstreams").STREAMS) if table is None else table
    carts = variants(rom) if carts is None else carts

    for iteration in range(1, rounds + 1):
        added = 0
        for name, cart in carts.items():
            image = build(cart, table, name)
            wanted = missed_streams(scan(image))
            for source, length in sorted(wanted.items()):
                if table.get(source, 0) >= length:
                    continue
                try:
                    produced = decode(rom, source, length)
                except (sdd1.TruncatedStream, IndexError, ValueError) as error:
                    say(f"    {source:#08x} n={length} does not decode: {error}")
                    continue
                if len(produced.data) != length:
                    say(f"    {source:#08x} n={length} produced {len(produced.data)}")
                    continue
                if absorb(rom, table, source, length, say):
                    added += 1
                    say(f"    {name}: added {source:#08x} length {length}")
            say(f"  iteration {iteration} {name}: {len(wanted)} missing")
        if added == 0:
            say(f"  converged after {iteration} iterations with {len(table)} streams")
            return table
        say(f"  iteration {iteration}: {added} added, {len(table)} streams")
    return table


if __name__ == "__main__":
    result = main()
    lines = [f"{source} {length}" for source, length in sorted(result.items())]
    (ROOT / "build" / "harvest" / "table.txt").write_text("\n".join(lines) + "\n")
    print(f"  wrote {len(result)} entries")
