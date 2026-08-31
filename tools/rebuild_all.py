import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump
rewrite = hardware.load("romimage").rewrite


ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spcfast = load("spcfast")
shinakuma = load("shinakuma")
gamefixes = load("gamefixes")
repeatload = load("repeatload")
prefight = load("prefight")
rombuild = load("rombuild")
sdd1map = load("sdd1map")

OUT = ROOT / "build" / "all"
RETAIL = {"usa": ROOT / "roms" / "sfa2-usa-final.sfc", "jp": ROOT / "roms" / "sfz2-jp-final.sfc"}
BYPASS = {"usa": "sdd1-bypass.asm", "jp": "sdd1-bypass-jp.asm"}
TAGGED = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"


def variants(retail: bytes | bytearray) -> dict[str, bytes]:
    fast = spcfast.apply(retail)
    return {
        "base": retail,
        "spc": fast,
        "sa": shinakuma.apply(retail),
        "both": repeatload.apply(gamefixes.apply(shinakuma.apply(fast))),
    }


def entries_for(region: str) -> Any:
    table = load("jpstreams" if region == "jp" else "usastreams").STREAMS
    return rombuild.entries_from_map({str(source): length for source, length in table})


def assemble(
    region: str,
    name: str,
    cart: bytes | bytearray,
    execute: Callable[..., Any] = subprocess.run,
) -> Path:
    """Stage one variant and assemble the bypass against it.

    The shelling out is a parameter so the staging and the naming can be driven
    without the assembler on the machine.
    """
    staged = OUT / f"{region}-{name}-cart.sfc"
    staged.write_bytes(cart)
    output = f"{region}-{name}-bypass.sfc"
    execute(
        [
            sys.executable,
            "build.py",
            f"asm/{BYPASS[region]}",
            str(staged.relative_to(ROOT)),
            output,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    produced = ROOT / "asm" / output
    target = OUT / output
    target.write_bytes(produced.read_bytes())
    produced.unlink()
    return target


PREFIGHT_VARIANT = "both"


def image_source(
    name: str, bypass: Path, read: Callable[[Path], Any] | None = None
) -> tuple[Any, tuple[Any, ...]]:
    """What goes into the image, and anything that has to be placed alongside it.

    Only one variant carries the pre-fight patch, and only that one needs its
    table written into the image. The cartridge reader is a parameter so both
    answers can be driven without an assembled bypass on disk.
    """
    read = dump.read if read is None else read
    rom = read(bypass)
    if name != PREFIGHT_VARIANT:
        return rom, ()
    return prefight.apply(rom), ((prefight.TABLE_ADDRESS, prefight.table()),)


def main(
    carts: dict[str, dict[str, bytes | bytearray]] | None = None,
    build: Callable[..., Path] = assemble,
    source_for: Callable[[str, Path], tuple[Any, tuple[Any, ...]]] = image_source,
    table_for: Callable[[str], Any] = entries_for,
    say: Callable[[str], None] = print,
) -> int:
    """Rebuild every variant of every region, in cartridge, bypass and free form.

    The variant set, the assembler and the prefight step are parameters, so the
    loop can be driven without the dumps and without the assembler. Deriving the
    variants is not tested here because each patch carries its own proof.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    carts = (
        {region: variants(dump.read(path)) for region, path in RETAIL.items()}
        if carts is None
        else carts
    )
    for region, region_carts in carts.items():
        entries = table_for(region)
        for name, cart in region_carts.items():
            bypass = build(region, name, cart)
            source, extra = source_for(name, bypass)
            image = rombuild.build(source, entries, extra=extra).image
            free = OUT / f"{region}-{name}-free.sfc"
            free.write_bytes(rewrite.declare_rom_only(image))
            say(f"  {region}-{name}: cart, bypass, free ({len(entries)} streams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
