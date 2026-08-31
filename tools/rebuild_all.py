import importlib.util
import subprocess
import sys
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


def assemble(region: str, name: str, cart: bytes | bytearray) -> Path:
    staged = OUT / f"{region}-{name}-cart.sfc"
    staged.write_bytes(cart)
    output = f"{region}-{name}-bypass.sfc"
    subprocess.run(
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


def image_source(name: str, bypass: Path) -> tuple[Any, tuple[Any, ...]]:
    rom = dump.read(bypass)
    if name != PREFIGHT_VARIANT:
        return rom, ()
    return prefight.apply(rom), ((prefight.TABLE_ADDRESS, prefight.table()),)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for region, path in RETAIL.items():
        retail = dump.read(path)
        entries = entries_for(region)
        for name, cart in variants(retail).items():
            bypass = assemble(region, name, cart)
            source, extra = image_source(name, bypass)
            image = rombuild.build(source, entries, extra=extra).image
            free = OUT / f"{region}-{name}-free.sfc"
            free.write_bytes(rewrite.declare_rom_only(image))
            print(f"  {region}-{name}: cart, bypass, free ({len(entries)} streams)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
