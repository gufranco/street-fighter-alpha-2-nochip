import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump

cpu = hardware.load("mos65xx")
mapper = hardware.load("mapper")


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patchrun = load_module("patchrun")
rombuild = load_module("rombuild")

IMAGE = ROOT / "build" / "sfa2-usa-nochip.sfc"
PATCHED = ROOT / "build" / "sfa2-usa-patched.sfc"
TAGGED = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"


@unittest.skipUnless(  # pragma: no cover
    IMAGE.exists() and PATCHED.exists() and TAGGED.exists(),
    "the built image is not present",
)
class TranslationTest(unittest.TestCase):
    entries: ClassVar[Any]
    expected: ClassVar[Any]
    image: ClassVar[Any]
    memory: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.image = dump.read(IMAGE)
        cls.entries = rombuild.load_entries(dump.read(TAGGED))
        cls.expected = rombuild.build(dump.read(PATCHED), cls.entries).destinations
        cls.memory = patchrun.SnesMemory(cls.image)

    def test_every_stream_translates_to_its_allocated_address(self) -> None:
        wrong: list[Any] = []
        for entry in self.entries:
            outcome = patchrun.translate(self.memory, entry.source)

            if outcome.destination != self.expected[entry.index]:
                wrong.append(entry.index)

        self.assertEqual(wrong, [])

    def test_every_stream_leaves_the_fixed_address_bit_clear(self) -> None:
        for entry in self.entries[:600]:
            outcome = patchrun.translate(self.memory, entry.source)

            self.assertFalse(outcome.dmap & patchrun.FIXED_ADDRESS_BIT)

    def test_the_rest_of_the_dmap_byte_is_untouched(self) -> None:
        outcome = patchrun.translate(self.memory, self.entries[0].source, dmap=0xF9)

        self.assertEqual(outcome.dmap, 0xF9 & ~patchrun.FIXED_ADDRESS_BIT)

    def test_the_other_fixed_channels_translate_the_same_way(self) -> None:
        for channel in (0x10, 0x70):
            for entry in self.entries[:200]:
                outcome = patchrun.translate(self.memory, entry.source, channel=channel)

                self.assertEqual(
                    outcome.destination,
                    self.expected[entry.index],
                    f"channel {channel:#04x}",
                )
                self.assertFalse(outcome.dmap & patchrun.FIXED_ADDRESS_BIT)

    def test_the_variable_channel_entry_reads_its_offset_from_y(self) -> None:
        for channel in (0x00, 0x10, 0x70):
            for entry in self.entries[:100]:
                outcome = patchrun.translate(
                    self.memory,
                    entry.source,
                    channel=channel,
                    entry=patchrun.VARIABLE_ENTRY,
                    y=channel,
                )

                self.assertEqual(
                    outcome.destination, self.expected[entry.index], f"y={channel:#04x}"
                )
                self.assertFalse(outcome.dmap & patchrun.FIXED_ADDRESS_BIT)

    def test_an_eight_bit_callers_registers_come_back_untouched(self) -> None:
        for entry in self.entries[:300]:
            outcome = patchrun.translate(
                self.memory, entry.source, a=0x0001, x=0x0034, y=0x0078, c=True
            )

            self.assertEqual(outcome.cpu.a & 0xFF, 0x01)
            self.assertEqual(outcome.cpu.x, 0x34)
            self.assertEqual(outcome.cpu.y, 0x78)
            self.assertTrue(outcome.cpu.c)

    def test_a_sixteen_bit_callers_registers_come_back_untouched(self) -> None:
        for entry in self.entries[:300]:
            outcome = patchrun.translate(
                self.memory,
                entry.source,
                m8=False,
                x8=False,
                a=0x1001,
                x=0x1234,
                y=0x5678,
                c=True,
            )

            self.assertEqual(outcome.cpu.a, 0x1001)
            self.assertEqual(outcome.cpu.x, 0x1234)
            self.assertEqual(outcome.cpu.y, 0x5678)
            self.assertTrue(outcome.cpu.c)

    def test_a_narrow_caller_gets_back_only_what_it_could_hold(self) -> None:
        """The high byte of an index register does not survive an eight bit caller.

        The routine widens the registers, pushes them whole, and restores the
        caller's status byte on the way out. Restoring a status byte that says the
        index registers are eight bits wide clears their high bytes, so a caller
        running narrow cannot smuggle sixteen bits through the call. That is the
        processor's rule rather than this routine's, and a test that expected
        otherwise was reading a model that did not implement it.
        """
        outcome = patchrun.translate(
            self.memory, self.entries[0].source, a=0x0001, x=0x1234, y=0x5678
        )

        self.assertEqual(outcome.cpu.x, 0x34)
        self.assertEqual(outcome.cpu.y, 0x78)

    def test_the_stack_is_balanced_on_return(self) -> None:
        for entry in self.entries[:300]:
            outcome = patchrun.translate(self.memory, entry.source)

            self.assertEqual(outcome.cpu.s, patchrun.STACK_TOP)

    def test_the_widths_the_caller_had_are_restored(self) -> None:
        outcome = patchrun.translate(self.memory, self.entries[0].source)

        self.assertTrue(outcome.cpu.m8)
        self.assertTrue(outcome.cpu.x8)

    def test_the_variable_channel_entry_also_balances_its_stack(self) -> None:
        for entry in self.entries[:200]:
            outcome = patchrun.translate(
                self.memory,
                entry.source,
                channel=0x70,
                entry=patchrun.VARIABLE_ENTRY,
                y=0x70,
            )

            self.assertEqual(outcome.cpu.s, patchrun.STACK_TOP)
            self.assertEqual(outcome.cpu.y, 0x70)


