import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "build" / "all"
LOGS = ROOT / "build" / "logs"

FRAMES = 12000
BRIGHT_EVERY = 300
LIT_THRESHOLD = 5.0
SCAN_BUDGET = 64
PAUSE_FRAME_MS = 1000.0 / 60.0988

RESULT = re.compile(r"^RESULT load=(\w+) frames=(\d+)")
BRIGHT = re.compile(r"^BRIGHT frame=\d+ value=([\d.]+)")
SCANLEN = re.compile(r"^SCANLEN addr=\w+ steps=(\d+)")
APU = re.compile(r"^APU frame=(\d+) writes=\d+")


def run(image, mapping):
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{image.stem}{mapping}.txt"
    with log.open("wb") as handle:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "-e",
                "SFDRIVE=1",
                "-e",
                f"SFBRIGHT={BRIGHT_EVERY}",
                "-e",
                "SFSCANLEN=1",
                "-e",
                "SFAPU=1",
                "-v",
                f"{ROOT}:/work",
                "street-fighter-alpha-2-nochip/sfemu:snes9x-1.63",
                str(image.relative_to(ROOT)),
                str(FRAMES),
                mapping,
            ],
            stdout=handle,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return log


def summarise(log):
    loaded, frames = "?", 0
    samples, lit, misses, scans = 0, 0, 0, 0
    burst_frames = []
    for line in log.read_text(errors="replace").splitlines():
        found = RESULT.match(line)
        if found:
            loaded, frames = found.group(1), int(found.group(2))
            continue
        found = BRIGHT.match(line)
        if found:
            samples += 1
            lit += float(found.group(1)) > LIT_THRESHOLD
            continue
        found = SCANLEN.match(line)
        if found:
            scans += 1
            misses += int(found.group(1)) > SCAN_BUDGET
            continue
        found = APU.match(line)
        if found:
            burst_frames.append(int(found.group(1)))
    return {
        "load": loaded,
        "frames": frames,
        "lit": f"{lit}/{samples}",
        "scans": scans,
        "misses": misses,
        "pause": f"{longest_burst(burst_frames) * PAUSE_FRAME_MS / 1000:.2f}s",
    }


def longest_burst(frames):
    best = run_length = 0
    previous = None
    for frame in frames:
        run_length = run_length + 1 if previous is not None and frame == previous + 1 else 1
        previous = frame
        best = max(best, run_length)
    return best


FREE_MAPPING = "-2"
CART_MAPPING = "-1"


def mapping_for(stem):
    """Which map an image is read through, decided by the form it was built in.

    A converted image is windowed, because it is larger than the address space
    the cartridge layout can reach. One still in cartridge form is not, and
    reading it through the windowed map would fetch the right bytes from the
    wrong bank.
    """
    return FREE_MAPPING if stem.endswith("-free") else CART_MAPPING


def main(argv: list[str]) -> int:
    wanted = argv[1] if len(argv) > 1 else ""
    rows = []
    for image in sorted(IMAGES.glob("*.sfc")):
        if wanted and wanted not in image.stem:
            continue
        if image.stem.endswith("-bypass"):
            continue
        mapping = mapping_for(image.stem)
        summary = summarise(run(image, mapping))
        rows.append((image.stem, summary))
        print(
            f"  {image.stem:22s} load={summary['load']:4s} frames={summary['frames']:6d} "
            f"lit={summary['lit']:>8s} scans={summary['scans']:6d} "
            f"misses={summary['misses']:3d} pause={summary['pause']}",
            flush=True,
        )
    failed = [name for name, s in rows if s["load"] != "ok" or s["misses"] or s["frames"] != FRAMES]
    print(f"\n  {len(rows)} images, {len(failed)} failing")
    for name in failed:
        print(f"    FAIL {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
