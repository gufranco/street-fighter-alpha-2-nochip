import importlib.util
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hardware  # noqa: E402

mapper = hardware.load("mapper")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_image = load_module("verify_image", ROOT / "tools" / "verify_image.py")

BANKS = 192
"""The image the builder produces, and the smallest one that reaches the table.

The lookup table sits in bank `$60`, which the windowed layout places past the
eighth megabyte of the file. An image small enough to be convenient for a test
cannot hold it, so the fixture is the size the real one is.
"""


def _image(banks: int = BANKS) -> bytearray:
    return bytearray(banks * mapper.BANK)


def _write(image: bytearray, banks: int, bank: int, address: int, value: int) -> None:
    image[mapper.address_to_file(bank, address, banks)] = value


def _entry(image: bytearray, banks: int, slot: int, source: int, destination: int) -> None:
    _write(image, banks, verify_image.TABLE_BANK, slot, verify_image.WINDOW_BASE + (source >> 16))
    _write(image, banks, verify_image.TABLE_BANK + 1, slot, destination & 0xFF)
    _write(image, banks, verify_image.TABLE_BANK + 2, slot, (destination >> 8) & 0xFF)
    _write(image, banks, verify_image.TABLE_BANK + 3, slot, (destination >> 16) & 0xFF)


class WindowReadTest(unittest.TestCase):
    def test_a_byte_comes_back_from_where_it_was_written(self) -> None:
        image = _image()
        _write(image, BANKS, 0x60, 0x1234, 0xAB)

        self.assertEqual(verify_image.window_read(image, BANKS, 0x60, 0x1234), 0xAB)

    def test_two_addresses_in_different_banks_do_not_collide(self) -> None:
        image = _image()
        _write(image, BANKS, 0x60, 0x1234, 0xAB)
        _write(image, BANKS, 0x61, 0x1234, 0xCD)

        self.assertEqual(verify_image.window_read(image, BANKS, 0x60, 0x1234), 0xAB)
        self.assertEqual(verify_image.window_read(image, BANKS, 0x61, 0x1234), 0xCD)

    def test_the_two_halves_of_a_bank_are_different_places(self) -> None:
        image = _image()
        _write(image, BANKS, 0x60, 0x0000, 0x11)
        _write(image, BANKS, 0x60, 0x8000, 0x22)

        self.assertEqual(verify_image.window_read(image, BANKS, 0x60, 0x0000), 0x11)
        self.assertEqual(verify_image.window_read(image, BANKS, 0x60, 0x8000), 0x22)


class ResolveTest(unittest.TestCase):
    def test_an_entry_at_the_exact_slot_is_found_without_scanning(self) -> None:
        image = _image()
        _entry(image, BANKS, 0x104C, 0x19104C, 0x0C4000)

        destination, step = verify_image.resolve(image, BANKS, 0x19104C)

        self.assertEqual(destination, 0x0C4000)
        self.assertEqual(step, 0)

    def test_an_entry_a_few_slots_along_is_found_and_the_distance_reported(self) -> None:
        image = _image()
        _entry(image, BANKS, 0x104C + 3, 0x19104C, 0x0C4000)

        destination, step = verify_image.resolve(image, BANKS, 0x19104C)

        self.assertEqual(destination, 0x0C4000)
        self.assertEqual(step, 3)

    def test_an_entry_past_the_budget_is_not_found(self) -> None:
        image = _image()
        _entry(image, BANKS, 0x104C + verify_image.SCAN_BUDGET + 1, 0x19104C, 0x0C4000)

        self.assertEqual(verify_image.resolve(image, BANKS, 0x19104C), (None, None))

    def test_an_empty_table_resolves_nothing(self) -> None:
        self.assertEqual(verify_image.resolve(_image(), BANKS, 0x19104C), (None, None))

    def test_an_entry_for_another_source_bank_is_not_this_one(self) -> None:
        image = _image()
        _entry(image, BANKS, 0x104C, 0x18104C, 0x0C4000)

        self.assertEqual(verify_image.resolve(image, BANKS, 0x19104C), (None, None))

    def test_a_lookup_near_the_top_of_a_bank_wraps_rather_than_reading_the_next(self) -> None:
        image = _image()
        _entry(image, BANKS, 0x0001, 0x19FFFF, 0x0C4000)

        destination, step = verify_image.resolve(image, BANKS, 0x19FFFF)

        self.assertEqual(destination, 0x0C4000)
        self.assertEqual(step, 2)


