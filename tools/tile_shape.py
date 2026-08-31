"""Whether what came out of the decompressor is shaped like graphics.

The decompressor is checked against digests, against a reference, against an
encoder somebody else wrote and against a cartridge that predates the
compression. All of those ask whether the bytes are the right bytes. This asks a
different and weaker question, and it is worth asking because it needs nothing
outside this machine: are the bytes shaped like a tile sheet at all?

**Why the obvious check is worthless.** Reading a stream back through the 4bpp
layout and writing it out again reproduces the input for any run whose length
divides by thirty two, because the planar layout is a rearrangement and nothing
is lost. It reproduces noise exactly as happily as art. A round trip is not
evidence and this does not report one.

**What is measured instead.** Reuse. A real sheet repeats tiles, because blank
space and flat colour repeat, and a run of random bytes never repeats a
thirty two byte tile. So the reading is the fraction of tiles that are not the
first of their kind, and beside every real reading is one taken from random bytes
of the same length. Across 900 streams of the USA cartridge the real figure is
about 0.14 and the control is 0.00, and 470 sheets repeat something where no
control does.

The control is the point. Without it a reader cannot tell a measurement from an
artefact of the format, which is the trap this whole file exists to avoid.

Usage:
    python3 tools/tile_shape.py <rom> [streams]
"""

import importlib.util
import os
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

sdd1 = hardware.load("sdd1")

snesgfx = hardware.load("snesgfx")

FOUR_BIT = snesgfx.FORMATS["4bpp"]
"""The layout this cartridge stores, taken from the model rather than restated.

The model is what knows that a tile is thirty two bytes and what refuses a run
that is not a whole number of them. Writing either of those here would be a
second copy of a fact that already has an owner, and the two would drift.
"""

TILE_BYTES = 32
"""One 8x8 tile at four bits per pixel, kept only to report and to size a control.

The number is not used to decide anything. `FOUR_BIT.decode` decides what is a
tile and what is not, and this is checked against it below so a change in the
model is a failing test here rather than a silent disagreement.
"""

SMALLEST = 512
"""Below this a reuse figure is noise in both directions, so a stream is skipped.

A sheet of four tiles that happens to repeat one reads as 0.25, which says
nothing. The threshold is stated rather than tuned: it is sixteen tiles, the
smallest sheet where a single coincidence does not dominate the fraction.
"""

Survey = namedtuple(
    "Survey",
    "aligned unaligned meanReuse meanReuseOfNoise withAnyRepeat noiseWithAnyRepeat",
)


def tiles(data):
    """The run cut into tiles by the model, or nothing when it is not tiles.

    The model raises rather than padding, which is the behaviour wanted: a run
    that is not a whole number of tiles is a run this measurement has nothing to
    say about, and guessing at its tail would invent the reuse being counted.
    """
    if not data:
        return None
    try:
        found = FOUR_BIT.decode(bytes(data))
    except snesgfx.Truncated:
        return None
    return [tuple(one) for one in found]


def reuse(data):
    """What fraction of the tiles are not the first of their kind."""
    cut = tiles(data)
    if cut is None:
        return None
    return 1 - len(set(cut)) / len(cut)


def noise(length):
    """Random bytes, which is what a reading has to be compared against."""
    return os.urandom(length)


def survey(runs):
    """Every run measured, each against a control of its own length."""
    aligned = unaligned = 0
    real, control = [], []
    for data in runs:
        found = reuse(data)
        if found is None:
            unaligned += 1
            continue
        aligned += 1
        real.append(found)
        control.append(reuse(noise(len(data))) or 0.0)
    return Survey(
        aligned=aligned,
        unaligned=unaligned,
        meanReuse=sum(real) / len(real) if real else 0.0,
        meanReuseOfNoise=sum(control) / len(control) if control else 0.0,
        withAnyRepeat=sum(1 for one in real if one > 0),
        noiseWithAnyRepeat=sum(1 for one in control if one > 0),
    )


def table_for(where):
    """The stream table belonging to whichever cartridge this is."""
    name = "usastreams" if "usa" in Path(where).name.lower() else "jpstreams"
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STREAMS


def against(where, limit=None):
    """Every stream the cartridge declares, decompressed and measured."""
    rom = bytearray(Path(where).read_bytes())
    runs = []
    for off, length in table_for(where):
        if length < SMALLEST:
            continue
        found = sdd1.decompress(rom, off, length)
        runs.append(bytes(found.data) if hasattr(found, "data") else bytes(found))
        if limit is not None and len(runs) >= limit:
            break
    return survey(runs)


def main(argv, say=print):
    if not argv:
        say("usage: tile_shape.py <rom> [streams]")
        return 2

    where = Path(argv[0])
    if not where.is_file():
        say(f"{where} is not a file this can read")
        return 2

    limit = int(argv[1]) if len(argv) > 1 else None
    found = against(where, limit=limit)

    say(f"  {found.aligned} streams are a whole number of {TILE_BYTES} byte tiles")
    say(f"  {found.unaligned} are not, and are not measured")
    say(f"  duplicate tile fraction, decompressed: {found.meanReuse:.4f}")
    say(f"  the same, random bytes of equal length: {found.meanReuseOfNoise:.4f}")
    say(f"  sheets repeating any tile: {found.withAnyRepeat}, controls: {found.noiseWithAnyRepeat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
