import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repeatload = load_module("repeatload")
spcfast = load_module("spcfast")

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


class RoutineTest(unittest.TestCase):
    def test_the_routine_ends_in_a_return(self) -> None:
        self.assertEqual(repeatload.ROUTINE[-1], 0x60)

    def test_the_routine_restores_the_instruction_it_replaced(self) -> None:
        self.assertEqual(repeatload.ROUTINE[-4:-1], bytes([0xA9, 0x00, 0x15]))

    def test_every_marker_access_is_long_addressed(self) -> None:
        loads = repeatload.ROUTINE.count(0xAF)
        stores = repeatload.ROUTINE.count(0x8F)

        self.assertEqual(loads, 3)
        self.assertEqual(stores, 3)

    def test_the_routine_fits_the_filler_it_is_written_into(self) -> None:
        self.assertLess(len(repeatload.ROUTINE), repeatload.FILLER_SIZE)

    def test_the_hook_is_a_call_to_the_routine(self) -> None:
        self.assertEqual(repeatload.hook(), bytes([0x20, repeatload.ROUTINE_ADDRESS & 0xFF, 0xF6]))

    def test_the_hook_is_the_same_length_as_what_it_replaces(self) -> None:
        self.assertEqual(len(repeatload.hook()), len(repeatload.REPLACED))

    def test_the_routine_matches_what_the_assembler_emits(self) -> None:
        """What this package emits against what the assembler emits.

        The comparison needs a build that neither a plain checkout nor a runner
        has, so on both it skips and the body below never runs.
        """
        assembled = ROOT / "asm" / "repeat-out.sfc"
        if not assembled.exists():
            raise unittest.SkipTest("assemble asm/repeat-load.asm first")

        produced = assembled.read_bytes()  # pragma: no cover

        self.assertEqual(  # pragma: no cover
            produced[repeatload.FILLER_FILE : repeatload.FILLER_FILE + len(repeatload.ROUTINE)],
            repeatload.ROUTINE,
        )


