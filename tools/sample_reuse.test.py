import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sample_reuse = load_module("sample_reuse", ROOT / "tools")


def parse(*lines: str) -> list[Any]:
    return list(sample_reuse.loads(sample_reuse.events(list(lines))))


LOAD = "GROUP frame={frame} pc=C70074 group=03 ids=00,00,00 alloc=1500 key=00"
WALK = "GROUP frame={frame} pc=C70103 group=03 ids={ids} alloc={alloc} key=02"
ENDS = "GROUP frame={frame} pc=C7018F group=0{group} ids={ids} alloc={alloc} key=04"
BLOCK = "HDR pc=C70472 src={src} len={length} dest={dest}"


class SegmentTest(unittest.TestCase):
    def test_each_load_start_opens_a_new_segment(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            LOAD.format(frame=9),
            BLOCK.format(src="D1:B000", length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
        )

        self.assertEqual([run["frame"] for run in runs], [1, 9])
        self.assertEqual(len(runs[0]["blocks"]), 1)

    def test_a_block_after_the_last_mark_is_not_part_of_the_load(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            WALK.format(frame=1, ids="05,00,00", alloc="1500"),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
        )

        self.assertEqual(runs[0]["blocks"], [])

    def test_blocks_before_the_first_load_start_are_dropped(self) -> None:
        runs = parse(BLOCK.format(src="D1:A000", length=9, dest="1500"))

        self.assertEqual(runs, [])

    def test_the_request_comes_from_the_walk_start_mark(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            WALK.format(frame=1, ids="25,45,00", alloc="1600"),
        )

        self.assertEqual(sample_reuse.request(runs[0]), (0x25, 0x45, 0))

    def test_a_load_with_no_walk_start_has_no_request(self) -> None:
        runs = parse(LOAD.format(frame=1))

        self.assertIsNone(sample_reuse.request(runs[0]))


class SpanTest(unittest.TestCase):
    def walk(self) -> list[Any]:
        return parse(
            LOAD.format(frame=1),
            WALK.format(frame=1, ids="05,06,00", alloc="1600"),
            ENDS.format(frame=1, group=0, ids="05,06,00", alloc="1800"),
            ENDS.format(frame=1, group=1, ids="05,06,00", alloc="1900"),
        )

    def test_the_base_list_span_reaches_the_walk_start(self) -> None:
        self.assertEqual(sample_reuse.spans(self.walk()[0])[0], ("base", 0x100))

    def test_each_group_span_reaches_its_own_end_mark(self) -> None:
        self.assertEqual(sample_reuse.spans(self.walk()[0])[1:], [(0, 0x200), (1, 0x100)])

    def test_a_span_that_wraps_backwards_is_discarded(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            WALK.format(frame=1, ids="05,00,00", alloc="1500"),
            ENDS.format(frame=1, group=0, ids="05,00,00", alloc="0500"),
        )

        self.assertEqual(sample_reuse.spans(runs[0])[1], (0, 0))

    def test_group_costs_add_every_span_of_the_same_name(self) -> None:
        costs = sample_reuse.group_costs(self.walk() + self.walk())

        self.assertEqual(costs["base"]["walks"], 2)
        self.assertEqual(costs[0]["bytes"], 0x400)


class ResidencyTest(unittest.TestCase):
    def test_the_first_upload_of_a_block_is_never_resident(self) -> None:
        totals, _ = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            )
        )

        self.assertEqual(totals["bytes"], 9)
        self.assertEqual(totals["resident_bytes"], 0)

    def test_the_same_bytes_sent_again_to_the_same_place_are_resident(self) -> None:
        totals, _ = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1509"),
                LOAD.format(frame=9),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=9, ids="05,00,00", alloc="1509"),
            )
        )

        self.assertEqual(totals["bytes"], 18)
        self.assertEqual(totals["resident_bytes"], 9)

    def test_the_same_bytes_sent_to_a_different_place_are_not_resident(self) -> None:
        totals, _ = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1509"),
                LOAD.format(frame=9),
                BLOCK.format(src="D1:A000", length=9, dest="1600"),
                WALK.format(frame=9, ids="05,00,00", alloc="1609"),
            )
        )

        self.assertEqual(totals["resident_bytes"], 0)

    def test_an_overwrite_makes_a_later_repeat_not_resident(self) -> None:
        totals, _ = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1509"),
                LOAD.format(frame=9),
                BLOCK.format(src="D1:B000", length=9, dest="1500"),
                WALK.format(frame=9, ids="05,00,00", alloc="1509"),
                LOAD.format(frame=20),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=20, ids="05,00,00", alloc="1509"),
            )
        )

        self.assertEqual(totals["bytes"], 27)
        self.assertEqual(totals["resident_bytes"], 0)

    def test_an_absurd_block_length_is_ignored(self) -> None:
        totals, _ = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=40000, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1500"),
            )
        )

        self.assertEqual(totals["bytes"], 0)

    def test_every_load_reports_its_own_totals(self) -> None:
        _, per_load = sample_reuse.replay(
            parse(
                LOAD.format(frame=1),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=1, ids="05,00,00", alloc="1509"),
                LOAD.format(frame=9),
                BLOCK.format(src="D1:A000", length=9, dest="1500"),
                WALK.format(frame=9, ids="05,00,00", alloc="1509"),
            )
        )

        self.assertEqual([entry["bytes"] for entry in per_load], [9, 9])
        self.assertEqual([entry["resident"] for entry in per_load], [0, 9])


