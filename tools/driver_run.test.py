import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, where)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver_run = load_module("driver_run", Path(__file__).resolve().parent / "driver_run.py")
spcfast = load_module("spcfast", ROOT / "spcfast.py")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"

NEEDS_A_DUMP = unittest.skipUnless(
    USA.exists(), "the retail dump is not on this machine, and nothing here ships one"
)
"""What the driver actually does can only be run against the cartridge it came from.

Nobody may distribute that file, so on a build machine these report as skipped
rather than as passed. Everything that can be checked without one is checked
without one, and is above.
"""


def _unit_builds() -> bool:
    try:
        driver_run.ssmp.Chip("s-smp")
    except (driver_run.ssmp.NoBootRom, driver_run.ssmp.Corrupt, OSError):
        return False
    return True


NEEDS_THE_BOOT_ROM = unittest.skipUnless(
    _unit_builds(),
    "the audio unit needs Sony's boot program, which nobody may distribute",
)
"""The composed unit will not start without sixty four bytes Sony wrote.

Those are an artifact like the cartridge is, so a machine without them skips the
runs that need one rather than failing. This is asked by building a unit rather
than by looking for a file, because where the model searches for it is the
model's business and not this file's.
"""

JP = ROOT / "roms" / "sfz2-jp-final.sfc"

PAYLOAD = bytes(range(0x30))


class PortsTest(unittest.TestCase):
    def test_the_first_triple_is_ready_before_anything_runs(self) -> None:
        ports = driver_run.Ports(bytes(range(6)))

        self.assertEqual([ports.read8(at) for at in range(0xF5, 0xF8)], [0, 1, 2])

    def test_the_counter_starts_where_the_driver_starts(self) -> None:
        ports = driver_run.Ports(bytes(range(6)))

        self.assertEqual(ports.read8(0xF4), 0)

    def test_an_echo_advances_to_the_next_triple(self) -> None:
        ports = driver_run.Ports(bytes(range(6)))

        ports.write8(0xF4, 0)

        self.assertEqual([ports.read8(at) for at in range(0xF5, 0xF8)], [3, 4, 5])

    def test_and_moves_the_counter_on_with_it(self) -> None:
        ports = driver_run.Ports(bytes(range(6)))

        ports.write8(0xF4, 0)

        self.assertEqual(ports.read8(0xF4), 1)

    def test_the_counter_wraps_at_a_byte(self) -> None:
        ports = driver_run.Ports(bytes(3 * 300))
        for step in range(300):
            ports.write8(0xF4, step & 0xFF)

        self.assertEqual(ports.read8(0xF4), 300 & 0xFF)

    def test_a_payload_that_runs_out_says_so(self) -> None:
        ports = driver_run.Ports(bytes(3))

        ports.write8(0xF4, 0)

        self.assertTrue(ports.spent)

    def test_and_one_that_has_not_says_that_instead(self) -> None:
        ports = driver_run.Ports(bytes(6))

        ports.write8(0xF4, 0)

        self.assertFalse(ports.spent)

    def test_a_payload_shorter_than_a_triple_is_padded_rather_than_read_past(self) -> None:
        ports = driver_run.Ports(bytes([9]))

        self.assertEqual([ports.read8(at) for at in range(0xF5, 0xF8)], [9, 0, 0])

    def test_everything_outside_the_ports_is_ordinary_memory(self) -> None:
        ports = driver_run.Ports(bytes(3))

        ports.write8(0x0200, 0x5A)

        self.assertEqual(ports.read8(0x0200), 0x5A)

    def test_and_the_driver_echo_is_remembered_for_the_caller_to_read(self) -> None:
        ports = driver_run.Ports(bytes(6))

        ports.write8(0xF5, 0x77)

        self.assertEqual(ports.echoed[1], 0x77)

    def test_an_echo_on_a_port_that_is_not_the_first_does_not_advance_anything(self) -> None:
        ports = driver_run.Ports(bytes(6))

        ports.write8(0xF6, 0x11)

        self.assertEqual(ports.handshakes, 0)


