"""Run the audio driver rather than read it.

The tests beside the patch check that the driver disassembles into the
instructions it was meant to become. That is worth having and it stops one step
short: a sequence of plausible instructions is not a working transfer, and the
thing the patch changes is a protocol rather than a listing.

So this drives the driver. The processor model executes the patched code out of
the ROM, the four ports it talks through are a small object standing in for the
main processor, and what comes out is where the bytes landed and how many
handshakes it took to put them there. The claim the patch makes is that it moves
three bytes per handshake where the original moved one, and that claim is now
measured on both builds rather than argued from a listing.

The port object is the whole trick. Reading a port hands the driver whatever the
main processor has placed there; writing the first port is the driver saying it
has taken the triple, which advances the payload and bumps the counter the driver
compares against. That is the handshake, and counting the writes counts it.

What the patched loop does with a triple is worth stating, because it is not what
it looks like. It does not write three bytes in a row. It writes one byte to each
of three destinations at the same index, so the transfer carries three streams
side by side rather than one stream three times as fast. The original loop
carries one stream one byte at a time, so the same number of bytes takes three
times the handshakes and the destination pointers the other two streams use are
never touched.

Usage:
    python3 tools/driver_run.py <rom>
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

spc700 = hardware.load("spc700")

PORT_BASE = 0xF4

PORTS = 4

TRIPLE = 3

DRIVER_BASE = 0x071C56

IMAGE_BYTES = 0x10000

FAST_LOOP = 0x0EDC

STOCK_LOOP = 0x0EC9
"""Where the driver as it ships takes its bytes, which is not where the patch does.

The original reads each port twice and compares, because a port can be read while
the other processor is halfway through writing it. The patched loop drops that
and reads three ports once each, which is most of where the time went.
"""

DESTINATION = 0x2000

SECOND = 0x3000

THIRD = 0x4000

POINTER = 0x0014

SECOND_POINTER = 0x00C8

THIRD_POINTER = 0x00CA

MEASURED_PAYLOAD = 0x30

ROOT = Path(__file__).resolve().parent.parent


def patcher():
    """The patch, loaded the way every other tool here loads it."""
    where = ROOT / "spcfast.py"
    spec = importlib.util.spec_from_file_location("spcfast", where)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Ports:
    """The four bytes the two processors talk through, with a main processor behind them.

    Everything outside the ports is ordinary memory. The ports themselves are a
    conversation: the driver reads a triple, says it has taken it, and the next
    triple appears. A payload shorter than a triple is padded rather than read
    past, because the driver reads three whatever the caller had left.
    """

    def __init__(self, payload, seed=spc700.UNSET_SEED):
        self.memory = spc700.Memory(fill=0, seed=seed)
        self.payload = bytes(payload)
        self.at = 0
        self.counter = 0
        self.handshakes = 0
        self.echoed = [0] * PORTS
        self.offer()

    @property
    def spent(self):
        return self.at >= len(self.payload)

    def offer(self):
        """Put the next triple and the counter where the driver will look for them."""
        for slot in range(1, TRIPLE + 1):
            at = self.at + slot - 1
            self.place(slot, self.payload[at] if at < len(self.payload) else 0)
        self.place(0, self.counter)

    def place(self, slot, value):
        self.memory.write8(PORT_BASE + slot, value & 0xFF)

    def read8(self, address):
        return self.memory.read8(address)

    def write8(self, address, value):
        if address == PORT_BASE:
            self.echoed[0] = value & 0xFF
            self.handshakes += 1
            self.at += TRIPLE
            self.counter = (self.counter + 1) & 0xFF
            self.offer()
            return
        if PORT_BASE < address < PORT_BASE + PORTS:
            self.echoed[address - PORT_BASE] = value & 0xFF
            return
        self.memory.write8(address, value)


class Transfer:
    """What a run of the driver did: where the bytes went and what it cost.

    The streams come back in the order the ports are read rather than the order
    the driver stores them, because that is the order the caller put them in.
    """

    def __init__(self, memory, streams, handshakes, steps):
        self.memory = memory
        self.streams = streams
        self.handshakes = handshakes
        self.steps = steps


def image_of(rom):
    """The block of the cartridge the audio processor is handed."""
    return bytes(rom[DRIVER_BASE : DRIVER_BASE + IMAGE_BYTES])


def loaded(image, payload, at):
    """A processor holding the driver, pointed at somewhere to put the bytes."""
    ports = Ports(payload)
    for address, value in enumerate(image):
        ports.memory.write8(address, value)
    point(ports, POINTER, at)
    point(ports, SECOND_POINTER, SECOND)
    point(ports, THIRD_POINTER, THIRD)
    ports.offer()
    return ports


def point(ports, pointer, at):
    ports.memory.write8(pointer, at & 0xFF)
    ports.memory.write8(pointer + 1, (at >> 8) & 0xFF)


def run(ports, entry, payload, at):
    """The driver from that entry point until its payload runs out.

    The processor starts with its registers holding arbitrary values, because
    hardware does. Two of them have to be said rather than inherited: the index
    the transfer counts with, and the flag that chooses which page the driver's
    pointers live in. The driver reaches this loop with the low page selected,
    and a harness that let the scramble decide would move the bytes somewhere
    else on some seeds and nowhere at all on others.

    Stopping is the other thing that has to be said. The driver acknowledges a
    triple before it has finished storing it, so a harness that stopped the
    moment the payload ran out would lose the last two bytes and blame the
    driver. It stops when the loop comes back round instead.
    """
    cpu = spc700.Cpu("spc700", ports)
    cpu.pc = entry
    cpu.y = 0
    cpu.p = False
    cpu.run_until(lambda machine: ports.spent and machine.pc == entry)
    carried = -(-len(payload) // TRIPLE)
    streams = tuple(
        bytes(ports.memory.read8(where + step) for step in range(carried))
        for where in (at, SECOND, THIRD)
    )
    return Transfer(ports, streams, ports.handshakes, cpu.steps)


def deliver(image, payload, at):
    """A transfer through the patched loop, which takes three bytes at a time."""
    return run(loaded(image, payload, at), FAST_LOOP, payload, at)


def deliver_one_at_a_time(image, payload, at):
    """A transfer through the original loop, which takes one.

    The original reads only the first byte of each triple, so the payload is
    spread out to match: one real byte and two the loop never looks at. That is
    what makes the two runs comparable, and the difference between them is the
    whole point of the patch.
    """
    return run(loaded(image, spread(payload), at), STOCK_LOOP, payload, at)


def spread(payload):
    """One byte per triple, because the original loop only reads the first."""
    laid = bytearray()
    for value in payload:
        laid.append(value)
        laid.extend((0, 0))
    return bytes(laid)


def main(argv):
    if not argv:
        print("usage: driver_run.py <rom>")
        return 2

    where = Path(argv[0])
    if not where.is_file():
        print(f"{where} is not a file this can read")
        return 2

    rom = bytearray(where.read_bytes())
    payload = bytes(range(MEASURED_PAYLOAD))

    stock = deliver_one_at_a_time(image_of(rom), payload, DESTINATION)
    fast = deliver(image_of(patcher().apply(rom)), payload, DESTINATION)

    print(f"  {len(payload)} bytes through the driver as it ships and as it is patched")
    print(f"  stock    {stock.handshakes:3d} handshakes, {stock.steps:5d} instructions")
    print(f"  patched  {fast.handshakes:3d} handshakes, {fast.steps:5d} instructions")
    for at, stream in zip((DESTINATION, SECOND, THIRD), fast.streams, strict=True):
        print(f"  landed at {at:#06x}: {stream[:8].hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