STAR_OCEAN = ROOT / "roms" / "star-ocean-jp-nochip-96mbit.sfc"
STAR_OCEAN_BANKS = 192
NEVIKSTI_ROUTINE = 0x00F063
STAR_OCEAN_STREAMS = (
    (0x0D5C85, 0x010000),
    (0x0E0000, 0x018000),
    (0x0DB2FD, 0x050000),
    (0x137EA8, 0x078000),
    (0x14C11B, 0x088000),
    (0x18D178, 0x0E6000),
    (0x134327, 0x168000),
    (0x16FB45, 0x14E000),
)


@unittest.skipUnless(STAR_OCEAN.exists(), "the star ocean build is not present")  # pragma: no cover
class ReferenceBuildTest(unittest.TestCase):
    """Runs neviksti's own translation routine, from his hardware-proven build,
    through the same interpreter and address model this project uses. It is the
    closest available check that the mapping is right, short of the SF7."""

    image: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.image = dump.read(STAR_OCEAN)

    def run_reference(self, source: int) -> Any:
        memory = patchrun.SnesMemory(self.image, banks=STAR_OCEAN_BANKS)
        memory.ram[patchrun.DMA_BASE] = patchrun.ARMED_DMAP
        memory.ram[patchrun.DMA_BASE + 2] = source & 0xFF
        memory.ram[patchrun.DMA_BASE + 3] = (source >> 8) & 0xFF
        memory.ram[patchrun.DMA_BASE + 4] = patchrun.WINDOW_BASE + (source >> 16)

        cpu = patchrun.emu65816.Cpu("65816", memory)
        cpu.s = patchrun.STACK_TOP
        cpu.m8 = True
        cpu.x8 = False
        cpu.call(NEVIKSTI_ROUTINE)
        return memory

    def test_the_reference_routine_reaches_the_known_output_of_each_stream(self) -> None:
        for source, expected_file in STAR_OCEAN_STREAMS:
            memory = self.run_reference(source)
            destination = patchrun.dma_source(memory.triggered)

            landed = patchrun.mapper.snes_to_file(
                destination >> 16, destination & 0xFFFF, STAR_OCEAN_BANKS
            )

            self.assertEqual(landed, expected_file, f"source {source:#08x}")

    def test_the_reference_routine_also_clears_the_fixed_address_bit(self) -> None:
        for source, _ in STAR_OCEAN_STREAMS:
            memory = self.run_reference(source)

            self.assertFalse(memory.triggered[patchrun.DMA_BASE] & patchrun.FIXED_ADDRESS_BIT)

    def test_the_reference_routine_starts_a_transfer(self) -> None:
        memory = self.run_reference(STAR_OCEAN_STREAMS[0][0])

        self.assertIsNotNone(memory.triggered)


