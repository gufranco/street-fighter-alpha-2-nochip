import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "build" / "logs" / "stagediff"

FRAMES = 3600
MENU = 1800
ROSTER = 18


def run(
    image: Path,
    matchup: str,
    out: Path,
    execute: Callable[..., Any] = subprocess.run,
) -> Path:
    """Play one matchup and leave a per-frame hash log behind.

    The reaching out is a parameter so the comparison, which is the part worth
    testing, can be driven against recorded logs rather than a container.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    execute(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "-e",
            f"SFSCENE={matchup}",
            "-e",
            f"SFSCENEMENU={MENU}",
            "-e",
            f"SFHASH=/work/{out.relative_to(ROOT)}",
            "-v",
            f"{ROOT}:/work",
            "street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
            str(image.relative_to(ROOT)),
            str(FRAMES),
            "-2",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return out


def hashes(path: Path) -> dict[int, str]:
    found: dict[int, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2:
            found[int(parts[0])] = parts[1]
    return found


def compare(before: dict[int, str], after: dict[int, str]) -> tuple[list[int], list[int]]:
    shared = sorted(set(before) & set(after))
    differing = [frame for frame in shared if before[frame] != after[frame]]
    return shared, differing


def main(
    argv: list[str],
    play: Callable[..., Path] = run,
    say: Callable[[str], None] = print,
    roster: int = ROSTER,
) -> int:
    """Report, per opponent, how many frames the two images render differently.

    The playing is a parameter so the reporting can be driven without a
    container, and the roster is one so a run can cover a single matchup.
    """
    before_image = ROOT / (argv[1] if len(argv) > 1 else "build/baseline/usa-both-free.before.sfc")
    after_image = ROOT / (argv[2] if len(argv) > 2 else "build/all/usa-both-free.sfc")
    tag = argv[3] if len(argv) > 3 else "usa"

    say(f"before {before_image.name}")
    say(f"after  {after_image.name}")
    say(f"{FRAMES} frames per matchup, menu driven for the first {MENU}")
    say("")

    for opponent in range(roster):
        matchup = f"00,{opponent:02x}"
        b = play(before_image, matchup, LOGS / f"{tag}-{opponent:02x}-before.txt")
        a = play(after_image, matchup, LOGS / f"{tag}-{opponent:02x}-after.txt")
        shared, differing = compare(hashes(b), hashes(a))
        if not shared:
            say(f"  opponent {opponent:02x}  no frames captured")
            continue
        first = differing[0] if differing else None
        in_fight = [frame for frame in differing if frame >= MENU]
        say(
            f"  opponent {opponent:02x}  {len(differing):5d} of {len(shared)} frames differ"
            f"   first {first if first is not None else '-'}"
            f"   in the fight {len(in_fight)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
