import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

spc700 = hardware.load("spc700")
dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spcfast = load_module("spcfast")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"
JP = ROOT / "roms" / "sfz2-jp-final.sfc"


class PatchShapeTest(unittest.TestCase):
    def test_the_patch_is_not_empty(self) -> None:
        self.assertGreater(len(spcfast.PATCH), 0)

    def test_the_runs_are_ordered_and_disjoint(self) -> None:
        end = -1
        for at, data in spcfast.PATCH:
            self.assertGreater(at, end)
            end = at + len(data) - 1

    def test_no_run_touches_the_checksum_field(self) -> None:
        for at, data in spcfast.PATCH:
            self.assertFalse(at <= spcfast.CHECKSUM_FIELD < at + len(data))

    def test_every_run_stays_inside_a_four_megabyte_rom(self) -> None:
        for at, data in spcfast.PATCH:
            self.assertLessEqual(at + len(data), 0x400000)

    def test_the_patch_reaches_the_sound_bank(self) -> None:
        self.assertIn(0x07, {at >> 16 for at, _ in spcfast.PATCH})

    def test_the_blank_gate_is_the_documented_sequence(self) -> None:
        self.assertEqual(spcfast.BLANK_GATE.hex(), "af12420029c0f0f8")


class DriverTest(unittest.TestCase):
    def run_covering(self, offset: int) -> tuple[int, bytes]:
        for at, data in spcfast.PATCH:
            if at <= offset < at + len(data):
                return at, data
        raise AssertionError(f"{offset:#08x} is not covered by the patch")

    def test_the_receive_loop_is_inside_the_patch(self) -> None:
        at, data = self.run_covering(spcfast.DRIVER_BASE + spcfast.RECEIVE_LOOP)

        self.assertLessEqual(at, spcfast.DRIVER_BASE + spcfast.RECEIVE_LOOP)
        self.assertGreater(len(data), 0)

    def test_the_block_header_parse_is_inside_the_patch(self) -> None:
        at, _ = self.run_covering(spcfast.DRIVER_BASE + spcfast.BLOCK_HEADER)

        self.assertLessEqual(at, spcfast.DRIVER_BASE + spcfast.BLOCK_HEADER)

    def test_the_processor_posts_the_three_byte_kind(self) -> None:
        at, data = self.run_covering(0x07046D)

        self.assertEqual(data[0x07046D - at], 0x03)


class ChecksumTest(unittest.TestCase):
    def test_the_stamped_field_is_a_complement_pair(self) -> None:
        stamped = spcfast.write_checksum(bytes(0x10000))
        complement = stamped[0x7FDC] | (stamped[0x7FDD] << 8)
        value = stamped[0x7FDE] | (stamped[0x7FDF] << 8)

        self.assertEqual(complement ^ value, 0xFFFF)

    def test_stamping_is_idempotent(self) -> None:
        once = spcfast.write_checksum(bytes(0x10000))

        self.assertEqual(spcfast.write_checksum(once), once)


class ApplyTest(unittest.TestCase):
    def make_rom(self) -> bytes:
        rom = bytearray(0x400000)
        for at, want in spcfast.STOCK_PROBE:
            rom[at : at + len(want)] = want
        return bytes(rom)

    def test_a_stock_rom_is_recognised(self) -> None:
        self.assertTrue(spcfast.is_stock(self.make_rom()))

    def test_every_run_is_written(self) -> None:
        patched = spcfast.apply(self.make_rom())

        for at, data in spcfast.PATCH:
            self.assertEqual(patched[at : at + len(data)], data)

    def test_the_result_reports_as_patched(self) -> None:
        self.assertTrue(spcfast.is_patched(spcfast.apply(self.make_rom())))

    def test_applying_twice_changes_nothing_further(self) -> None:
        once = spcfast.apply(self.make_rom())

        self.assertEqual(spcfast.apply(once), once)

    def test_the_source_rom_is_not_modified(self) -> None:
        rom = self.make_rom()

        spcfast.apply(rom)

        self.assertEqual(rom[0x07046D], 0x01)

    def test_a_rom_that_is_not_stock_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            spcfast.apply(bytes(0x400000))