class EntryTest(unittest.TestCase):
    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        complained: list[Any] = []

        code = patchrun.main(["patchrun.py"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", complained[0])

    @unittest.skipUnless(  # pragma: no cover
        IMAGE.exists() and PATCHED.exists() and TAGGED.exists(),
        "the built image is not present",
    )
    def test_a_whole_run_reports_how_many_streams_it_executed(self) -> None:
        said: list[Any] = []

        code = patchrun.main(
            ["patchrun.py", str(IMAGE), str(PATCHED), str(TAGGED)], say=said.append
        )

        self.assertEqual(code, 0)
        self.assertIn("executed", said[-1])


class MemoryTest(unittest.TestCase):
    """What the processor sees at each kind of address."""

    def memory(self) -> Any:
        return patchrun.SnesMemory(bytes(rombuild.IMAGE_SIZE))

    def test_a_work_ram_bank_reads_from_ram(self) -> None:
        memory = self.memory()
        memory.write8(0x7E1234, 0xAB)

        self.assertEqual(memory.read8(0x7E1234), 0xAB)

    def test_the_second_work_ram_bank_does_too(self) -> None:
        memory = self.memory()
        memory.write8(0x7F1234, 0xCD)

        self.assertEqual(memory.read8(0x7F1234), 0xCD)

    def test_a_work_ram_address_never_written_reads_as_zero(self) -> None:
        self.assertEqual(self.memory().read8(0x7E1234), 0x00)

    def test_the_low_half_of_a_low_bank_is_ram_rather_than_cartridge(self) -> None:
        memory = self.memory()
        memory.write8(0x001234, 0xEF)

        self.assertEqual(memory.read8(0x001234), 0xEF)

    def test_the_high_half_of_a_low_bank_is_cartridge(self) -> None:
        self.assertEqual(self.memory().read8(0x008000), 0x00)


class WalkTest(unittest.TestCase):
    """Reporting where the processor disagreed with the allocation.

    The translation is passed in, so the reporting can be driven without an
    assembled image and without running the processor over the whole table.
    """

    class Entry:
        def __init__(self, index: int, source: int) -> None:
            self.index, self.source = index, source

    def walk_with(
        self, outcomes: dict[int, tuple[int, int]], want: dict[int, int]
    ) -> tuple[list[str], int]:
        said: list[str] = []
        entries = [self.Entry(index, 0x100000 + index) for index in want]

        def _translate(_memory: Any, source: int) -> Any:
            destination, dmap = outcomes[source - 0x100000]
            return patchrun.Outcome(destination, dmap, None)

        return said, patchrun.walk(None, entries, want, said.append, _translate)

    def test_a_stream_that_lands_where_it_was_allocated_is_not_a_failure(self) -> None:
        said, failures = self.walk_with({0: (0x0C4000, 0x00)}, {0: 0x0C4000})

        self.assertEqual((failures, said), (0, []))

    def test_a_stream_that_lands_elsewhere_is_reported(self) -> None:
        said, failures = self.walk_with({0: (0x0C5000, 0x00)}, {0: 0x0C4000})

        self.assertEqual((failures, "got 0x0c5000" in said[0]), (1, True))

    def test_a_stream_that_kept_the_fixed_address_bit_is_reported(self) -> None:
        said, failures = self.walk_with({0: (0x0C4000, patchrun.FIXED_ADDRESS_BIT)}, {0: 0x0C4000})

        self.assertEqual((failures, "fixed-address bit" in said[0]), (1, True))

    def test_only_the_first_few_wrong_destinations_are_named(self) -> None:
        count = patchrun.EXAMPLE_LIMIT + 3
        outcomes = dict.fromkeys(range(count), (806912, 0))
        want = dict.fromkeys(range(count), 0x0C4000)

        said, failures = self.walk_with(outcomes, want)

        self.assertEqual((failures, len(said)), (count, patchrun.EXAMPLE_LIMIT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
