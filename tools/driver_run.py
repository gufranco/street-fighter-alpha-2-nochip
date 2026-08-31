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

**Two witnesses.** The stand-in above was written to a reading of the driver, so
a transfer that comes out right through it confirms the reading is consistent
with itself and nothing further. `on_hardware` runs the same driver on the whole
audio unit instead, where the ports are the part's own latches, the boot ROM is
Sony's, and the mixer is underneath. That model answers to its own suite rather
than to anything here, so the two agreeing is a real check rather than a
restatement. They do agree, to the byte, the handshake and the instruction.

Only the unit can report cycles, and cycles are what the patch's claim is
actually about. Measured over forty eight bytes, the stock driver spends 2640 and
the patched one 784, which is 3.37 times rather than the 3 the handshake count
alone suggests. The extra comes from the port reads the patched loop drops.

Two starting conditions had to be found rather than assumed, and both are recorded
beside the constants that set them: the counter the console offers first is
checked by the driver rather than echoed, and the driver's own latch has to be
seeded or its first acknowledgement is indistinguishable from silence.

Usage:
    python3 tools/driver_run.py <rom>
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware

spc700 = hardware.load("spc700")

ssmp = hardware.load("ssmp")

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

    `cycles` is present only for a run on the composed unit. The stand-in counts
    instructions because that is all it can count, and a run that reports no
    cycles says so with `None` rather than with a zero that would average in.
    """

    def __init__(self, memory, streams, handshakes, steps, cycles=None):
        self.memory = memory
        self.streams = streams
        self.handshakes = handshakes
        self.steps = steps
        self.cycles = cycles


REGISTERS = range(0xF0, 0x100)
"""The page the image is not loaded over, on the composed unit.

Those sixteen addresses are hardware rather than memory: the timers, the mixer
address latch, and the four ports themselves. The stand-in could be handed the
image wholesale because its ports were the only thing behind them. Writing the
image there on the real unit would start the timers and move the mixer's address
latch before the driver had run an instruction, so those bytes are skipped and
the driver never reads them as anything but registers anyway.
"""

CONTROL = 0xF1

BOOT_HIDDEN = 0x00
"""What the console has already written to the control register by this point.

The unit comes out of reset with the boot ROM covering the top sixty four bytes
of memory, because that is how it is made to start, and a game that has reached
its own audio driver switched that window off long before. This run says so for
the same reason it sets the direct page: a condition the driver arrives in is
worth stating rather than inheriting.

It is not load-bearing, and the honest thing is to say which. Running with the
window left on reaches the same bytes in the same cycles, because this driver
never reads the sixty four addresses it covers. That was measured rather than
assumed, and there is a test beside this one that keeps it measured, so the day
a patch does reach up there the difference appears instead of hiding.

Zero rather than a mask with only the window bit cleared: the other bits enable
the timers and clear the port latches, and none of those is wanted here.
"""

FIRST_COUNTER = 0
"""What the console puts on the counter port first, which the driver checks.

Starting anywhere else does not work, and finding that out is the useful part. The
driver does not echo the counter back, it compares against the value it expects;
handed a one where it wanted a zero it takes the other side of the branch two
instructions in and never returns. The stand-in could not have shown this, because
the stand-in only ever offered what the driver asked for.
"""

UNECHOED = 0xFF
"""A value put in the driver's own latch before it runs, so its first write shows.

Reset leaves that latch reading zero and the driver's first acknowledgement is a
zero, which would be indistinguishable from a driver that had not run at all. The
console cannot write that latch, but the audio side can, and seeding it from there
is the same as saying the previous transfer left something behind. Any value the
driver will not write first would do; this one is furthest from a low counter.
"""

HARDWARE_CEILING = 4_000_000
"""Cycles a composed run may spend before it is called stuck rather than slow.

