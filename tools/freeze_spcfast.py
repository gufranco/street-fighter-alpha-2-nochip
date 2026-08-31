import importlib.util
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent.parent

RETAIL = {
    "jp": ROOT / "roms" / "sfz2-jp-final.sfc",
    "usa": ROOT / "roms" / "sfa2-usa-final.sfc",
}
SOURCE = "asm/spc-fast-upload.asm"
CHECKSUM_FIELD = range(0x007FDC, 0x007FE0)


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assemble(region: str) -> Any:
    output = f"probe-{region}.sfc"
    subprocess.run(
        [sys.executable, "build.py", SOURCE, str(RETAIL[region].relative_to(ROOT)), output],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return dump.read(ROOT / "asm" / output)


def differing_runs(before: bytes | bytearray, after: bytes | bytearray) -> list[tuple[int, bytes]]:
    found: list[tuple[int, bytes]] = []
    start: int | None = None
    for index in range(len(before)):
        if index in CHECKSUM_FIELD:
            if start is not None:
                found.append((start, bytes(after[start:index])))
                start = None
            continue
        if before[index] != after[index]:
            if start is None:
                start = index
        elif start is not None:
            found.append((start, bytes(after[start:index])))
            start = None
    if start is not None:
        found.append((start, bytes(after[start:])))
    return found


def render(runs: list[tuple[int, bytes]]) -> str:
    lines = ["PATCH = ("]
    for at, data in runs:
        text = data.hex()
        if len(text) <= 60:
            lines.append(f'    (0x{at:06X}, bytes.fromhex("{text}")),')
        else:
            lines.append("    (")
            lines.append(f"        0x{at:06X},")
            lines.append("        bytes.fromhex(")
            for chunk in textwrap.wrap(text, 84):
                lines.append(f'            "{chunk}"')
            lines.append("        ),")
            lines.append("    ),")
    lines.append(")")
    return "\n".join(lines) + "\n"


PLUMBING = """JOYPAD_WAIT = bytes([0xAD, 0x12, 0x42, 0x4A, 0xB0, 0xFA])
FRAME_HOOK = bytes.fromhex("")
FRAME_HOOK_SITES = (0x000208, 0x00020C)


def frame_hook_site(rom: bytes | bytearray) -> int | None:
    for site in FRAME_HOOK_SITES:
        window = rom[site : site + len(JOYPAD_WAIT)]
        if window == JOYPAD_WAIT or window[: len(FRAME_HOOK)] == FRAME_HOOK:
            return site
    raise ValueError("the frame interrupt's joypad wait is at neither known position")


def runs_for(rom: bytes | bytearray) -> list[tuple[int, bytes]]:
    if not FRAME_HOOK:
        return PATCH
    return (*PATCH, (frame_hook_site(rom), FRAME_HOOK))


"""


def add_plumbing(source: str) -> str:
    if "FRAME_HOOK_SITES" in source:
        return source
    source = source.replace("def checksum(rom):", PLUMBING + "def checksum(rom):", 1)
    source = source.replace(
        "    return all(rom[at : at + len(data)] == data for at, data in PATCH)",
        "    return all(rom[at : at + len(data)] == data for at, data in runs_for(rom))",
        1,
    )
    source = source.replace("    for at, data in PATCH:", "    for at, data in runs_for(rom):", 1)
    source = source.replace(
        "    return sum(len(data) for _, data in PATCH)",
        "    return sum(len(data) for _, data in PATCH) + len(FRAME_HOOK)",
        1,
    )
    return source.replace(
        '    print(f"  patch         {patch_bytes()} bytes in {len(PATCH)} runs")',
        '    print(f"  patch         {patch_bytes()} bytes in {len(runs_for(rom))} runs")',
        1,
    )


def rewrite(
    source: str,
    shared: list[tuple[int, bytes]],
    hook_body: bytes | None,
    hook_sites: tuple[int, ...] | None,
) -> str:
    source = add_plumbing(source)
    rendered = render(shared)
    start = source.index("PATCH = (")
    end = source.index("\n)\n", start) + 3
    updated = source[:start] + rendered + source[end:]
    if hook_body is None:
        return re.sub(
            r'FRAME_HOOK = bytes\.fromhex\("[0-9a-f]*"\)',
            'FRAME_HOOK = bytes.fromhex("")',
            updated,
        )
    assert hook_sites is not None, "a hook body always arrives with the sites it goes to"
    updated = re.sub(
        r'FRAME_HOOK = bytes\.fromhex\("[0-9a-f]*"\)',
        f'FRAME_HOOK = bytes.fromhex("{hook_body.hex()}")',
        updated,
    )
    return re.sub(
        r"FRAME_HOOK_SITES = \([^)]*\)",
        f"FRAME_HOOK_SITES = ({hook_sites[0]:#08x}, {hook_sites[1]:#08x})",
        updated,
    )


def main(argv: list[str]) -> int:
    check_only = "--check" in argv[1:]

    assembled = {region: assemble(region) for region in RETAIL}
    runs = {
        region: differing_runs(dump.read(RETAIL[region]), image)
        for region, image in assembled.items()
    }

    shared = [run for run in runs["jp"] if run in runs["usa"]]
    per_region = {
        region: [run for run in region_runs if run not in shared]
        for region, region_runs in runs.items()
    }

    counts = {region: len(extra) for region, extra in per_region.items()}
    if len(set(counts.values())) != 1 or max(counts.values()) > 1:
        print(
            f"  region specific runs must match and number at most one: {counts}", file=sys.stderr
        )
        return 1

    source = (ROOT / "spcfast.py").read_text()
    if max(counts.values()) == 0:
        updated = rewrite(source, shared, None, None)
    else:
        bodies = {region: extra[0][1] for region, extra in per_region.items()}
        if bodies["jp"] != bodies["usa"]:
            print("  the region specific run must carry identical bytes", file=sys.stderr)
            return 1
        sites = tuple(sorted(extra[0][0] for extra in per_region.values()))
        updated = rewrite(source, shared, bodies["jp"], sites)

    if not check_only:
        (ROOT / "spcfast.py").write_text(updated)

    spcfast = load("spcfast")
    for region, image in assembled.items():
        if spcfast.apply(dump.read(RETAIL[region])) != image:
            print(
                f"  {region}: spcfast.py does not reproduce what the assembler produces",
                file=sys.stderr,
            )
            return 1
        print(f"  {region}: the frozen table reproduces the assembler exactly")

    runs_total = len(shared) + max(counts.values())
    byte_total = sum(len(data) for _, data in shared)
    if max(counts.values()):
        byte_total += len(per_region["jp"][0][1])
    print(f"  {runs_total} runs, {byte_total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