class BaseRepeatTest(unittest.TestCase):
    def two_loads(self, second_source: str) -> list[Any]:
        return parse(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=2, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=9),
            BLOCK.format(src=second_source, length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=10, group=0, ids="05,00,00", alloc="1512"),
        )

    def test_the_first_base_list_is_never_a_repeat(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
        )
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["loads"], 1)
        self.assertEqual(found["repeats"], 0)

    def test_the_same_base_list_twice_running_is_a_repeat(self) -> None:
        runs = self.two_loads("D1:A000")
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["loads"], 2)
        self.assertEqual(found["repeats"], 1)
        self.assertEqual(found["bytes"], 9)

    def test_a_different_base_list_is_not_a_repeat(self) -> None:
        runs = self.two_loads("D1:B000")
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["repeats"], 0)
        self.assertEqual(found["bytes"], 0)

    def test_a_repeat_agrees_with_residency(self) -> None:
        runs = self.two_loads("D1:A000")
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["resident"], 1)
        self.assertEqual(found["resident_not_repeat"], 0)
        self.assertEqual(found["repeat_not_resident"], 0)

    def test_a_base_list_overwritten_between_the_two_is_resident_no_longer(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=2, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=5),
            BLOCK.format(src="D1:C000", length=9, dest="1500"),
            WALK.format(frame=5, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=6, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=9),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=10, group=0, ids="05,00,00", alloc="1512"),
        )
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["repeats"], 0)
        self.assertEqual(found["resident"], 0)

    def test_a_load_that_moved_no_base_bytes_is_not_counted(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=2, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=9),
            WALK.format(frame=9, ids="05,00,00", alloc="1500"),
            ENDS.format(frame=10, group=0, ids="05,00,00", alloc="1509"),
        )
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["loads"], 1)


