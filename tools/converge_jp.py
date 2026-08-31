import importlib.util
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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
TABLE = ROOT / "build" / "harvest" / "table.txt"
OUT = ROOT / "build" / "converge"
WINDOW_BASE = 0xC0
SCAN_BUDGET = 64
WORKERS = 5

SCAN = re.compile(
    r"^SCAN addr=(\w{4}) "
    r"ch0=(\w\w):(\w{4}):(\d+):fixed\d "
    r"ch1=(\w\w):(\w{4}):(\d+):fixed\d "
    r"ch7=(\w\w):(\w{4}):(\d+):fixed\d"
)

PASSES = (
    ("tour18000", ["-e", "SFTOUR=1", "-e", "SFTOURBUDGET=18000"], 216000),
    ("tour9000", ["-e", "SFTOUR=1", "-e", "SFTOURBUDGET=9000"], 162000),
    (
        "tourconfirm",
        ["-e", "SFTOUR=1", "-e", "SFTOURBUDGET=12000", "-e", "SFTOURCONFIRM=1"],
        216000,
    ),
    ("force", ["-e", "SFFORCE=1"], 60000),
    ("grid", ["-e", "SFGRID=1", "-e", "SFSETTLE=200"], 60000),
)


def read_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for line in TABLE.read_text().splitlines():
        source, length = line.split()
        table[int(source)] = int(length)
    return table


def write_table(table: dict[int, int]) -> None:
    TABLE.write_text("\n".join(f"{s} {n}" for s, n in sorted(table.items())) + "\n")


def build_variants(table: dict[int, int]) -> Any:
    OUT.mkdir(parents=True, exist_ok=True)
    retail = dump.read(RETAIL)
    fast = spcfast.apply(retail)
    carts = {"base": retail, "spc": fast, "both": shinakuma.apply(fast)}
    entries = rombuild.entries_from_map({str(s): n for s, n in table.items()})
    built = []
    for name, cart in carts.items():
        staged = OUT / f"jp-{name}-cart.sfc"
        staged.write_bytes(cart)
        produced_name = f"jp-{name}-converge.sfc"
        subprocess.run(
            [
                sys.executable,
                "build.py",
                "asm/sdd1-bypass-jp.asm",
                str(staged.relative_to(ROOT)),
                produced_name,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        produced = ROOT / "asm" / produced_name
        bypass = dump.read(produced)
        produced.unlink()
        image = rombuild.build(bypass, entries).image
        free = OUT / f"jp-{name}-free.sfc"
        free.write_bytes(rewrite.declare_rom_only(image))
        built.append(free)
    return built


def requests_of(image: Path, extra: Any, frames: int) -> dict[int, int]:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "-e",
            "SFSCAN=1",
            "-e",
            "SFSCANLEN=1",
            *extra,
            "-v",
            f"{ROOT}:/work",
            "street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
            str(image.relative_to(ROOT)),
            str(frames),
            "-2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    wanted: dict[int, int] = {}
    for line in (result.stdout + result.stderr).splitlines():
        found = SCAN.match(line)
        if not found:
            continue
        address = found.group(1)
        channels = (
            (found.group(2), found.group(3), int(found.group(4))),
            (found.group(5), found.group(6), int(found.group(7))),
            (found.group(8), found.group(9), int(found.group(10))),
        )
        for bank, addr, count in channels:
            if addr == address and count > 0 and int(bank, 16) >= WINDOW_BASE:
                source = (int(bank, 16) - WINDOW_BASE) * 0x10000 + int(addr, 16)
                wanted[source] = max(wanted.get(source, 0), count)
    return wanted


def main() -> int:
    retail = dump.read(RETAIL)
    for iteration in range(1, 21):
        table = read_table()
        images = build_variants(table)
        candidates: dict[int, int] = {}
        work = [(image, extra, frames) for image in images for _n, extra, frames in PASSES]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for wanted in pool.map(lambda job: requests_of(*job), work):
                for source, length in wanted.items():
                    if source in table:
                        continue
                    candidates[source] = max(candidates.get(source, 0), length)
        print(f"  iteration {iteration}: {len(candidates)} candidates", flush=True)

        added = 0
        for source, length in sorted(candidates.items()):
            try:
                produced = sdd1.decompress(retail, source, length)
            except (sdd1.TruncatedStream, IndexError, ValueError):
                print(f"    {source:#08x} does not decode, skipped", flush=True)
                continue
            if len(produced.data) != length:
                print(f"    {source:#08x} produced {len(produced.data)}, skipped", flush=True)
                continue
            table[source] = length
            added += 1
            print(f"    added {source:#08x} length {length}", flush=True)

        write_table(table)
        print(f"  iteration {iteration}: {added} added, {len(table)} streams", flush=True)
        if added == 0:
            print(f"  converged after {iteration} iterations with {len(table)} streams")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
