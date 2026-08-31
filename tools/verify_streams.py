import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sdd1ref = load("sdd1ref")
rombuild = load("rombuild")
jpstreams = load("jpstreams")
usastreams = load("usastreams")

BATCH = 200

SETS: dict[str, tuple[Path, Callable[[], list[Any]]]] = {
    "usa": (
        ROOT / "roms" / "sfa2-usa-final.sfc",
        lambda: list(usastreams.STREAMS),
    ),
    "jp": (
        ROOT / "roms" / "sfz2-jp-final.sfc",
        lambda: list(jpstreams.STREAMS),
    ),
}


def batches(cases: list[Any], size: int = BATCH) -> list[list[Any]]:
    """The cases split into runs the reference is asked about one run at a time.

    The reference runs in a container, and handing it every stream at once means
    one very long silence followed by an answer. Splitting the work lets progress
    be reported while it happens, which on a set of several thousand streams is
    the difference between a tool that looks stuck and one that does not.
    """
    return [cases[start : start + size] for start in range(0, len(cases), size)]


def verify(
    region: str,
    read: Callable[[Any], Any] | None = None,
    compare: Callable[..., list[Any]] | None = None,
    say: Callable[[str], None] = print,
) -> tuple[list[Any], list[Any]]:
    """Every stream in one region's table, compared against the C reference.

    The cartridge reader and the comparison are parameters, so the batching and
    the running count, which are what this function adds, can be driven without
    a dump or a container.
    """
    read = dump.read if read is None else read
    compare = sdd1ref.compare if compare is None else compare
    retail, cases_for = SETS[region]
    rom = read(retail)
    cases: list[Any] = cases_for()
    mismatches: list[Any] = []
    checked = 0
    for chunk in batches(cases):
        checked += len(chunk)
        mismatches.extend(compare(rom, chunk))
        say(f"    {region}: {checked:5d}/{len(cases)} checked, {len(mismatches)} differing")
    return cases, mismatches


def main(
    argv: list[str],
    build: Callable[[], int] = sdd1ref.build_image,
    check: Callable[..., tuple[list[Any], list[Any]]] = verify,
    say: Callable[..., None] = print,
) -> int:
    """The command line, with the container build and the comparison passed in."""
    wanted = argv[1:] or sorted(SETS)
    if build() != 0:
        say("the reference image failed to build", file=sys.stderr)
        return 1

    failed = False
    for region in wanted:
        cases, mismatches = check(region)
        for offset, length, why in mismatches[:20]:
            say(f"  MISMATCH {offset:#09x} len {length}: {why}")
        if mismatches:
            failed = True
            say(f"  {region}: {len(mismatches)} of {len(cases)} streams differ")
        else:
            say(f"  {region}: all {len(cases)} streams identical to the reference")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