class SiteTest(unittest.TestCase):
    def test_the_hook_site_carries_the_expected_instruction_in_both_regions(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            self.assertEqual(
                rom[repeatload.HOOK_FILE : repeatload.HOOK_FILE + len(repeatload.REPLACED)],
                repeatload.REPLACED,
                str(path),
            )

    def test_the_filler_is_free_in_both_regions(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            window = rom[repeatload.FILLER_FILE : repeatload.FILLER_FILE + repeatload.FILLER_SIZE]
            self.assertEqual(set(window), {0xFF}, str(path))

    def test_the_marker_sits_inside_the_run_no_write_was_seen_in(self) -> None:
        """The measured free run, not a range that looked free.

        Two forty five thousand frame tours, one per region, walking the whole
        roster and entering fights, wrote no byte anywhere in this range. The
        marker sits inside it with room on both sides. The address it used before
        was one byte below a run that really is free, and the game writes that
        byte on every play.
        """
        first, last = 0x7E5E70, 0x7EFE3F

        self.assertGreaterEqual(repeatload.MARKER, first)
        self.assertLessEqual(repeatload.MARKER + 3, last)

    def test_the_marker_is_not_in_the_page_the_game_keeps_variables_in(self) -> None:
        self.assertGreater(repeatload.MARKER & 0xFFFF, 0x2000)

    def test_every_address_the_routine_touches_is_the_marker(self) -> None:
        touched = set()
        for at in range(len(repeatload.ROUTINE) - 3):
            if repeatload.ROUTINE[at] in (0xAF, 0x8F):
                operand = repeatload.ROUTINE[at + 1 : at + 4]
                touched.add(int.from_bytes(operand, "little"))

        self.assertEqual(touched, {repeatload.MARKER, repeatload.MARKER + 1, repeatload.MARKER + 2})


class ApplyTest(unittest.TestCase):
    def test_applying_installs_the_hook_and_the_routine(self) -> None:
        for path in (USA, JP):
            rom = retail(path)

            patched = repeatload.apply(rom)

            self.assertEqual(
                patched[repeatload.HOOK_FILE : repeatload.HOOK_FILE + 3],
                repeatload.hook(),
                str(path),
            )
            self.assertEqual(
                patched[repeatload.FILLER_FILE : repeatload.FILLER_FILE + len(repeatload.ROUTINE)],
                repeatload.ROUTINE,
                str(path),
            )

    def test_applying_twice_changes_nothing_the_second_time(self) -> None:
        rom = retail(USA)

        once = repeatload.apply(rom)

        self.assertEqual(repeatload.apply(once), once)

    def test_a_rom_without_the_site_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            repeatload.apply(b"\x00" * 0x100000)

    def test_nothing_outside_the_hook_and_the_routine_moves(self) -> None:
        rom = retail(USA)

        patched = repeatload.apply(rom)

        allowed = set(range(repeatload.HOOK_FILE, repeatload.HOOK_FILE + 3))
        allowed.update(
            range(repeatload.FILLER_FILE, repeatload.FILLER_FILE + len(repeatload.ROUTINE))
        )
        allowed.update(range(spcfast.CHECKSUM_FIELD, spcfast.CHECKSUM_FIELD + 4))
        moved = {at for at, (a, b) in enumerate(zip(rom, patched, strict=True)) if a != b}
        self.assertTrue(moved <= allowed, sorted(moved - allowed)[:8])

    def test_it_does_not_collide_with_the_pre_fight_routine(self) -> None:
        prefight = load_module("prefight")

        first = range(prefight.FILLER_FILE, prefight.FILLER_FILE + len(prefight.ROUTINE))
        second = range(repeatload.FILLER_FILE, repeatload.FILLER_FILE + len(repeatload.ROUTINE))

        self.assertFalse(set(first) & set(second))


class RefusalTest(unittest.TestCase):
    """An image the patch does not recognise is refused rather than patched anyway."""

    def test_an_image_whose_filler_is_not_free_is_refused(self) -> None:
        rom = bytearray(repeatload.FILLER_END + 0x100)
        rom[repeatload.HOOK_FILE : repeatload.HOOK_FILE + len(repeatload.REPLACED)] = (
            repeatload.REPLACED
        )
        rom[repeatload.FILLER_FILE : repeatload.FILLER_END] = b"\xff" * (
            repeatload.FILLER_END - repeatload.FILLER_FILE
        )
        rom[repeatload.FILLER_FILE] = 0x00

        with self.assertRaises(ValueError) as raised:
            repeatload.apply(bytes(rom))

        self.assertIn("filler", str(raised.exception))

    def test_an_image_whose_allocator_setup_is_elsewhere_is_refused(self) -> None:
        rom = bytearray(repeatload.FILLER_END + 0x100)
        rom[repeatload.FILLER_FILE : repeatload.FILLER_END] = b"\xff" * (
            repeatload.FILLER_END - repeatload.FILLER_FILE
        )

        with self.assertRaises(ValueError) as raised:
            repeatload.apply(bytes(rom))

        self.assertIn("allocator setup", str(raised.exception))


class EntryTest(unittest.TestCase):
    """The command line, run with both streams collected rather than printed."""

    def _paths(self) -> tuple[Path, Path]:
        where = Path(tempfile.mkdtemp())
        source = where / "in.sfc"
        source.write_bytes(USA.read_bytes())
        return source, where / "out.sfc"

    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        complained: list[Any] = []

        code = repeatload.main(["repeatload.py"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_patching_the_source_in_place_is_refused(self) -> None:
        source, _ = self._paths()
        complained: list[Any] = []

        code = repeatload.main(
            ["repeatload.py", str(source), str(source)],
            say=lambda _l: None,
            complain=complained.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("in place", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_a_run_writes_the_patched_image_and_says_what_it_did(self) -> None:
        source, output = self._paths()
        said: list[Any] = []

        code = repeatload.main(["repeatload.py", str(source), str(output)], say=said.append)

        self.assertEqual(code, 0)
        self.assertTrue(output.exists())
        self.assertTrue(said)


if __name__ == "__main__":
    unittest.main()
