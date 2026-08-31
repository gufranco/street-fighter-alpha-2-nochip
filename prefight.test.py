import importlib.util
import unittest
from pathlib import Path
from typing import Any

import hardware

wdc65816 = hardware.load("mos65xx")

ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prefight = load_module("prefight")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"
JP = ROOT / "roms" / "sfz2-jp-final.sfc"


def retail(path):
    if not path.exists():
        raise unittest.SkipTest(f"{path} is not present")
    return path.read_bytes()


class TableTest(unittest.TestCase):
    def test_the_table_is_the_size_the_builder_writes(self) -> None:
        self.assertEqual(len(prefight.table()), prefight.TABLE_SIZE)

    def test_the_table_is_the_same_every_time_it_is_built(self) -> None:
        self.assertEqual(prefight.table(), prefight.table())

    def test_the_first_entry_is_the_high_word_of_the_starting_value(self) -> None:
        self.assertEqual(prefight.table()[:2], bytes([0x4B, 0x00]))

    def test_every_entry_is_a_word(self) -> None:
        self.assertEqual(prefight.TABLE_SIZE % 2, 0)

    def test_the_table_fits_inside_one_bank_half(self) -> None:
        self.assertLess(prefight.TABLE_SIZE, 0x8000)


class RoutineTest(unittest.TestCase):
    def test_the_routine_ends_in_a_long_return(self) -> None:
        self.assertEqual(prefight.routine()[-1], 0x6B)

    def test_the_routine_starts_by_saving_the_flags(self) -> None:
        self.assertEqual(prefight.routine()[0], 0x08)

    def test_every_hardware_store_is_long_addressed(self) -> None:
        emitted = prefight.routine()
        listing = [
            ins
            for ins in wdc65816.disassemble(emitted, 0, prefight.ROUTINE_ADDRESS, m=True, x=True)
            if ins.address - prefight.ROUTINE_ADDRESS < len(emitted)
        ]
        stores = [ins for ins in listing if ins.mnemonic == "sta"]

        self.assertEqual(len(stores), 8)
        for store in stores:
            self.assertEqual(emitted[store.address - prefight.ROUTINE_ADDRESS], 0x8F)

    def test_the_routine_names_the_table_address_it_reads(self) -> None:
        emitted = prefight.routine()

        self.assertIn(bytes([prefight.TABLE_ADDRESS >> 16]), emitted)

    def test_the_routine_matches_what_the_assembler_emits(self) -> None:
        assembled = ROOT / "asm" / "prefight-out.sfc"
        if not assembled.exists():
            raise unittest.SkipTest("assemble asm/prefight-table.asm first")

        produced = assembled.read_bytes()

        self.assertEqual(
            produced[prefight.FILLER_FILE : prefight.FILLER_FILE + len(prefight.ROUTINE)],
            prefight.ROUTINE,
        )

    def test_the_routine_fits_the_filler_it_is_written_into(self) -> None:
        self.assertLess(len(prefight.routine()), prefight.FILLER_SIZE)


class LocationTest(unittest.TestCase):
    def test_the_builder_is_found_once_in_each_region(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            self.assertIsNotNone(prefight.find_builder(rom), str(path))

    def test_both_callers_are_found_in_each_region(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            self.assertEqual(len(prefight.find_callers(rom)), 2, str(path))

    def test_a_rom_without_the_builder_reports_nothing(self) -> None:
        self.assertIsNone(prefight.find_builder(b"\x00" * 0x1000))

    def test_the_filler_is_free_in_each_region(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            window = rom[prefight.FILLER_FILE : prefight.FILLER_FILE + prefight.FILLER_SIZE]
            self.assertEqual(set(window), {0xFF}, str(path))


class ApplyTest(unittest.TestCase):
    def test_every_caller_is_redirected_to_the_routine(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            patched = prefight.apply(rom)

            for at in prefight.find_callers(rom):
                self.assertEqual(patched[at], 0x22, str(path))
                target = int.from_bytes(patched[at + 1 : at + 4], "little")
                self.assertEqual(target, prefight.ROUTINE_ADDRESS, str(path))

    def test_the_routine_lands_in_the_filler(self) -> None:
        rom = retail(USA)

        patched = prefight.apply(rom)

        emitted = prefight.routine()
        self.assertEqual(
            patched[prefight.FILLER_FILE : prefight.FILLER_FILE + len(emitted)], emitted
        )

    def test_applying_twice_changes_nothing_the_second_time(self) -> None:
        rom = retail(USA)

        once = prefight.apply(rom)

        self.assertEqual(prefight.apply(once), once)

    def test_the_builder_itself_is_left_in_place(self) -> None:
        rom = retail(USA)
        at = prefight.find_builder(rom)

        patched = prefight.apply(rom)

        self.assertEqual(patched[at : at + 32], rom[at : at + 32])

    def test_a_rom_without_the_builder_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            prefight.apply(b"\x00" * 0x1000)

    def test_nothing_outside_the_callers_and_the_filler_moves(self) -> None:
        rom = retail(USA)

        patched = prefight.apply(rom)

        allowed = set()
        for at in prefight.find_callers(rom):
            allowed.update(range(at, at + 4))
        allowed.update(range(prefight.FILLER_FILE, prefight.FILLER_FILE + len(prefight.routine())))
        moved = {at for at, (a, b) in enumerate(zip(rom, patched, strict=True)) if a != b}
        self.assertTrue(moved <= allowed, sorted(moved - allowed)[:8])


if __name__ == "__main__":
    unittest.main()
