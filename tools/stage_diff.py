import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "build" / "logs" / "stagediff"

FRAMES = 3600
MENU = 1800
ROSTER = 18


def run(image: Path, matchup: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
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


def main(argv: list[str]) -> int:
    before_image = ROOT / (argv[1] if len(argv) > 1 else "build/baseline/usa-both-free.before.sfc")
    after_image = ROOT / (argv[2] if len(argv) > 2 else "build/all/usa-both-free.sfc")
    tag = argv[3] if len(argv) > 3 else "usa"

    print(f"before {before_image.name}")
    print(f"after  {after_image.name}")
    print(f"{FRAMES} frames per matchup, menu driven for the first {MENU}")
    print()

    for opponent in range(ROSTER):
        matchup = f"00,{opponent:02x}"
        b = run(before_image, matchup, LOGS / f"{tag}-{opponent:02x}-before.txt")
        a = run(after_image, matchup, LOGS / f"{tag}-{opponent:02x}-after.txt")
        shared, differing = compare(hashes(b), hashes(a))
        if not shared:
            print(f"  opponent {opponent:02x}  no frames captured")
            sys.stdout.flush()
            continue
        first = differing[0] if differing else None
        in_fight = [frame for frame in differing if frame >= MENU]
        print(
            f"  opponent {opponent:02x}  {len(differing):5d} of {len(shared)} frames differ"
            f"   first {first if first is not None else '-'}"
            f"   in the fight {len(in_fight)}"
        )
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
