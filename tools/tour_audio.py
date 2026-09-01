import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "build" / "all"
LOGS = ROOT / "build" / "logs"

ROSTER = 18
BUDGET = 12000
TICK = 60

TOUR = re.compile(r"^TOUR character=(\d+) frame=(\d+)")
TICKLINE = re.compile(r"^TICK frame=(\d+) main=(\w\w) nmi=(\w\w)")
BLKBAD = re.compile(r"^BLKBAD src=(\S+) dest=\w+ len=\d+ bad=\d+")
BLOCKS = re.compile(r"^BLOCKS ok=(\d+) bad=(\d+)")
RESULT = re.compile(r"^RESULT load=(\w+) frames=(\d+)")


def run(
    image: Path,
    mapping: str,
    roster: int,
    budget: int,
    execute: Callable[..., Any] = subprocess.run,
) -> str:
    """Tour one image and return the log the emulator wrote.

    The reaching out is a parameter so the parsing and the verdict, which are
    the parts worth testing, can be driven without a container.
    """
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"tour-{image.stem}.txt"
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
                f"SFTOURROSTER={roster}",
                "-e",
                f"SFTOURBUDGET={budget}",
                "-e",
                "SFVERIFY=1",
                "-e",
                f"SFTICK={TICK}",
                "-v",
                f"{ROOT}:/work",
                "snes-street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
                str(image.relative_to(ROOT)),
                str(roster * budget),
                mapping,
            ],
            stdout=handle,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return log.read_text(errors="replace")


def parse(text: str, roster: int, budget: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    found: list[dict[str, Any]] = [
        {"fighter": index, "main": set(), "nmi": set(), "bad": [], "ticks": 0}
        for index in range(roster)
    ]
    summary: dict[str, Any] = {"load": "?", "frames": 0, "ok": 0, "bad": 0}
    slot = 0
    for line in text.splitlines():
        match = TICKLINE.match(line)
        if match:
            slot = min(int(match.group(1)) // budget, roster - 1)
            found[slot]["main"].add(match.group(2))
            found[slot]["nmi"].add(match.group(3))
            found[slot]["ticks"] += 1
            continue
        match = TOUR.match(line)
        if match:
            slot = min(int(match.group(2)) // budget, roster - 1)
            found[slot]["fighter"] = int(match.group(1))
            continue
        match = BLKBAD.match(line)
        if match:
            found[slot]["bad"].append(match.group(1))
            continue
        match = BLOCKS.match(line)
        if match:
            summary["ok"], summary["bad"] = int(match.group(1)), int(match.group(2))
            continue
        match = RESULT.match(line)
        if match:
            summary["load"], summary["frames"] = match.group(1), int(match.group(2))
    return found, summary


def stalled(found: list[dict[str, Any]]) -> list[int]:
    return [
        index for index, slot in enumerate(found) if len(slot["main"]) < 2 or len(slot["nmi"]) < 2
    ]


def passed(found: list[dict[str, Any]], summary: dict[str, Any], roster: int, budget: int) -> bool:
    return (
        not stalled(found)
        and summary["bad"] == 0
        and summary["load"] == "ok"
        and summary["frames"] == roster * budget
    )


def report(
    name: str,
    found: list[dict[str, Any]],
    summary: dict[str, Any],
    say: Callable[[str], None] = print,
) -> None:
    """One block about one image: a line per fighter, then the totals."""
    say(f"  {name}")
    for slot in found:
        moving = len(slot["main"]) > 1 and len(slot["nmi"]) > 1
        say(
            f"    fighter {slot['fighter']:2d}  ticks={slot['ticks']:4d}  "
            f"main states={len(slot['main']):3d}  frames drawn={len(slot['nmi']):3d}  "
            f"bad blocks={len(slot['bad']):2d}  {'ok' if moving else 'STALLED'}"
        )
    say(
        f"    load={summary['load']} frames={summary['frames']} "
        f"blocks ok={summary['ok']} bad={summary['bad']}"
    )


def main(
    argv: list[str],
    images: list[Path] | None = None,
    tour: Callable[..., str] = run,
    say: Callable[[str], None] = print,
) -> int:
    """Tour every matching image and report which of them stalled.

    The image list and the touring are parameters, so the verdict can be driven
    without a container and without a build on disk.
    """
    wanted = argv[1] if len(argv) > 1 else "both-cart"
    roster = int(argv[2]) if len(argv) > 2 else ROSTER
    budget = int(argv[3]) if len(argv) > 3 else BUDGET
    failed = []
    for image in sorted(IMAGES.glob("*.sfc")) if images is None else images:
        if wanted not in image.stem or image.stem.endswith("-bypass"):
            continue
        mapping = "-2" if image.stem.endswith("-free") else "-1"
        found, summary = parse(tour(image, mapping, roster, budget), roster, budget)
        report(image.stem, found, summary, say)
        if not passed(found, summary, roster, budget):
            failed.append((image.stem, stalled(found), summary["bad"]))
    say("")
    for name, halted, bad in failed:
        say(f"    FAIL {name}: stalled {halted}, bad blocks {bad}")
    say(f"  {len(failed)} failing")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
