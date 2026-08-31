import importlib.util
import tempfile
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


def retail(path: Path) -> bytes:
    """The cartridge, or a skip when this machine does not have it.

    Both arms are decided by what is on disk, so no single run covers both: a
    machine with the dump never raises and a machine without it never reads.
    """
    if not path.exists():  # pragma: no cover
        raise unittest.SkipTest(f"{path} is not present")
    return path.read_bytes()  # pragma: no cover


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
        """What this package emits against what the assembler emits.

        The comparison needs a build that neither a plain checkout nor a runner
        has, so on both it skips and the body below never runs.
        """
        assembled = ROOT / "asm" / "prefight-out.sfc"
        if not assembled.exists():
            raise unittest.SkipTest("assemble asm/prefight-table.asm first")

        produced = assembled.read_bytes()  # pragma: no cover

        self.assertEqual(  # pragma: no cover
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

        allowed: set[int] = set()
        for at in prefight.find_callers(rom):
            allowed.update(range(at, at + 4))
        allowed.update(range(prefight.FILLER_FILE, prefight.FILLER_FILE + len(prefight.routine())))
        moved = {at for at, (a, b) in enumerate(zip(rom, patched, strict=True)) if a != b}
        self.assertTrue(moved <= allowed, sorted(moved - allowed)[:8])


def synthetic(builder: int = 0x030000, callers: tuple[int, ...] = (0x020000,)) -> bytearray:
    """A cartridge carrying only what the patch looks for.

    A real dump is not on every machine, and the patch's decisions do not depend
    on anything else in the cartridge, so a stand-in that carries the builder,
    its callers and free filler exercises every branch honestly.
    """
    rom = bytearray(0x400000)
    rom[builder : builder + len(prefight.BUILDER_SIGNATURE)] = prefight.BUILDER_SIGNATURE
    rom[prefight.FILLER_FILE : prefight.FILLER_END] = b"\xff" * prefight.FILLER_SIZE
    window = prefight.WINDOW_FIRST_BANK + (builder >> 16)
    call = prefight.call_to((window << 16) | (builder & 0xFFFF))
    for site in callers:
        rom[site : site + len(call)] = call
    return rom


class SyntheticLocationTest(unittest.TestCase):
    """Finding the builder and its callers, without a cartridge on the machine."""

    def test_a_cartridge_without_the_builder_has_none(self) -> None:
        self.assertIsNone(prefight.find_builder(bytes(0x400000)))

    def test_a_builder_appearing_twice_is_refused(self) -> None:
        rom = synthetic()
        rom[0x050000 : 0x050000 + len(prefight.BUILDER_SIGNATURE)] = prefight.BUILDER_SIGNATURE

        with self.assertRaises(ValueError):
            prefight.find_builder(rom)

    def test_the_builder_is_found_where_it_was_put(self) -> None:
        self.assertEqual(prefight.find_builder(synthetic()), 0x030000)

    def test_a_cartridge_without_the_builder_has_no_callers(self) -> None:
        self.assertEqual(prefight.find_callers(bytes(0x400000)), [])

    def test_every_caller_is_found(self) -> None:
        rom = synthetic(callers=(0x020000, 0x021000, 0x022000))

        self.assertEqual(prefight.find_callers(rom), [0x020000, 0x021000, 0x022000])


class SyntheticApplyTest(unittest.TestCase):
    """Applying the patch, and every reason it refuses to."""

    def test_a_cartridge_without_the_builder_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            prefight.apply(bytes(0x400000))

    def test_a_builder_nobody_calls_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            prefight.apply(synthetic(callers=()))

    def test_filler_that_is_not_free_is_refused(self) -> None:
        rom = synthetic()
        rom[prefight.FILLER_FILE] = 0x00

        with self.assertRaises(ValueError):
            prefight.apply(rom)

    def test_the_routine_lands_in_the_filler_of_a_stand_in(self) -> None:
        patched = prefight.apply(synthetic())

        emitted = prefight.routine()
        self.assertEqual(
            patched[prefight.FILLER_FILE : prefight.FILLER_FILE + len(emitted)], emitted
        )

    def test_the_caller_is_redirected(self) -> None:
        patched = prefight.apply(synthetic())

        self.assertEqual(
            patched[0x020000 : 0x020000 + 4], prefight.call_to(prefight.ROUTINE_ADDRESS)
        )

    def test_a_patched_cartridge_is_recognised_as_patched(self) -> None:
        self.assertTrue(prefight.is_patched(prefight.apply(synthetic())))

    def test_an_unpatched_cartridge_is_not(self) -> None:
        self.assertFalse(prefight.is_patched(synthetic()))

    def test_applying_twice_to_a_stand_in_changes_nothing(self) -> None:
        once = prefight.apply(synthetic())

        self.assertEqual(prefight.apply(once), once)


class ReportTest(unittest.TestCase):
    """What the patch says it found."""

    def test_a_cartridge_without_the_builder_is_said_to_have_none(self) -> None:
        said: list[str] = []

        prefight.report(bytes(0x400000), said.append)

        self.assertIn("no pre-fight table builder", said[0])

    def test_a_cartridge_with_one_has_it_named_with_its_bank(self) -> None:
        said: list[str] = []

        prefight.report(synthetic(), said.append)

        self.assertIn("$C3:0000", said[0])

    def test_every_caller_is_named(self) -> None:
        said: list[str] = []

        prefight.report(synthetic(callers=(0x020000, 0x021000)), said.append)

        self.assertEqual(len([one for one in said if "caller" in one]), 2)

    def test_the_table_it_will_build_is_named_with_its_size(self) -> None:
        said: list[str] = []

        prefight.report(synthetic(), said.append)

        self.assertIn(f"{prefight.TABLE_SIZE:,} bytes", said[-1])


class CommandTest(unittest.TestCase):
    """The command line, driven against a stand-in cartridge."""

    def test_the_wrong_number_of_arguments_prints_the_usage(self) -> None:
        said: list[str] = []

        code = prefight.main(["prefight.py"], say=said.append)

        self.assertEqual((code, "usage" in said[0]), (2, True))

    def test_patching_a_cartridge_over_itself_is_refused(self) -> None:
        where = Path(tempfile.mkdtemp()) / "rom.sfc"
        where.write_bytes(bytes(synthetic()))
        said: list[str] = []

        code = prefight.main(["prefight.py", str(where), str(where)], say=said.append)

        self.assertEqual((code, "in place" in said[0]), (1, True))

    def test_a_run_writes_the_patched_cartridge(self) -> None:
        where = Path(tempfile.mkdtemp())
        source, output = where / "in.sfc", where / "out.sfc"
        source.write_bytes(bytes(synthetic()))

        code = prefight.main(["prefight.py", str(source), str(output)], say=lambda _l: None)

        self.assertEqual((code, prefight.is_patched(output.read_bytes())), (0, True))

    def test_and_says_how_big_the_result_is(self) -> None:
        where = Path(tempfile.mkdtemp())
        source, output = where / "in.sfc", where / "out.sfc"
        source.write_bytes(bytes(synthetic()))
        said: list[str] = []

        prefight.main(["prefight.py", str(source), str(output)], say=said.append)

        self.assertIn("[done]", said[-1])


if __name__ == "__main__":
    unittest.main()