class ListIdTest(unittest.TestCase):
    def test_a_mark_without_a_list_id_still_parses(self) -> None:
        runs = parse(
            LOAD.format(frame=1),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
        )

        self.assertIsNone(runs[0]["marks"][0]["list"])

    def test_a_mark_with_a_list_id_carries_it(self) -> None:
        runs = parse(
            LOAD.format(frame=1) + " list=2C",
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
        )

        self.assertEqual(runs[0]["marks"][0]["list"], 0x2C)

    def test_two_repeats_are_split_by_whether_the_list_id_matched(self) -> None:
        runs = parse(
            LOAD.format(frame=1) + " list=2C",
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=2, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=9) + " list=2C",
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=10, group=0, ids="05,00,00", alloc="1512"),
            LOAD.format(frame=17) + " list=31",
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=17, ids="05,00,00", alloc="1509"),
            ENDS.format(frame=18, group=0, ids="05,00,00", alloc="1512"),
        )
        sample_reuse.replay(runs)

        found = sample_reuse.base_repeats(runs)

        self.assertEqual(found["repeats"], 2)
        self.assertEqual(found["repeats_same_id"], 1)


class TimingTest(unittest.TestCase):
    def test_a_byte_costs_the_measured_driver_time(self) -> None:
        self.assertAlmostEqual(sample_reuse.seconds(1024000), 16.3, places=6)

    def test_no_bytes_cost_no_time(self) -> None:
        self.assertEqual(sample_reuse.seconds(0), 0)


class ReportTest(unittest.TestCase):
    """What one log says about how much of each load was already resident."""

    @staticmethod
    def log(*lines: str) -> str:
        return "\n".join(lines) + "\n"

    def run_on(self, text: str) -> tuple[dict[str, Any], list[str]]:
        said: list[str] = []
        return sample_reuse.report("probe", text, said.append), said

    def test_a_log_with_no_loads_reports_none(self) -> None:
        _, said = self.run_on("nothing here\n")

        self.assertIn("engine loads 0", said[1])

    def test_a_load_that_moved_bytes_is_counted(self) -> None:
        text = self.log(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
        )

        totals, said = self.run_on(text)

        self.assertEqual((totals["loads"], "1 moved bytes" in said[1]), (1, True))

    def test_the_same_load_twice_is_reported_as_already_resident(self) -> None:
        text = self.log(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
            LOAD.format(frame=9),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
        )

        totals, said = self.run_on(text)

        self.assertEqual((totals["loads"], "already resident" in "\n".join(said)), (2, True))

    def test_the_report_names_the_log_it_read(self) -> None:
        _, said = self.run_on("nothing here\n")

        self.assertEqual(said[0], "  probe")

    def test_every_group_it_saw_gets_a_line(self) -> None:
        text = self.log(
            LOAD.format(frame=1),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=1, ids="05,00,00", alloc="1509"),
        )

        _, said = self.run_on(text)

        self.assertTrue(any("walks" in one for one in said))


class CommandTest(unittest.TestCase):
    """The command line, driven against a log written for the occasion."""

    def test_a_named_log_is_reported_on(self) -> None:
        where = Path(tempfile.mkdtemp()) / "grp-probe.txt"
        where.write_text("nothing here\n")
        said: list[str] = []

        code = sample_reuse.main(["sample_reuse.py", str(where)], say=said.append)

        self.assertEqual((code, said[0]), (0, "  grp-probe"))

    def test_two_named_logs_are_both_reported_on(self) -> None:
        folder = Path(tempfile.mkdtemp())
        said: list[str] = []
        for stem in ("grp-a", "grp-b"):
            (folder / f"{stem}.txt").write_text("nothing here\n")

        sample_reuse.main(
            ["sample_reuse.py", str(folder / "grp-a.txt"), str(folder / "grp-b.txt")],
            say=said.append,
        )

        self.assertEqual([one for one in said if one.startswith("  grp-")], ["  grp-a", "  grp-b"])

    def test_no_log_named_falls_back_to_the_soundwalk_directory(self) -> None:
        said: list[str] = []

        code = sample_reuse.main(["sample_reuse.py"], say=said.append)

        self.assertEqual(code, 0)


