import sys
from collections import namedtuple
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

emu65816 = hardware.load("mos65xx")
dump = hardware.load("romimage").dump
mapper = hardware.load("mapper")

import rombuild  # noqa: E402

ENTRY_POINTS = {0x00: 0x35CD84, 0x10: 0x35CDD0, 0x70: 0x35CE1C}
VARIABLE_ENTRY = 0x35CE68

EXAMPLE_LIMIT = 5

DMA_BASE = 0x4300
DMA_TRIGGER = 0x420B
DMA_BLOCK = range(0x4300, 0x4380)
FIXED_ADDRESS_BIT = 0x08
ARMED_DMAP = 0x09
STEP_LIMIT = 400_000
STACK_TOP = 0x01FF
WINDOW_BASE = 0xC0

Outcome = namedtuple("Outcome", "destination dmap cpu")


class SnesMemory:
    def __init__(self, image: bytes | bytearray, banks: int = rombuild.IMAGE_BANKS) -> None:
        self.image = image
        self.banks = banks
        self.ram: dict[int, int] = {}
        self.triggered: dict[int, int] | None = None

    def read8(self, address: int) -> int:
        bank, offset = address >> 16, address & 0xFFFF
        if bank in rombuild.WRAM_BANKS:
            return self.ram.get(address, 0x00)
        if (bank < 0x40 or 0x80 <= bank < 0xC0) and offset < mapper.HALF:
            return self.ram.get(address, 0x00)
        at = mapper.address_to_file(bank, offset, self.banks)
        assert isinstance(at, int)
        return self.image[at]

    def write8(self, address: int, value: int) -> None:
        self.ram[address] = value & 0xFF
        if address == DMA_TRIGGER:
            self.triggered = {a: self.ram.get(a, 0x00) for a in DMA_BLOCK}


def dma_source(snapshot: bytes | bytearray, channel: int = 0x00) -> int:
    base = DMA_BASE + channel
    return snapshot[base + 2] | (snapshot[base + 3] << 8) | (snapshot[base + 4] << 16)


def translate(
    memory: Any,
    source: int,
    channel: int = 0x00,
    entry: Any = None,
    dmap: int = ARMED_DMAP,
    **registers: Any,
) -> Any:
    """Run the translation the way the cartridge runs it, and read the result.

    Native mode is not a detail. The processor powers on in emulation mode, where
    the instruction that widens the accumulator and index registers is defined to
    do nothing, and the routine's first act is to widen them. Left in emulation
    mode it loads eight bits of a sixteen bit address, indexes with a register
    that wraps at two hundred and fifty six, and scans forever without finding
    what it is looking for.

    The cartridge reaches this routine from native-mode code, so the harness has
    to start where the caller does.
    """
    base = DMA_BASE + channel
    memory.ram.clear()
    memory.ram[base] = dmap
    memory.ram[base + 2] = source & 0xFF
    memory.ram[base + 3] = (source >> 8) & 0xFF
    memory.ram[base + 4] = WINDOW_BASE + (source >> 16)

    cpu = emu65816.Cpu("65816", memory)
    cpu.emulation = False
    cpu.s = STACK_TOP
    cpu.m8 = True
    cpu.x8 = True
    cpu.a = 0x0001
    for name, value in registers.items():
        setattr(cpu, name, value)

    cpu.call(entry if entry is not None else ENTRY_POINTS[channel], limit=STEP_LIMIT)

    destination = memory.ram[base + 2] | (memory.ram[base + 3] << 8) | (memory.ram[base + 4] << 16)
    return Outcome(destination, memory.ram[base], cpu)


def walk(
    memory: Any,
    entries: list[Any],
    expected: dict[int, int],
    say: Callable[[str], None],
    run: Callable[[Any, int], Any] = translate,
) -> int:
    """Every stream translated on the processor, and where it disagreed.

    The translation is a parameter so the reporting can be driven without an
    assembled image and without running the processor over the whole table.
    """
    failures = 0
    for entry in entries:
        outcome = run(memory, entry.source)
        if outcome.destination != expected[entry.index]:
            failures += 1
            if failures <= EXAMPLE_LIMIT:
                say(
                    f"  stream {entry.index}: got {outcome.destination:#08x}, "
                    f"want {expected[entry.index]:#08x}"
                )
        elif outcome.dmap & FIXED_ADDRESS_BIT:
            failures += 1
            say(f"  stream {entry.index}: fixed-address bit still set")
    return failures


def main(
    argv: list[str] | None = None,
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    argv = sys.argv if argv is None else argv
    complain = say if complain is None else complain

    if len(argv) < 4:
        complain("usage: patchrun.py <built-image> <patched-rom> <tagged-rom>")
        return 2

    image = dump.read(argv[1])
    entries = rombuild.load_entries(dump.read(argv[3]))
    expected = rombuild.build(dump.read(argv[2]), entries).destinations

    failures = walk(SnesMemory(image), entries, expected, say)
    say(f"  executed {len(entries):,} streams, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
