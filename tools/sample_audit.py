"""Check the audio processor's sample bank as sound rather than as bytes.

The per-upload comparison in `compare_audio.py` answers whether the bytes that
left the cartridge arrived intact. It cannot answer the question the skip patch
actually raises, which is whether the bytes that are *already there* are still
the right ones. A skipped upload is correct only if the memory it declined to
write already held what the write would have put there, and a voice pointed at
half of an old sample and half of a new one reads perfectly valid bytes.

So this reads the bank the way the chip reads it. Each directory entry is walked
as a chain of nine byte blocks until one of them says it is the last, which is
the only thing that ends a sample. A chain that never says so is not a quiet
defect: the chip keeps reading, off the end of the sample, through whatever
follows it, until it finds a byte that happens to have the flag set.

Four faults are worth naming, and none of them is visible in a byte comparison:

A chain that runs off the end of memory before it terminates. A loop point that
does not land on a block boundary, which makes the chip resume mid block and
decode nonsense. A loop point outside the sample it belongs to. And two samples
that share bytes without being the same sample, where overwriting one damages
the other.

The last check is the one the patch needs. Given which voices are keyed on and
which addresses an upload is about to write, it reports any playing sample the
upload would walk through. That is the defect the plan named and the reason the
audio DSP is vendored here at all.

Running it needs an image of the audio processor's memory, which the harness in
`emu/` can dump. The tests beside this file build their images by hand, so they
prove the checks without needing a cartridge.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hardware  # noqa: E402

sdsp = hardware.load("sdsp")

APU_RAM = 0x10000

BLOCK_BYTES = 9

DIRECTORY_BYTES = 4

MAX_BLOCKS = APU_RAM // BLOCK_BYTES

END_FLAG = 0x01

RUNS_OFF = "runs off the end without ending"

LOOP_UNALIGNED = "loop point is not on a block boundary"

LOOP_OUTSIDE = "loop point is outside the sample"

DIRECTORY_WRITTEN = "the directory entry itself is being written"

OVERWRITTEN = "a playing sample is being written"

RENDER_SAMPLES = 512

REG_MVOLL = 0x0C
REG_MVOLR = 0x1C
REG_DIR = 0x5D
REG_KON = 0x4C
REG_FLG = 0x6C
REG_ENDX = 0x7C
V_SRCN = 0x04
V_PITCHL = 0x02
V_PITCHH = 0x03
V_VOLL = 0x00
V_VOLR = 0x01
V_ADSR0 = 0x05
V_GAIN = 0x07

FULL_VOLUME = 0x7F

UNIT_PITCH = 0x1000

DIRECT_GAIN = 0x7F


class Unreadable(Exception):
    pass


class Chain:
    """What walking one sample found: how far it reached, and what stopped it."""

    def __init__(self, start, blocks, reach, fault):
        self.start = start
        self.blocks = blocks
        self.reach = reach
        self.fault = fault

    def __repr__(self):
        return f"<Chain at {self.start:#06x}, {self.blocks} blocks, {self.fault or 'ends'}>"


class Fault:
    """One thing wrong with one sample."""

    def __init__(self, sample, fault, at):
        self.sample = sample
        self.fault = fault
        self.at = at

    def __eq__(self, other):
        return (self.sample, self.fault, self.at) == (other.sample, other.fault, other.at)

    def __hash__(self):
        return hash((self.sample, self.fault, self.at))

    def __repr__(self):
        return f"<Fault sample {self.sample} at {self.at:#06x}: {self.fault}>"


def load(image):
    """An audio memory image, refused unless it is the whole sixty four kilobytes."""
    if len(image) != APU_RAM:
        raise Unreadable(f"an audio memory image is {APU_RAM} bytes, not {len(image)}")
    return bytearray(image)


def entry(ram, directory, sample):
    """The start and loop addresses the directory holds for that sample."""
    at = (directory + sample * DIRECTORY_BYTES) & 0xFFFF
    start = ram[at] | (ram[(at + 1) & 0xFFFF] << 8)
    loop = ram[(at + 2) & 0xFFFF] | (ram[(at + 3) & 0xFFFF] << 8)
    return start, loop


def chain(ram, start):
    """Walk a sample the way the chip walks it, and report where it stops.

    Nothing bounds this walk except the flag in a block header, so the bound here
    is the number of blocks that could fit in memory at all. Reaching it means the
    chip would not have stopped either.
    """
    at = start
    for blocks in range(1, MAX_BLOCKS + 1):
        if at + BLOCK_BYTES > APU_RAM:
            return Chain(start, blocks - 1, range(start, min(at, APU_RAM)), RUNS_OFF)
        header = ram[at]
        at += BLOCK_BYTES
        if header & END_FLAG:
            return Chain(start, blocks, range(start, at), None)
    return Chain(start, MAX_BLOCKS, range(start, APU_RAM), RUNS_OFF)


def _prepare(ram, directory, sample):
    memory = sdsp.Memory()
    for address, value in enumerate(ram):
        memory.write8(address, value)
    chip = sdsp.Chip("s-dsp", memory)
    chip.write(REG_FLG, 0x00)
    chip.write(REG_MVOLL, FULL_VOLUME)
    chip.write(REG_MVOLR, FULL_VOLUME)
    chip.write(REG_DIR, (directory >> 8) & 0xFF)
    chip.write(V_SRCN, sample & 0xFF)
    chip.write(V_PITCHL, UNIT_PITCH & 0xFF)
    chip.write(V_PITCHH, UNIT_PITCH >> 8)
    chip.write(V_VOLL, FULL_VOLUME)
    chip.write(V_VOLR, FULL_VOLUME)
    chip.write(V_ADSR0, 0x00)
    chip.write(V_GAIN, DIRECT_GAIN)
    chip.write(REG_KON, 0x01)
    return chip


def play(ram, directory, sample, samples=RENDER_SAMPLES):
    """What the chip produces from that sample, through the real decoder."""
    return _prepare(ram, directory, sample).render(samples)


def reaches_end(ram, directory, sample, samples=RENDER_SAMPLES):
    """Whether the chip reports finishing the sample within that many samples."""
    chip = _prepare(ram, directory, sample)
    chip.render(samples)
    return bool(chip.read(REG_ENDX) & 0x01)


def faults(ram, directory, used):
    """Everything wrong with the samples that are actually in use."""
    found = []
    for sample in used:
        start, loop = entry(ram, directory, sample)
        walked = chain(ram, start)
        if walked.fault:
            found.append(Fault(sample, walked.fault, start))
            continue
        if loop not in walked.reach:
            found.append(Fault(sample, LOOP_OUTSIDE, loop))
        elif (loop - start) % BLOCK_BYTES:
            found.append(Fault(sample, LOOP_UNALIGNED, loop))
    return found


def overlaps(ram, directory, used):
    """Pairs of different samples that share bytes, which one upload can damage."""
    reached = {}
    for sample in used:
        start, _ = entry(ram, directory, sample)
        walked = chain(ram, start)
        if walked.fault is None:
            reached[sample] = (start, set(walked.reach))

    found = []
    names = sorted(reached)
    for first_index, first in enumerate(names):
        for second in names[first_index + 1 :]:
            if reached[first][0] == reached[second][0]:
                continue
            shared = reached[first][1] & reached[second][1]
            if shared:
                found.append((first, second, min(shared)))
    return found


def collisions(ram, directory, playing, written):
    """Which playing samples an upload would walk through while they are playing."""
    touched = set(written)
    found = []
    for sample in playing:
        at = (directory + sample * DIRECTORY_BYTES) & 0xFFFF
        if touched & set(range(at, at + DIRECTORY_BYTES)):
            found.append(Fault(sample, DIRECTORY_WRITTEN, at))
            continue
        start, _ = entry(ram, directory, sample)
        walked = chain(ram, start)
        shared = touched & set(walked.reach)
        if shared:
            found.append(Fault(sample, OVERWRITTEN, min(shared)))
    return found


def report(ram, directory, used):
    """Everything this can say about a bank, as lines a person reads."""
    lines = []
    for fault in faults(ram, directory, used):
        lines.append(f"  sample {fault.sample:3d} at {fault.at:#06x}: {fault.fault}")
    for first, second, at in overlaps(ram, directory, used):
        lines.append(f"  samples {first:3d} and {second:3d} share {at:#06x}")
    if not lines:
        lines.append(f"  {len(list(used))} samples, all well formed and none sharing bytes")
    return lines


def main(argv):
    if len(argv) < 2:
        print("usage: sample_audit.py <apu-ram-image> <directory-page> [sample ...]")
        return 2
    ram = load(Path(argv[0]).read_bytes())
    directory = int(argv[1], 0)
    used = [int(name, 0) for name in argv[2:]] or range(0x100)
    for line in report(ram, directory, used):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
