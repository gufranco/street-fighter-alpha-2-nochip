"""That the tile measurement measures something, and knows when it does not.

The trap this exists to avoid is a check that passes on anything. Reading a
decompressed stream back as tiles and writing it out again reproduces the input
for any run of bytes whose length divides by thirty two, because the planar
layout is a rearrangement and nothing else. A round trip is therefore not
evidence that the output is graphics, and treating it as such would be a check
nobody has seen fail.

What separates art from noise is reuse. A real sheet repeats tiles, because blank
space and flat colour repeat, and random bytes never do. So the measurement is
the duplicate fraction, and the control is random bytes of the same length. The
control has to come out at zero or the measurement is not measuring reuse.
"""

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


tile_shape = load_module("tile_shape", Path(__file__).resolve().parent / "tile_shape.py")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"

NEEDS_A_DUMP = unittest.skipUnless(
    USA.exists(), "the retail dump is not on this machine, and nothing here ships one"
)


class TilesTest(unittest.TestCase):
    def test_a_run_that_is_a_whole_number_of_tiles_is_cut_into_them(self) -> None:
        found = tile_shape.tiles(bytes(64))

        self.assertEqual(len(found), 2)

    def test_a_run_that_is_not_is_refused_rather_than_padded(self) -> None:
        self.assertIsNone(tile_shape.tiles(bytes(40)))

    def test_and_nothing_at_all_is_refused_too(self) -> None:
        self.assertIsNone(tile_shape.tiles(b""))

    def test_the_model_decides_what_a_tile_is_rather_than_this_file(self) -> None:
        found = tile_shape.tiles(bytes(tile_shape.TILE_BYTES))

        self.assertEqual(len(found), 1)

    def test_and_the_size_named_here_agrees_with_what_the_model_cuts(self) -> None:
        found = tile_shape.tiles(bytes(tile_shape.TILE_BYTES * 5))

        self.assertEqual(len(found), 5)


class ReuseTest(unittest.TestCase):
    def test_a_sheet_of_identical_tiles_is_all_reuse_but_one(self) -> None:
        found = tile_shape.reuse(bytes(32 * 4))

        self.assertEqual(found, 0.75)

    def test_a_sheet_with_no_tile_twice_reuses_nothing(self) -> None:
        sheet = b"".join(bytes([n]) * 32 for n in range(4))

        self.assertEqual(tile_shape.reuse(sheet), 0.0)

    def test_a_run_that_is_not_whole_tiles_has_no_reuse_to_report(self) -> None:
        self.assertIsNone(tile_shape.reuse(bytes(40)))


class ControlTest(unittest.TestCase):
    def test_random_bytes_repeat_no_tile_at_all(self) -> None:
        found = [tile_shape.reuse(tile_shape.noise(32 * 64)) for _ in range(8)]

        self.assertEqual(max(found), 0.0)

    def test_which_is_what_makes_a_nonzero_reading_mean_something(self) -> None:
        sheet = bytes(32) + bytes(32) + b"\x01" * 32

        self.assertGreater(tile_shape.reuse(sheet), tile_shape.reuse(tile_shape.noise(96)))


class SurveyTest(unittest.TestCase):
    def test_a_survey_of_nothing_reports_nothing_rather_than_dividing_by_zero(self) -> None:
        found = tile_shape.survey([])

        self.assertEqual((found.aligned, found.meanReuse), (0, 0.0))

    def test_an_aligned_run_is_counted_as_aligned(self) -> None:
        found = tile_shape.survey([bytes(32 * 3)])

        self.assertEqual((found.aligned, found.unaligned), (1, 0))

    def test_and_one_that_is_not_is_counted_apart(self) -> None:
        found = tile_shape.survey([bytes(40)])

        self.assertEqual((found.aligned, found.unaligned), (0, 1))

    def test_the_control_is_measured_beside_every_real_run(self) -> None:
        found = tile_shape.survey([bytes(32 * 3)])

        self.assertEqual(found.meanReuseOfNoise, 0.0)

    def test_a_survey_of_real_sheets_reuses_more_than_its_own_control(self) -> None:
        found = tile_shape.survey([bytes(32 * 8)] * 4)

        self.assertGreater(found.meanReuse, found.meanReuseOfNoise)

    def test_how_many_sheets_repeated_anything_is_reported(self) -> None:
        found = tile_shape.survey([bytes(32 * 2), b"".join(bytes([n]) * 32 for n in range(2))])

        self.assertEqual((found.withAnyRepeat, found.noiseWithAnyRepeat), (1, 0))


@NEEDS_A_DUMP
class AgainstTheCartridgeTest(unittest.TestCase):
    def measured(self) -> Any:
        return tile_shape.against(USA, limit=200)

    def test_most_streams_are_a_whole_number_of_tiles(self) -> None:
        found = self.measured()

        self.assertGreater(found.aligned, found.unaligned)

    def test_the_decompressed_output_repeats_tiles(self) -> None:
        self.assertGreater(self.measured().meanReuse, 0.05)

    def test_and_random_bytes_of_the_same_lengths_repeat_none(self) -> None:
        self.assertEqual(self.measured().meanReuseOfNoise, 0.0)

    def test_which_is_the_whole_claim(self) -> None:
        found = self.measured()

        self.assertGreater(found.withAnyRepeat, found.noiseWithAnyRepeat)


class EntryTest(unittest.TestCase):
    @NEEDS_A_DUMP
    def test_a_run_from_the_command_line_reports_what_it_measured(self) -> None:
        self.assertEqual(tile_shape.main([str(USA), "60"]), 0)

    def test_a_rom_it_cannot_read_is_reported_rather_than_raised(self) -> None:
        self.assertEqual(tile_shape.main([str(ROOT / "roms" / "nothing-here.sfc")]), 2)

    def test_and_so_is_a_missing_argument(self) -> None:
        self.assertEqual(tile_shape.main([]), 2)


if __name__ == "__main__":
    unittest.main()
