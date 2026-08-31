import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare_audio = load_module("compare_audio", ROOT / "tools" / "compare_audio.py")

CLEAN = "\n".join(
    [
        "BLKEND src=C7:204E len=1000 writes=2000 expect=1500",
        "BLKEND src=D0:E94A len=300 writes=600 expect=450",
        "BLOCKS ok=2 bad=0",
        "RESULT load=ok frames=3000 size=256x224",
        "",
    ]
)

FASTER = "\n".join(
    [
        "BLKEND src=C7:204E len=1000 writes=1200 expect=1500",
        "BLKEND src=D0:E94A len=300 writes=360 expect=450",
        "BLOCKS ok=2 bad=0",
        "RESULT load=ok frames=3000 size=256x224",
        "",
    ]
)

CORRUPT = "\n".join(
    [
        "BLKEND src=C7:204E len=1000 writes=1200 expect=1500",
        "BLKBAD src=C7:204E dest=2000 len=1000 bad=7 first=512",
        "BLOCKS ok=0 bad=1",
        "RESULT load=ok frames=3000 size=256x224",
        "",
    ]
)

SKIPPED = "\n".join(
    [
        "BLKEND src=C7:204E len=1000 writes=1200 expect=1500",
        "BLOCKS ok=1 bad=0",
        "RESULT load=ok frames=3000 size=256x224",
        "",
    ]
)


def _log(folder, text, name="run.txt"):
    path = Path(folder) / name
    path.write_text(text)
    return path


class MappingTest(unittest.TestCase):
    def test_a_converted_image_is_read_through_the_windowed_map(self) -> None:
        self.assertEqual(compare_audio.mapping_for("jp-both-free"), compare_audio.FREE_MAPPING)

    def test_one_still_in_cartridge_form_is_not(self) -> None:
        self.assertEqual(compare_audio.mapping_for("jp-both-cart"), compare_audio.CART_MAPPING)


class ReadTest(unittest.TestCase):
    def test_every_uploaded_block_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertEqual(len(found["blocks"]), 2)

    def test_a_block_carries_its_source_as_a_whole_address(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertEqual(found["blocks"][0]["source"], 0xC7204E)

    def test_a_block_carries_what_it_cost_and_what_it_should_have(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertEqual(found["blocks"][0]["writes"], 2000)
            self.assertEqual(found["blocks"][0]["expect"], 1500)

    def test_the_totals_come_from_the_line_that_states_them(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertEqual((found["ok"], found["bad"]), (2, 0))

    def test_a_corrupt_block_is_recorded_with_where_it_went_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CORRUPT))

            self.assertEqual(found["corrupt"][0]["bad"], 7)
            self.assertEqual(found["corrupt"][0]["first"], 512)
            self.assertEqual(found["corrupt"][0]["destination"], 0x2000)

    def test_how_far_the_run_got_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertEqual((found["load"], found["frames"]), ("ok", 3000))

    def test_a_log_with_nothing_in_it_says_it_does_not_know(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, ""))

            self.assertEqual(found["load"], "?")
            self.assertEqual(found["blocks"], [])

    def test_bytes_it_cannot_decode_do_not_stop_the_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.txt"
            path.write_bytes(b"\xff\xfe\n" + CLEAN.encode())

            self.assertEqual(compare_audio.read(path)["ok"], 2)


class UploadTest(unittest.TestCase):
    def _read(self, folder, text, name):
        return compare_audio.read(_log(folder, text, name))

    def test_a_source_uploaded_twice_is_counted_twice(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = self._read(folder, CLEAN + CLEAN, "twice.txt")

            self.assertEqual(compare_audio.uploads(found)[(0xC7204E, 1000)], 2)

    def test_a_build_compared_with_itself_skipped_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")

            self.assertEqual(compare_audio.fewer(stock, stock), {})
            self.assertEqual(compare_audio.missing(stock, stock), [])

    def test_a_source_uploaded_less_often_is_reported_with_both_counts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN + CLEAN, "a.txt")
            patched = self._read(folder, CLEAN, "b.txt")

            self.assertEqual(compare_audio.fewer(stock, patched)[(0xC7204E, 1000)], (2, 1))

    def test_a_source_never_uploaded_at_all_is_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")
            patched = self._read(folder, SKIPPED, "b.txt")

            self.assertEqual(compare_audio.missing(stock, patched), [(0xD0E94A, 300)])


