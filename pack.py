import hashlib
import importlib.util
import subprocess
import sys
from collections import namedtuple
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware


def load_images(load: Callable[[str], Any] = hardware.load) -> Any:
    """The image handling model, or the reason a tree without it cannot go on.

    A submodule is a pinned commit rather than content, so a clone without them
    leaves named but empty directories. Saying that plainly beats a bare import
    error from whatever happens to import first.
    """
    try:
        return load("romimage")
    except hardware.ModelMissing as unchecked:
        raise SystemExit(str(unchecked)) from None


image_package = load_images()

dump = image_package.dump
rewrite = image_package.rewrite


ROOT = Path(__file__).resolve().parent


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rombuild = _load("rombuild")
spcfast = _load("spcfast")
shinakuma = _load("shinakuma")
gamefixes = _load("gamefixes")
repeatload = _load("repeatload")
prefight = _load("prefight")
jpstreams = _load("jpstreams")
usastreams = _load("usastreams")
version = _load("version")
gate = _load("gate")

Region = namedtuple("Region", "title retail bypass tagged")

REGIONS = {
    "usa": Region(
        title="sfa2-usa",
        retail=ROOT / "roms" / "sfa2-usa-final.sfc",
        bypass="asm/sdd1-bypass.asm",
        tagged=ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc",
    ),
    "jp": Region(
        title="sfz2-jp",
        retail=ROOT / "roms" / "sfz2-jp-final.sfc",
        bypass="asm/sdd1-bypass-jp.asm",
        tagged=None,
    ),
}

DIST = ROOT / "dist"
MANIFEST = "SHA256SUMS"


def output_name(region: str, release: str | None = None) -> str:
    found = version.stamped(f"{REGIONS[region].title}-nochip", release)
    assert isinstance(found, str)
    return found


def manifest_line(name: str, image: bytes | bytearray) -> str:
    return f"{hashlib.sha256(image).hexdigest()}  {name}"


def entries_for(region: str) -> Any:
    table = jpstreams.STREAMS if region == "jp" else usastreams.STREAMS
    return rombuild.entries_from_map({str(source): length for source, length in table})


class AssemblyFailed(Exception):
    """The bypass patch did not assemble, carrying what the assembler said."""


def assembly_failure(region: str, result: Any) -> str:
    said = [
        f"the {region} bypass patch did not assemble: build.py exited {result.returncode}",
        "",
        "This step assembles the patch in a container, so Docker has to be installed",
        "and running. Check it answers with: docker --version",
    ]
    for stream, raw in (("stdout", result.stdout), ("stderr", result.stderr)):
        text = (raw or "").strip()
        if text:
            said += ["", f"--- build.py {stream} ---", text]
    return "\n".join(said)


def assemble_command(region: str, staged: Path, produced_name: str) -> list[str]:
    """What assembling one region's bypass patch shells out to."""
    return [
        sys.executable,
        "build.py",
        REGIONS[region].bypass,
        str(Path(staged).relative_to(ROOT)),
        produced_name,
    ]


def _shell_out(args: list[str]) -> Any:
    return subprocess.run(args, cwd=ROOT, check=False, capture_output=True, text=True)


def assemble_bypass(
    region: str,
    cart: bytes | bytearray,
    workdir: Path,
    execute: Callable[[list[str]], Any] = _shell_out,
) -> bytes:
    staged = workdir / f"{region}-patched.sfc"
    staged.write_bytes(cart)
    produced_name = f"{region}-bypass.sfc"
    result = execute(assemble_command(region, staged, produced_name))
    if result.returncode != 0:
        raise AssemblyFailed(assembly_failure(region, result))
    produced = ROOT / "asm" / produced_name
    image = produced.read_bytes()
    produced.unlink()
    return image


def build(region: str, workdir: Path) -> bytes:
    retail = dump.read(REGIONS[region].retail)
    cart = repeatload.apply(gamefixes.apply(shinakuma.apply(spcfast.apply(retail))))
    bypass = prefight.apply(assemble_bypass(region, cart, workdir))
    extra = ((prefight.TABLE_ADDRESS, prefight.table()),)
    image = rombuild.build(bypass, entries_for(region), extra=extra).image
    assert isinstance(image, bytes)
    declared = rewrite.declare_rom_only(image)
    assert isinstance(declared, bytes)
    return declared


def main(
    argv: list[str],
    make: Any = None,
    gate_check: Any = None,
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
    dist: Path | None = None,
) -> int:
    """Every region built, with the two slow steps passed in so a run can be checked."""
    complain = say if complain is None else complain
    make = build if make is None else make
    gate_check = gate.check if gate_check is None else gate_check
    dist = DIST if dist is None else Path(dist)

    wanted = argv[1:] or sorted(REGIONS)
    unknown = [region for region in wanted if region not in REGIONS]
    if unknown:
        complain(f"unknown region: {', '.join(unknown)}")
        return 2

    missing = [str(REGIONS[r].retail) for r in wanted if not REGIONS[r].retail.exists()]
    if missing:
        complain("these retail dumps are not present:")
        for path in missing:
            complain(f"  {path}")
        return 1

    for region in wanted:
        findings = gate_check(region)
        if findings:
            complain(f"the {region} stream table does not pass the gate:")
            for finding in findings:
                complain(f"  {finding}")
            return 1

    dist.mkdir(exist_ok=True)
    workdir = dist / "work"
    workdir.mkdir(exist_ok=True)

    lines = []
    for region in wanted:
        try:
            image = make(region, workdir)
        except AssemblyFailed as failure:
            complain(str(failure))
            return 1
        name = output_name(region)
        (dist / name).write_bytes(image)
        lines.append(manifest_line(name, image))
        say(f"  {name}  {len(image):,} bytes")

    (dist / MANIFEST).write_text("\n".join(lines) + "\n")
    say(f"  {MANIFEST}  {len(lines)} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