class SpreadTest(unittest.TestCase):
    def test_spreading_leaves_one_byte_per_triple(self) -> None:
        self.assertEqual(driver_run.spread(bytes([1, 2])), bytes([1, 0, 0, 2, 0, 0]))

    def test_and_nothing_at_all_stays_nothing(self) -> None:
        self.assertEqual(driver_run.spread(b""), b"")


@NEEDS_A_DUMP
class ImageTest(unittest.TestCase):
    def test_the_driver_image_is_the_block_the_processor_is_handed(self) -> None:
        image = driver_run.image_of(bytearray(USA.read_bytes()))

        self.assertEqual(len(image), driver_run.IMAGE_BYTES)

    def test_and_it_starts_where_the_receive_loop_was_disassembled_from(self) -> None:
        rom = bytearray(USA.read_bytes())
        patched = spcfast.apply(rom)
        image = driver_run.image_of(patched)
        at = spcfast.DRIVER_BASE + spcfast.RECEIVE_LOOP

        self.assertEqual(image[spcfast.RECEIVE_LOOP], patched[at])

    def test_the_two_tools_agree_on_where_the_driver_lives(self) -> None:
        self.assertEqual(driver_run.DRIVER_BASE, spcfast.DRIVER_BASE)


@NEEDS_A_DUMP
class TransferTest(unittest.TestCase):
    """The patched receive loop, run rather than read."""

    def deliver(self, payload: bytes | bytearray, rom: Path = USA) -> Any:
        image = driver_run.image_of(spcfast.apply(bytearray(rom.read_bytes())))
        return driver_run.deliver(image, payload, driver_run.DESTINATION)

    def test_a_transfer_carries_three_streams_side_by_side(self) -> None:
        found = self.deliver(PAYLOAD)

        self.assertEqual(found.streams[0], PAYLOAD[0::3])
        self.assertEqual(found.streams[1], PAYLOAD[1::3])
        self.assertEqual(found.streams[2], PAYLOAD[2::3])

    def test_the_first_stream_lands_where_the_driver_was_pointed(self) -> None:
        found = self.deliver(bytes([0xAB, 0x00, 0x00]))

        self.assertEqual(found.memory.read8(driver_run.DESTINATION), 0xAB)

    def test_and_the_other_two_land_where_their_own_pointers_say(self) -> None:
        found = self.deliver(bytes([0x00, 0xCD, 0xEF]))

        self.assertEqual(found.memory.read8(driver_run.SECOND), 0xCD)
        self.assertEqual(found.memory.read8(driver_run.THIRD), 0xEF)

    def test_a_transfer_takes_one_handshake_for_every_three_bytes(self) -> None:
        found = self.deliver(PAYLOAD)

        self.assertEqual(found.handshakes, len(PAYLOAD) // 3)

    def test_the_driver_echoes_the_counter_it_was_given(self) -> None:
        found = self.deliver(bytes(range(9)))

        self.assertEqual(found.memory.echoed[0], found.handshakes - 1)

    def test_a_transfer_longer_than_a_page_carries_the_pointer_over(self) -> None:
        payload = bytes(range(256)) * 3

        found = self.deliver(payload)

        self.assertEqual(found.streams[0], payload[0::3])

    def test_the_japanese_build_receives_the_same_way(self) -> None:
        found = self.deliver(PAYLOAD, rom=JP)

        self.assertEqual(found.streams[0], PAYLOAD[0::3])

    def test_a_transfer_stops_when_its_payload_does(self) -> None:
        found = self.deliver(bytes(range(6)))

        self.assertEqual(found.handshakes, 2)

    def test_and_leaves_the_byte_after_it_alone(self) -> None:
        found = self.deliver(bytes([0xFF] * 3))

        self.assertNotEqual(found.memory.read8(driver_run.DESTINATION + 1), 0xFF)


@NEEDS_A_DUMP
class StockTest(unittest.TestCase):
    """The driver before the patch, which is the thing the patch is faster than."""

    def stock(self, payload: bytes | bytearray, rom: Path = USA) -> Any:
        image = driver_run.image_of(bytearray(rom.read_bytes()))
        return driver_run.deliver_one_at_a_time(image, payload, driver_run.DESTINATION)

    def test_the_stock_driver_takes_a_handshake_for_every_byte(self) -> None:
        found = self.stock(PAYLOAD)

        self.assertEqual(found.handshakes, len(PAYLOAD))

    def test_and_carries_one_stream_rather_than_three(self) -> None:
        found = self.stock(bytes(range(9)))

        self.assertEqual(found.streams[0][:3], bytes([0, 1, 2]))

    def test_the_patch_is_three_times_fewer_handshakes_for_the_same_bytes(self) -> None:
        stock = self.stock(PAYLOAD)
        fast = driver_run.deliver(
            driver_run.image_of(spcfast.apply(bytearray(USA.read_bytes()))),
            PAYLOAD,
            driver_run.DESTINATION,
        )

        self.assertEqual(stock.handshakes, fast.handshakes * 3)

    def test_and_fewer_instructions_than_that_because_it_reads_each_port_once(self) -> None:
        stock = self.stock(PAYLOAD)
        fast = driver_run.deliver(
            driver_run.image_of(spcfast.apply(bytearray(USA.read_bytes()))),
            PAYLOAD,
            driver_run.DESTINATION,
        )

        self.assertGreater(stock.steps, fast.steps * 3)


@NEEDS_A_DUMP
@NEEDS_THE_BOOT_ROM
class ComposedTest(unittest.TestCase):
    """The same driver on the whole audio unit, which is a second witness.

    Agreeing with the stand-in is the point of these. The stand-in was written to
    a reading of the driver, so it can only ever confirm that reading is
    self-consistent. The unit was not written for this project at all.
    """

    def images(self) -> tuple[bytes, bytes]:
        rom = bytearray(USA.read_bytes())
        return driver_run.image_of(rom), driver_run.image_of(spcfast.apply(bytearray(rom)))

    def unit(self, payload: bytes | bytearray = PAYLOAD) -> Any:
        _stock, fast = self.images()
        return driver_run.on_hardware(fast, payload, driver_run.DESTINATION)

    def test_the_unit_carries_the_three_streams_the_stand_in_carries(self) -> None:
        found = self.unit()

        self.assertEqual(found.streams, (PAYLOAD[0::3], PAYLOAD[1::3], PAYLOAD[2::3]))

    def test_it_reaches_the_same_bytes_as_the_stand_in(self) -> None:
        _stock, fast = self.images()

        found = driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION)

        self.assertEqual(
            found.streams, driver_run.deliver(fast, PAYLOAD, driver_run.DESTINATION).streams
        )

    def test_and_takes_the_same_number_of_handshakes_getting_there(self) -> None:
        _stock, fast = self.images()

        found = driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION)

        self.assertEqual(
            found.handshakes, driver_run.deliver(fast, PAYLOAD, driver_run.DESTINATION).handshakes
        )

    def test_and_the_same_number_of_instructions(self) -> None:
        _stock, fast = self.images()

        found = driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION)

        self.assertEqual(
            found.steps, driver_run.deliver(fast, PAYLOAD, driver_run.DESTINATION).steps
        )

    def test_only_the_unit_reports_cycles_at_all(self) -> None:
        _stock, fast = self.images()

        self.assertIsNone(driver_run.deliver(fast, PAYLOAD, driver_run.DESTINATION).cycles)
        self.assertGreater(self.unit().cycles, 0)

    def test_the_stock_loop_runs_on_the_unit_too(self) -> None:
        stock, _fast = self.images()

        found = driver_run.on_hardware(
            stock, driver_run.spread(PAYLOAD), driver_run.DESTINATION, entry=driver_run.STOCK_LOOP
        )

        self.assertEqual(found.handshakes, len(PAYLOAD))

    def test_and_costs_more_cycles_than_the_patched_one_for_the_same_bytes(self) -> None:
        stock, _fast = self.images()

        slow = driver_run.on_hardware(
            stock, driver_run.spread(PAYLOAD), driver_run.DESTINATION, entry=driver_run.STOCK_LOOP
        )

        self.assertGreater(slow.cycles, self.unit().cycles * 3)

    def test_a_counter_that_does_not_start_where_the_driver_expects_runs_away(self) -> None:
        _stock, fast = self.images()

        with self.assertRaises(driver_run.RunLimit):
            driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION, counter=1)

    def test_without_the_seeded_latch_the_first_acknowledgement_is_lost(self) -> None:
        _stock, fast = self.images()

        with self.assertRaises(driver_run.RunLimit):
            driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION, unechoed=0x00)

    def test_leaving_the_boot_window_on_changes_nothing_for_this_driver(self) -> None:
        _stock, fast = self.images()

        found = driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION, control=0x80)

        self.assertEqual((found.streams, found.cycles), (self.unit().streams, self.unit().cycles))

    def test_because_the_driver_never_reads_what_the_window_covers(self) -> None:
        _stock, fast = self.images()

        shown = driver_run.on_hardware(fast, PAYLOAD, driver_run.DESTINATION, control=0x80)

        self.assertEqual(shown.handshakes, len(PAYLOAD) // 3)

    def test_a_payload_longer_than_a_page_carries_over_on_the_unit_too(self) -> None:
        payload = bytes(range(256)) * 3

        found = self.unit(payload)

        self.assertEqual(found.streams[0], payload[0::3])


@NEEDS_THE_BOOT_ROM
class ConsoleTest(unittest.TestCase):
    def build(self, payload: bytes | bytearray) -> tuple[Any, Any]:
        chip = driver_run.ssmp.Chip("s-smp")
        chip.reset()
        chip.space.write8(driver_run.PORT_BASE, driver_run.UNECHOED)
        console = driver_run.Console(chip, payload)
        console.offer()
        return chip, console

    def test_the_first_triple_is_where_the_driver_will_look_for_it(self) -> None:
        chip, _console = self.build(bytes(range(6)))

        self.assertEqual([chip.space.read8(at) for at in range(0xF5, 0xF8)], [0, 1, 2])

    def test_the_counter_starts_where_the_driver_expects_it(self) -> None:
        chip, _console = self.build(bytes(range(6)))

        self.assertEqual(chip.space.read8(0xF4), driver_run.FIRST_COUNTER)

    def test_an_acknowledgement_advances_to_the_next_triple(self) -> None:
        chip, console = self.build(bytes(range(6)))

        chip.space.write8(0xF4, 0x00)
        console.watch()

        self.assertEqual([chip.space.read8(at) for at in range(0xF5, 0xF8)], [3, 4, 5])

    def test_a_latch_that_has_not_changed_is_not_an_acknowledgement(self) -> None:
        _chip, console = self.build(bytes(range(6)))

        self.assertFalse(console.watch())
        self.assertEqual(console.handshakes, 0)

    def test_a_payload_shorter_than_a_triple_is_padded_rather_than_read_past(self) -> None:
        chip, _console = self.build(bytes([9]))

        self.assertEqual([chip.space.read8(at) for at in range(0xF5, 0xF8)], [9, 0, 0])

    def test_a_payload_that_runs_out_says_so(self) -> None:
        chip, console = self.build(bytes(3))

        chip.space.write8(0xF4, 0x00)
        console.watch()

        self.assertTrue(console.spent)

    def test_the_counter_wraps_at_a_byte(self) -> None:
        chip, console = self.build(bytes(3 * 300))
        for step in range(300):
            chip.space.write8(0xF4, step & 0xFF)
            console.watch()

        self.assertEqual(chip.space.read8(0xF4), 300 & 0xFF)

    def test_the_driver_cannot_read_its_own_acknowledgement(self) -> None:
        chip, _console = self.build(bytes(range(6)))

        chip.space.write8(0xF4, 0x9E)

        self.assertEqual(chip.space.read8(0xF4), driver_run.FIRST_COUNTER)


class EntryTest(unittest.TestCase):
    @NEEDS_A_DUMP
    @NEEDS_THE_BOOT_ROM
    def test_a_run_from_the_command_line_reports_what_it_measured(self) -> None:
        self.assertEqual(driver_run.main([str(USA)]), 0)

    def test_a_rom_it_cannot_read_is_reported_rather_than_raised(self) -> None:
        self.assertEqual(driver_run.main([str(ROOT / "roms" / "nothing-here.sfc")]), 2)

    def test_and_so_is_a_missing_argument(self) -> None:
        self.assertEqual(driver_run.main([]), 2)


if __name__ == "__main__":
    unittest.main()
