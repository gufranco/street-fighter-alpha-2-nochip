import random
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump
sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent
REF_DIR = ROOT / "ref"
IMAGE = "street-fighter-alpha-2-nochip/sdd1ref:snes9x-1.63"
MAX_LENGTH = sdd1.MAX_LENGTH
SAMPLE_LENGTHS = (1, 2, 15, 16, 17, 64, 832, 2048, 8192)


def build_image_command() -> list[str]:
    return ["docker", "build", "--tag", IMAGE, str(REF_DIR)]


def run_command() -> list[str]:
    return ["docker", "run", "--rm", "--interactive", "--network=none", IMAGE]


def encode_request(rom: bytes | bytearray, cases: list[tuple[int, int]]) -> bytes:
    parts = [
        len(rom).to_bytes(4, "little"),
        bytes(rom),
        len(cases).to_bytes(4, "little"),
    ]
    for offset, length in cases:
        if not 0 <= offset < len(rom):
            raise ValueError(f"offset {offset} lies outside the rom")
        if not 0 <= length <= MAX_LENGTH:
            raise ValueError(f"length {length} exceeds one 64K block")
        parts.append(offset.to_bytes(4, "little"))
        parts.append((length % MAX_LENGTH).to_bytes(4, "little"))
    return b"".join(parts)


def decode_response(blob: bytes, cases: list[tuple[int, int]]) -> list[bytes]:
    parts: list[bytes] = []
    pos = 0
    for _, length in cases:
        size = length if length else MAX_LENGTH
        chunk = blob[pos : pos + size]
        if len(chunk) != size:
            raise ValueError("the reference returned a short response")
        parts.append(chunk)
        pos += size
    return parts


def build_image(quiet: bool = True, execute: Callable[..., Any] = subprocess.run) -> int:
    """Build the reference image, returning whatever the builder exited with.

    The builder is a parameter so a caller can be driven without a container
    runtime on the machine.
    """
    stream = subprocess.DEVNULL if quiet else None
    returned: int = execute(
        build_image_command(), stdout=stream, stderr=stream, check=False
    ).returncode
    return returned


def reference_outputs(
    rom: bytes | bytearray,
    cases: list[tuple[int, int]],
    execute: Callable[..., Any] = subprocess.run,
) -> list[bytes]:
    """Ask the C reference for one output per case.

    The running is a parameter so the framing, which is the part worth testing,
    can be driven against a recorded response.
    """
    result = execute(
        run_command(), input=encode_request(rom, cases), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"reference decompressor exited {result.returncode}: {result.stderr[:200]!r}"
        )
    return decode_response(result.stdout, cases)


def compare(
    rom: bytes | bytearray,
    cases: list[tuple[int, int]],
    reference: Callable[..., list[bytes]] = reference_outputs,
) -> list[tuple[int, int, str]]:
    """Every case where this package and the C reference disagree.

    The reference is a parameter so each kind of disagreement can be driven
    without a container.
    """
    expected = reference(rom, cases)
    mismatches: list[tuple[int, int, str]] = []
    for (offset, length), want in zip(cases, expected, strict=True):
        try:
            got = sdd1.decompress(rom, offset, length).data
        except sdd1.TruncatedStream:
            mismatches.append((offset, length, "truncated"))
            continue
        if got != want:
            first = next(
                (i for i, (a, b) in enumerate(zip(got, want, strict=True)) if a != b), len(want)
            )
            mismatches.append((offset, length, f"first differing byte at {first}"))
    return mismatches


def sample_cases(rom: bytes | bytearray, count: int, seed: int) -> list[tuple[int, int]]:
    limit = len(rom) - MAX_LENGTH
    if limit < 1:
        raise ValueError("the rom is too small to sample compressed streams from")
    rng = random.Random(seed)
    return [(rng.randrange(limit), rng.choice(SAMPLE_LENGTHS)) for _ in range(count)]


def main(
    argv: list[str] | None = None,
    read: Callable[[Any], Any] | None = None,
    build: Callable[[], int] = build_image,
    check: Callable[..., list[tuple[int, int, str]]] = compare,
    say: Callable[..., None] = print,
) -> int:
    """The command line, with every step that reaches outside passed in.

    A run needs a cartridge and a container, so both are parameters and every
    branch, including the two refusals and the mismatch report, can be driven
    without either.
    """
    argv = sys.argv if argv is None else argv
    read = dump.read if read is None else read
    if len(argv) < 2:
        say("usage: sdd1ref.py <rom> [cases] [seed]", file=sys.stderr)
        return 2

    rom = read(argv[1])
    count = int(argv[2]) if len(argv) > 2 else 500
    seed = int(argv[3]) if len(argv) > 3 else 20260813

    say(f"  building {IMAGE}")
    if build() != 0:
        say("reference image failed to build", file=sys.stderr)
        return 1

    cases = sample_cases(rom, count, seed)
    say(f"  comparing {len(cases)} cases against the c reference")
    mismatches = check(rom, cases)

    if mismatches:
        for offset, length, why in mismatches[:20]:
            say(f"  MISMATCH {offset:#09x} len {length}: {why}")
        say(f"[fail] {len(mismatches)}/{len(cases)} cases differ")
        return 1

    say(f"[ok] {len(cases)} cases identical to snes9x {IMAGE.rsplit('-', maxsplit=1)[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