class CostTest(unittest.TestCase):
    def test_a_run_that_uploaded_nothing_costs_nothing(self) -> None:
        self.assertEqual(compare_audio.cost({"blocks": []}), 0.0)

    def test_the_cost_is_writes_over_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = compare_audio.read(_log(folder, CLEAN))

            self.assertAlmostEqual(compare_audio.cost(found), 2600 / 1300)

    def test_a_faster_loop_costs_less_per_byte(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = compare_audio.read(_log(folder, CLEAN, "a.txt"))
            patched = compare_audio.read(_log(folder, FASTER, "b.txt"))

            self.assertLess(compare_audio.cost(patched), compare_audio.cost(stock))


class VerdictTest(unittest.TestCase):
    def _read(self, folder, text, name):
        return compare_audio.read(_log(folder, text, name))

    def test_a_faster_build_that_delivered_everything_passes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")
            patched = self._read(folder, FASTER, "b.txt")

            self.assertEqual(compare_audio.verdict(stock, patched), [])

    def test_a_corrupt_block_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")
            patched = self._read(folder, CORRUPT, "b.txt")

            self.assertIn("a block did not arrive intact", compare_audio.verdict(stock, patched))

    def test_a_source_that_stopped_being_uploaded_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")
            patched = self._read(folder, SKIPPED, "b.txt")

            self.assertIn(
                "a source the stock build uploads was never uploaded",
                compare_audio.verdict(stock, patched),
            )

    def test_a_build_that_did_not_load_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stock = self._read(folder, CLEAN, "a.txt")
            patched = self._read(folder, "", "b.txt")

            self.assertIn("one of the builds did not load", compare_audio.verdict(stock, patched))


class ReportTest(unittest.TestCase):
    def _said(self, stock_text, patched_text):
        with tempfile.TemporaryDirectory() as folder:
            stock = compare_audio.read(_log(folder, stock_text, "a.txt"))
            patched = compare_audio.read(_log(folder, patched_text, "b.txt"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                compare_audio.report("stock.sfc", "patched.sfc", stock, patched)
            return buffer.getvalue()

    def test_both_builds_are_named_with_what_they_uploaded(self) -> None:
        said = self._said(CLEAN, FASTER)

        self.assertIn("stock.sfc", said)
        self.assertIn("patched.sfc", said)

    def test_a_corrupt_block_is_printed_with_the_byte_it_went_wrong_at(self) -> None:
        said = self._said(CLEAN, CORRUPT)

        self.assertIn("CORRUPT", said)
        self.assertIn("512", said)

    def test_a_source_that_stopped_being_uploaded_is_printed(self) -> None:
        self.assertIn("NEVER UPLOADED", self._said(CLEAN, SKIPPED))

    def test_the_speed_up_is_reported_as_a_ratio(self) -> None:
        self.assertIn("writes per byte went from", self._said(CLEAN, FASTER))

    def test_a_run_that_uploaded_nothing_does_not_report_a_ratio(self) -> None:
        self.assertNotIn("writes per byte went from", self._said("", ""))


class OptionTest(unittest.TestCase):
    def test_two_images_are_the_whole_requirement(self) -> None:
        found = compare_audio.options(["x", "a.sfc", "b.sfc"])

        self.assertEqual(found[:2], ("a.sfc", "b.sfc"))

    def test_the_default_tour_does_not_enter_fights(self) -> None:
        self.assertFalse(compare_audio.options(["x", "a.sfc", "b.sfc"])[4])

    def test_the_fight_flag_turns_them_on(self) -> None:
        self.assertTrue(compare_audio.options(["x", "--fights", "a.sfc", "b.sfc"])[4])

    def test_the_roster_and_the_budget_can_be_named(self) -> None:
        _, _, roster, budget, _ = compare_audio.options(
            ["x", "--roster", "2", "--budget", "500", "a.sfc", "b.sfc"]
        )

        self.assertEqual((roster, budget), (2, 500))

    def test_the_flag_can_come_after_the_images(self) -> None:
        self.assertTrue(compare_audio.options(["x", "a.sfc", "b.sfc", "--fights"])[4])

    def test_one_image_is_not_enough(self) -> None:
        with self.assertRaises(compare_audio.Usage):
            compare_audio.options(["x", "a.sfc"])

    def test_three_images_are_too_many(self) -> None:
        with self.assertRaises(compare_audio.Usage):
            compare_audio.options(["x", "a.sfc", "b.sfc", "c.sfc"])


class MainTest(unittest.TestCase):
    def test_it_refuses_a_call_with_the_wrong_number_of_arguments(self) -> None:
        self.assertEqual(compare_audio.main(["compare_audio.py"]), 2)

    def test_it_refuses_a_roster_that_is_not_a_number(self) -> None:
        self.assertEqual(
            compare_audio.main(["compare_audio.py", "--roster", "many", "a.sfc", "b.sfc"]), 2
        )

    def test_it_refuses_a_flag_with_nothing_after_it(self) -> None:
        self.assertEqual(compare_audio.main(["compare_audio.py", "a.sfc", "b.sfc", "--roster"]), 2)


if __name__ == "__main__":
    unittest.main()
