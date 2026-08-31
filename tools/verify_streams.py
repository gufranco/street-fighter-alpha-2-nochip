import importlib.util
import sys
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

SETS = {
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


def verify(region: str) -> int:
    retail, cases_for = SETS[region]
    rom = dump.read(retail)
    cases = cases_for()
    mismatches = []
    checked = 0
    for chunk in batches(cases):
        checked += len(chunk)
        mismatches.extend(sdd1ref.compare(rom, chunk))
        print(
            f"    {region}: {checked:5d}/{len(cases)} checked, {len(mismatches)} differing",
            flush=True,
        )
    return cases, mismatches


def main(argv: list[str]) -> int:
    wanted = argv[1:] or sorted(SETS)
    if sdd1ref.build_image() != 0:
        print("the reference image failed to build", file=sys.stderr)
        return 1

    failed = False
    for region in wanted:
        cases, mismatches = verify(region)
        for offset, length, why in mismatches[:20]:
            print(f"  MISMATCH {offset:#09x} len {length}: {why}")
        if mismatches:
            failed = True
            print(f"  {region}: {len(mismatches)} of {len(cases)} streams differ")
        else:
            print(f"  {region}: all {len(cases)} streams identical to the reference")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