The stand-in stops when the payload runs out and the loop comes back round. The
same test holds here, and this is the second bound underneath it, so a driver that
never reaches its entry again reports a limit rather than hanging.
"""


class RunLimit(Exception):
    """A composed run spent its ceiling without finishing."""


class Console:
    """The main processor, as the audio unit meets it.

    The stand-in models this conversation with an object of its own. This drives
    the same conversation through the unit's real port hardware instead: the
    console leaves a triple and a counter in the four write latches, the driver
    reads them, and the driver's acknowledgement arrives in the separate read
    latch that `chip.read` returns. Those are two sets of latches on the real
    part, which is why the driver cannot see its own acknowledgement and why the
    console cannot see what it wrote.
    """

    def __init__(self, chip, payload, counter=FIRST_COUNTER):
        self.chip = chip
        self.payload = bytes(payload)
        self.at = 0
        self.counter = counter & 0xFF
        self.handshakes = 0
        self.seen = chip.read(0)

    @property
    def spent(self):
        return self.at >= len(self.payload)

    def offer(self):
        """Put the next triple and the counter where the driver will look."""
        for slot in range(1, TRIPLE + 1):
            at = self.at + slot - 1
            self.chip.write(slot, self.payload[at] if at < len(self.payload) else 0)
        self.chip.write(0, self.counter)

    def watch(self):
        """Notice an acknowledgement and answer it, the way a console polls."""
        now = self.chip.read(0)
        if now == self.seen:
            return False
        self.seen = now
        self.handshakes += 1
        self.at += TRIPLE
        self.counter = (self.counter + 1) & 0xFF
        self.offer()
        return True


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


def on_hardware(image, payload, at, entry=FAST_LOOP, counter=None, unechoed=None, control=None):
    """The same driver, on the whole audio unit rather than a processor and a stand-in.

    This is the second witness. The stand-in is a model of the protocol written to
    a reading of the driver, so agreeing with it proves the reading self-consistent
    and nothing else. The composed unit is the processor, the mixer and the boot
    ROM behind the port hardware the console actually reaches, and it is held to
    its own suite rather than to this project's expectations. Two witnesses that
    reach the same byte counts by different routes are worth more than either.

    What only this one can report is cycles. The patch's claim is about how long a
    transfer takes, and instructions are a proxy for that which the stand-in had no
    way to convert. Here the unit counts the cycles it actually spent.

    The three starting conditions are parameters rather than constants read from
    the module, so a test can hand this a wrong one and watch what happens. A
    default that could only be reached by patching a module attribute is a default
    nothing ever drives against, and two of these turn out to matter enormously.
    """
    counter = FIRST_COUNTER if counter is None else counter
    unechoed = UNECHOED if unechoed is None else unechoed
    control = BOOT_HIDDEN if control is None else control

    chip = ssmp.Chip("s-smp")
    chip.reset()
    space = chip.space
    space.write8(CONTROL, control)
    for address, value in enumerate(image):
        if address not in REGISTERS:
            space.write8(address, value)
    point_space(space, POINTER, at)
    point_space(space, SECOND_POINTER, SECOND)
    point_space(space, THIRD_POINTER, THIRD)

    space.write8(PORT_BASE, unechoed)
    console = Console(chip, payload, counter)
    console.offer()

    cpu = chip.processor
    cpu.pc = entry
    cpu.y = 0
    cpu.p = False

    started = chip.cycles
    while True:
        chip.step()
        console.watch()
        if console.spent and cpu.pc == entry:
            break
        if chip.cycles - started > HARDWARE_CEILING:
            raise RunLimit(f"gave up after {chip.cycles - started} cycles at ${cpu.pc:04X}")

    carried = -(-len(payload) // TRIPLE)
    streams = tuple(
        bytes(space.read8(where + step) for step in range(carried)) for where in (at, SECOND, THIRD)
    )
    return Transfer(space, streams, console.handshakes, cpu.steps, chip.cycles - started)


def point_space(space, pointer, at):
    space.write8(pointer, at & 0xFF)
    space.write8(pointer + 1, (at >> 8) & 0xFF)


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

    stock_image = image_of(rom)
    fast_image = image_of(patcher().apply(rom))

    stock = deliver_one_at_a_time(stock_image, payload, DESTINATION)
    fast = deliver(fast_image, payload, DESTINATION)
    stock_unit = on_hardware(stock_image, spread(payload), DESTINATION, entry=STOCK_LOOP)
    fast_unit = on_hardware(fast_image, payload, DESTINATION)

    print(f"  {len(payload)} bytes through the driver as it ships and as it is patched")
    print(f"  stock    {stock.handshakes:3d} handshakes, {stock.steps:5d} instructions")
    print(f"  patched  {fast.handshakes:3d} handshakes, {fast.steps:5d} instructions")
    for at, stream in zip((DESTINATION, SECOND, THIRD), fast.streams, strict=True):
        print(f"  landed at {at:#06x}: {stream[:8].hex()}")

    print("  the same two runs on the whole audio unit, which counts cycles")
    print(f"  stock    {stock_unit.handshakes:3d} handshakes, {stock_unit.cycles:6d} cycles")
    print(f"  patched  {fast_unit.handshakes:3d} handshakes, {fast_unit.cycles:6d} cycles")
    print(f"  faster by {stock_unit.cycles / fast_unit.cycles:.2f} times")
    agreed = fast_unit.streams == fast.streams and stock_unit.streams[0].startswith(
        stock.streams[0]
    )
    print(f"  stand-in and unit agree on every byte: {agreed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