class NamingTest(unittest.TestCase):
    def test_an_image_built_with_the_corrections_says_so_in_its_name(self) -> None:
        self.assertTrue(verify_image.carries_game_fixes("build/all/jp-both-free.sfc"))

    def test_one_built_without_them_does_not(self) -> None:
        self.assertFalse(verify_image.carries_game_fixes("build/all/jp-sa-free.sfc"))

    def test_the_check_ignores_case(self) -> None:
        self.assertTrue(verify_image.carries_game_fixes("BUILD/ALL/JP-BOTH-FREE.SFC"))

    def test_a_japanese_image_resolves_to_the_japanese_table(self) -> None:
        streams, retail = verify_image.region_of("jp-both-free.sfc")

        self.assertEqual(streams, verify_image.jpstreams.STREAMS)
        self.assertIn("sfz2", retail.name)

    def test_a_usa_image_resolves_to_the_usa_table(self) -> None:
        streams, retail = verify_image.region_of("usa-both-free.sfc")

        self.assertEqual(streams, verify_image.usastreams.STREAMS)
        self.assertIn("sfa2", retail.name)

    def test_a_retail_name_is_enough_to_tell_the_region(self) -> None:
        self.assertEqual(
            verify_image.region_of("sfz2-jp-final.sfc")[0], verify_image.jpstreams.STREAMS
        )
        self.assertEqual(
            verify_image.region_of("sfa2-usa-final.sfc")[0], verify_image.usastreams.STREAMS
        )

    def test_a_name_belonging_to_no_region_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ValueError):
            verify_image.region_of("something-else.sfc")


class CommandTest(unittest.TestCase):
    """The two failures the check reports, driven without an assembled image."""

    RETAIL = bytes(0x400000)

    def run_with(self, image: bytearray, streams: list[tuple[int, int]]) -> tuple[int, list[str]]:
        said: list[str] = []

        def _read(where: Any) -> Any:
            return image if "jp-" in Path(where).name else self.RETAIL

        code = verify_image.main(
            ["verify_image.py", "jp-base-free.sfc"],
            read=_read,
            streams=streams,
            say=said.append,
        )
        return code, said

    def placed(self, source: int, length: int, at: int = 0x0C4000) -> bytearray:
        image = _image()
        _entry(image, BANKS, source & 0xFFFF, source, at)
        want = verify_image.sdd1.decompress(self.RETAIL, source, length).data
        for offset, value in enumerate(want):
            _write(image, BANKS, (at + offset) >> 16, (at + offset) & 0xFFFF, value)
        return image

    def test_a_stream_that_is_where_the_table_says_passes(self) -> None:
        code, said = self.run_with(self.placed(0x19104C, 16), [(0x19104C, 16)])

        self.assertEqual((code, "wrong: 0" in "\n".join(said)), (0, True))

    def test_a_lookup_that_resolves_nowhere_fails(self) -> None:
        code, said = self.run_with(_image(), [(0x19104C, 16)])

        self.assertEqual((code, "unresolved lookups: 1" in "\n".join(said)), (1, True))

    def test_an_unresolved_lookup_is_named(self) -> None:
        _, said = self.run_with(_image(), [(0x19104C, 16)])

        self.assertIn("0x19104c", "\n".join(said))

    def test_bytes_that_do_not_match_fail(self) -> None:
        image = self.placed(0x19104C, 16)
        _write(image, BANKS, 0x0C, 0x4003, 0xFF)

        code, said = self.run_with(image, [(0x19104C, 16)])

        self.assertEqual((code, "first bad byte 3" in "\n".join(said)), (1, True))

    def test_only_the_first_ten_unresolved_lookups_are_listed(self) -> None:
        many = [(0x190000 + n * 0x100, 16) for n in range(15)]

        _, said = self.run_with(_image(), many)

        self.assertEqual(len([one for one in said if one.startswith("     0x")]), 10)

    @staticmethod
    def recorder(applied: list[Any]) -> Callable[[Any], Any]:
        def _apply(rom: Any) -> Any:
            applied.append(rom)
            return rom

        return _apply

    def test_an_image_naming_the_game_fixes_has_them_applied_first(self) -> None:
        applied: list[Any] = []

        verify_image.main(
            ["verify_image.py", "jp-both-free.sfc"],
            read=lambda where: _image() if "jp-both" in Path(where).name else self.RETAIL,
            streams=[],
            say=lambda _l: None,
            fixes=self.recorder(applied),
        )

        self.assertEqual(len(applied), 1)

    def test_an_image_that_does_not_name_them_leaves_the_cartridge_alone(self) -> None:
        applied: list[Any] = []

        verify_image.main(
            ["verify_image.py", "jp-base-free.sfc"],
            read=lambda where: _image() if "jp-base" in Path(where).name else self.RETAIL,
            streams=[],
            say=lambda _l: None,
            fixes=self.recorder(applied),
        )

        self.assertEqual(applied, [])

    def test_an_image_belonging_to_neither_region_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            verify_image.main(["verify_image.py", "mystery.sfc"], say=lambda _l: None)


if __name__ == "__main__":
    unittest.main()