@unittest.skipUnless(USA.exists() and JP.exists(), "the retail ROMs are not present")
class RetailRomTest(unittest.TestCase):
    jp: ClassVar[Any]
    usa: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.usa = dump.read(USA)
        cls.jp = dump.read(JP)

    def test_both_regions_are_recognised_as_stock(self) -> None:
        self.assertTrue(spcfast.is_stock(self.usa))
        self.assertTrue(spcfast.is_stock(self.jp))

    def test_every_patched_region_is_identical_across_regions(self) -> None:
        for at, data in spcfast.PATCH:
            self.assertEqual(
                self.usa[at : at + len(data)],
                self.jp[at : at + len(data)],
                f"regions differ at {at:#08x}",
            )

    def test_both_regions_have_seventeen_blank_gates(self) -> None:
        self.assertEqual(len(spcfast.find_blank_gates(self.usa)), 17)
        self.assertEqual(len(spcfast.find_blank_gates(self.jp)), 17)

    def test_patching_touches_only_the_patch_and_the_checksum(self) -> None:
        patched = spcfast.apply(self.usa)
        changed = {i for i in range(len(patched)) if patched[i] != self.usa[i]}
        allowed = set(range(spcfast.CHECKSUM_FIELD, spcfast.CHECKSUM_FIELD + 4))
        for at, data in spcfast.PATCH:
            allowed.update(range(at, at + len(data)))

        self.assertTrue(changed.issubset(allowed))

    def test_the_patched_block_start_waits_for_a_zero_counter(self) -> None:
        patched = spcfast.apply(self.usa)
        base = spcfast.DRIVER_BASE
        listing = [
            i.text
            for i in spc700.disassemble(
                patched[base : base + 0x10000],
                spcfast.RECEIVE_LOOP,
                spcfast.RECEIVE_LOOP,
                count=3,
            )
        ]

        self.assertEqual(listing, ["mov y,$0f4", "bne $0ebd", "mov a,$0e6"])

    def test_the_patched_dispatch_selects_on_the_kind_byte(self) -> None:
        patched = spcfast.apply(self.usa)
        base = spcfast.DRIVER_BASE
        listing = [
            i.text
            for i in spc700.disassemble(patched[base : base + 0x10000], 0x0EC1, 0x0EC1, count=3)
        ]

        self.assertEqual(listing[0], "mov a,$0e6")
        self.assertEqual(listing[1], "cmp a,#$03")
        self.assertTrue(listing[2].startswith("beq"))

    def test_the_driver_echoes_only_after_reading_every_port(self) -> None:
        patched = spcfast.apply(self.usa)
        base = spcfast.DRIVER_BASE
        listing = [
            i.text
            for i in spc700.disassemble(patched[base : base + 0x10000], 0x0EE4, 0x0EE4, count=6)
        ]

        self.assertEqual(listing[2], "mov x,$0f6")
        self.assertEqual(listing[3], "mov a,$0f7")
        self.assertEqual(listing[4], "mov $0f4,y")

    def test_the_receive_loop_stops_before_the_header_parse(self) -> None:
        patched = spcfast.apply(self.usa)
        base = spcfast.DRIVER_BASE
        end = 0x0EDC
        for instruction in spc700.disassemble(
            patched[base : base + 0x10000], 0x0EDC, 0x0EDC, count=14
        ):
            end = instruction.address + instruction.size

        self.assertLessEqual(end, spcfast.BLOCK_HEADER)

    def test_the_transfer_leaves_only_the_length_on_the_caller_stack(self) -> None:
        patched = spcfast.apply(self.usa)
        entry = 0x0704EB

        self.assertEqual(patched[entry : entry + 3].hex(), "c230da")

    def test_the_transfer_switches_to_its_own_stack_before_doing_anything(self) -> None:
        patched = spcfast.apply(self.usa)
        entry = 0x0704EB

        self.assertEqual(patched[entry + 3 : entry + 9].hex(), "3ba2e01f9a48")

    def test_the_stock_driver_tail_is_untouched(self) -> None:
        patched = spcfast.apply(self.usa)
        tail = spcfast.DRIVER_BASE + 0x0F28

        self.assertEqual(patched[tail : tail + 0x18], self.usa[tail : tail + 0x18])

    def test_the_checksum_is_restamped(self) -> None:
        patched = spcfast.apply(self.usa)

        self.assertEqual(patched[0x7FDE] | (patched[0x7FDF] << 8), spcfast.checksum(patched))


class LoadingTest(unittest.TestCase):
    def test_a_module_beside_this_one_is_loaded_by_path(self) -> None:
        self.assertTrue(hasattr(spcfast._load("sdd1tables"), "__name__"))


class FrameHookTest(unittest.TestCase):
    """The frame hook is dormant, and these say exactly how dormant.

    `FRAME_HOOK` is empty, so nothing is written at either site and `runs_for`
    hands back the patch unchanged. The finder is generated alongside it by
    tools/freeze_spcfast.py and waits for a hook to place, so what is pinned here
    is the dormancy itself rather than the behaviour of code that cannot run.
    """

    def test_no_hook_is_placed_while_there_is_no_hook_to_place(self) -> None:
        self.assertEqual(spcfast.FRAME_HOOK, b"")

    def test_so_the_runs_are_the_patch_and_nothing_else(self) -> None:
        self.assertEqual(spcfast.runs_for(bytes(0x400000)), spcfast.PATCH)

    def test_and_the_two_sites_it_would_look_at_are_still_named(self) -> None:
        self.assertEqual(len(spcfast.FRAME_HOOK_SITES), 2)


class EntryTest(unittest.TestCase):
    """The command line, run with both streams collected rather than printed."""

    def _paths(self) -> tuple[Path, Path]:
        where = Path(tempfile.mkdtemp())
        source = where / "in.sfc"
        source.write_bytes(USA.read_bytes())
        return source, where / "out.sfc"

    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        complained: list[Any] = []

        code = spcfast.main(["spcfast.py"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", complained[0])

    @unittest.skipUnless(USA.exists(), "the retail dump is supplied by the builder")
    def test_patching_the_source_in_place_is_refused(self) -> None:
        source, _ = self._paths()
        complained: list[Any] = []

        code = spcfast.main(
            ["spcfast.py", str(source), str(source)],
            say=lambda _l: None,
            complain=complained.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("in place", complained[0])

    @unittest.skipUnless(USA.exists(), "the retail dump is supplied by the builder")
    def test_a_run_writes_the_patched_image_and_says_what_it_did(self) -> None:
        source, output = self._paths()
        said: list[Any] = []

        code = spcfast.main(["spcfast.py", str(source), str(output)], say=said.append)

        self.assertEqual(code, 0)
        self.assertTrue(output.exists())
        self.assertTrue(said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