class WalkBeforeLoadTest(unittest.TestCase):
    """A mark that arrives before any load has started."""

    def test_a_walk_with_no_load_open_is_ignored(self) -> None:
        runs = parse(WALK.format(frame=1, ids="05,00,00", alloc="1500"))

        self.assertEqual(runs, [])

    def test_and_a_later_load_still_opens_normally(self) -> None:
        runs = parse(
            WALK.format(frame=1, ids="05,00,00", alloc="1500"),
            LOAD.format(frame=9),
            BLOCK.format(src="D1:A000", length=9, dest="1500"),
            WALK.format(frame=9, ids="05,00,00", alloc="1509"),
        )

        self.assertEqual([run["frame"] for run in runs], [9])


class BaseSpanTest(unittest.TestCase):
    """The one span each load walks before anything else."""

    def test_a_load_with_no_base_span_has_none(self) -> None:
        self.assertIsNone(sample_reuse.base_span({"spans": []}))

    def test_a_span_by_another_name_is_not_the_base(self) -> None:
        self.assertIsNone(sample_reuse.base_span({"spans": [{"name": "extra"}]}))

    def test_the_base_span_is_returned_when_it_is_there(self) -> None:
        span = {"name": "base", "bytes": 9}

        self.assertIs(sample_reuse.base_span({"spans": [span]}), span)


class ReplayCountTest(unittest.TestCase):
    """The four ways a load relates to the one before it.

    The runs come from the parser rather than being written by hand, so they
    carry every field the replay reads.
    """

    @staticmethod
    def load(frame: int, ids: str, src: str, dest: str = "1500") -> list[str]:
        return [
            LOAD.format(frame=frame),
            BLOCK.format(src=src, length=9, dest=dest),
            WALK.format(frame=frame, ids=ids, alloc=f"{int(dest, 16) + 9:04x}"),
        ]

    def replay(self, *loads: list[str]) -> dict[str, Any]:
        lines: list[str] = []
        for one in loads:
            lines.extend(one)
        runs = parse(*lines)
        sample_reuse.replay(runs)
        found: dict[str, Any] = sample_reuse.base_repeats(runs)
        return found

    def test_the_first_load_of_a_run_is_neither_resident_nor_a_repeat(self) -> None:
        totals = self.replay(self.load(1, "05,00,00", "D1:A000"))

        self.assertEqual((totals["repeats"], totals["resident_not_repeat"]), (0, 0))

    def test_the_same_load_again_is_a_repeat_and_resident(self) -> None:
        totals = self.replay(
            self.load(1, "05,00,00", "D1:A000"), self.load(9, "05,00,00", "D1:A000")
        )

        self.assertEqual((totals["repeats"], totals["repeat_not_resident"]), (1, 0))

    def test_a_load_returned_to_after_another_one_is_resident_without_being_a_repeat(
        self,
    ) -> None:
        totals = self.replay(
            self.load(1, "05,00,00", "D1:A000", "1500"),
            self.load(9, "06,00,00", "D1:B000", "2000"),
            self.load(17, "05,00,00", "D1:A000", "1500"),
        )

        self.assertEqual(totals["resident_not_repeat"], 1)

    @staticmethod
    def overwrite(frame: int, src: str, dest: str) -> list[str]:
        return [
            LOAD.format(frame=frame),
            WALK.format(frame=frame, ids="05,00,00", alloc="1500"),
            BLOCK.format(src=src, length=9, dest=dest),
            WALK.format(frame=frame, ids="06,00,00", alloc=f"{int(dest, 16) + 9:04x}"),
        ]

    def test_a_load_whose_bytes_were_overwritten_is_a_repeat_that_is_not_resident(self) -> None:
        totals = self.replay(
            self.load(1, "05,00,00", "D1:A000", "1500"),
            self.overwrite(9, "D1:C000", "1500"),
            self.load(17, "05,00,00", "D1:A000", "1500"),
        )

        self.assertEqual(totals["repeat_not_resident"], 1)

    def test_a_load_that_moved_nothing_is_not_counted_at_all(self) -> None:
        totals = self.replay([LOAD.format(frame=1)])

        self.assertEqual(totals["loads"], 0)


if __name__ == "__main__":
    unittest.main()
