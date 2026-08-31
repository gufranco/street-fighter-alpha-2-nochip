import importlib.util
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tour = load_module("tour_audio", ROOT / "tools")


def log(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


class ParseTest(unittest.TestCase):
    def test_a_run_with_no_output_reports_nothing_loaded(self) -> None:
        found, summary = tour.parse("", roster=2, budget=100)

        self.assertEqual(summary["load"], "?")
        self.assertEqual(summary["frames"], 0)
        self.assertEqual(len(found), 2)

    def test_ticks_land_in_the_slot_their_frame_belongs_to(self) -> None:
        text = log(
            [
                "TICK frame=0 main=01 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                "TICK frame=60 main=02 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
                "TICK frame=120 main=03 nmi=30 ready=00 busy=00 mode=00 port0=00 spc=0400",
            ]
        )

        found, _ = tour.parse(text, roster=2, budget=100)

        self.assertEqual(found[0]["ticks"], 2)
        self.assertEqual(found[1]["ticks"], 1)

    def test_a_frame_past_the_last_slot_stays_in_the_last_slot(self) -> None:
        text = log(["TICK frame=9999 main=01 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400"])

        found, _ = tour.parse(text, roster=2, budget=100)

        self.assertEqual(found[1]["ticks"], 1)

    def test_a_slot_whose_main_counter_never_moves_is_stalled(self) -> None:
        text = log(
            [
                "TICK frame=0 main=16 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                "TICK frame=60 main=16 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
            ]
        )

        found, _ = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(tour.stalled(found), [0])

    def test_a_slot_whose_counters_both_move_is_not_stalled(self) -> None:
        text = log(
            [
                "TICK frame=0 main=16 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                "TICK frame=60 main=17 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
            ]
        )

        found, _ = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(tour.stalled(found), [])

    def test_a_slot_whose_interrupt_stops_is_stalled(self) -> None:
        text = log(
            [
                "TICK frame=0 main=16 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                "TICK frame=60 main=17 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
            ]
        )

        found, _ = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(tour.stalled(found), [0])

    def test_a_slot_with_no_ticks_at_all_is_stalled(self) -> None:
        found, _ = tour.parse("", roster=1, budget=1000)

        self.assertEqual(tour.stalled(found), [0])

    def test_bad_blocks_are_collected_with_their_source(self) -> None:
        text = log(["BLKBAD src=CB:3C2C dest=5517 len=4266 bad=12 first=3"])

        found, _ = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(found[0]["bad"], ["CB:3C2C"])

    def test_the_block_totals_are_read_from_the_closing_line(self) -> None:
        text = log(["BLOCKS ok=153 bad=0"])

        _, summary = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(summary["ok"], 153)
        self.assertEqual(summary["bad"], 0)

    def test_the_result_line_gives_the_load_state_and_frame_count(self) -> None:
        text = log(["RESULT load=ok frames=216000 size=256x224 lit=48896 rows=191 banks=64"])

        _, summary = tour.parse(text, roster=1, budget=1000)

        self.assertEqual(summary["load"], "ok")
        self.assertEqual(summary["frames"], 216000)

    def test_a_character_marker_names_the_fighter_a_slot_ran(self) -> None:
        text = log(["TOUR character=7 frame=84000"])

        found, _ = tour.parse(text, roster=18, budget=12000)

        self.assertEqual(found[7]["fighter"], 7)


class VerdictTest(unittest.TestCase):
    def test_a_clean_run_passes(self) -> None:
        found, summary = tour.parse(
            log(
                [
                    "TICK frame=0 main=01 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "TICK frame=60 main=02 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "BLOCKS ok=73 bad=0",
                    "RESULT load=ok frames=1000 size=256x224 lit=1 rows=1 banks=64",
                ]
            ),
            roster=1,
            budget=1000,
        )

        self.assertTrue(tour.passed(found, summary, roster=1, budget=1000))

    def test_a_bad_block_fails_the_run(self) -> None:
        found, summary = tour.parse(
            log(
                [
                    "TICK frame=0 main=01 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "TICK frame=60 main=02 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "BLOCKS ok=72 bad=1",
                    "RESULT load=ok frames=1000 size=256x224 lit=1 rows=1 banks=64",
                ]
            ),
            roster=1,
            budget=1000,
        )

        self.assertFalse(tour.passed(found, summary, roster=1, budget=1000))

    def test_a_short_run_fails_the_run(self) -> None:
        found, summary = tour.parse(
            log(
                [
                    "TICK frame=0 main=01 nmi=10 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "TICK frame=60 main=02 nmi=20 ready=00 busy=00 mode=00 port0=00 spc=0400",
                    "BLOCKS ok=73 bad=0",
                    "RESULT load=ok frames=900 size=256x224 lit=1 rows=1 banks=64",
                ]
            ),
            roster=1,
            budget=1000,
        )

        self.assertFalse(tour.passed(found, summary, roster=1, budget=1000))


class ShellOutTest(unittest.TestCase):
    """The one step that reaches for a container, with the reaching passed in."""

    def test_it_asks_for_as_many_frames_as_the_roster_and_budget_need(self) -> None:
        asked: list[Any] = []

        tour.run(
            tour.ROOT / "build" / "all" / "probe.sfc",
            "-2",
            3,
            100,
            execute=lambda command, **_rest: asked.append(command),
        )

        self.assertIn("300", asked[0])

    def test_it_returns_whatever_the_pass_wrote(self) -> None:
        line = "RESULT load=ok frames=300\n"

        def _write(_command: Any, stdout: Any = None, **_rest: Any) -> Any:
            stdout.write(line.encode())
            return None

        found = tour.run(tour.ROOT / "build" / "all" / "probe.sfc", "-2", 3, 100, execute=_write)

        self.assertEqual(found, line)


class ReportTest(unittest.TestCase):
    """One block about one image."""

    @staticmethod
    def moving(fighter: int) -> dict[str, Any]:
        return {"fighter": fighter, "main": {"a", "b"}, "nmi": {"c", "d"}, "bad": [], "ticks": 9}

    def test_a_fighter_whose_state_moved_is_reported_as_ok(self) -> None:
        said: list[str] = []

        tour.report(
            "probe", [self.moving(0)], {"load": "ok", "frames": 1, "ok": 1, "bad": 0}, said.append
        )

        self.assertIn("ok", said[1])

    def test_a_fighter_whose_state_never_moved_is_reported_as_stalled(self) -> None:
        said: list[str] = []
        stuck = {"fighter": 0, "main": {"a"}, "nmi": {"c"}, "bad": [], "ticks": 9}

        tour.report("probe", [stuck], {"load": "ok", "frames": 1, "ok": 1, "bad": 0}, said.append)

        self.assertIn("STALLED", said[1])

    def test_the_totals_close_the_block(self) -> None:
        said: list[str] = []

        tour.report("probe", [], {"load": "ok", "frames": 7, "ok": 1, "bad": 0}, said.append)

        self.assertIn("frames=7", said[-1])


class CommandTest(unittest.TestCase):
    """The verdict over a set of images, driven against recorded logs."""

    @staticmethod
    def healthy(roster: int, budget: int) -> str:
        lines = []
        for fighter in range(roster):
            lines.append(f"TOUR fighter={fighter} frame={fighter * budget}")
            for step in range(2):
                frame = fighter * budget + step
                lines.append(
                    f"TICK frame={frame} main={step:02x} nmi={step + 16:02x} "
                    "ready=00 busy=00 mode=00 port0=00 spc=0400"
                )
        lines.append("BLOCKS ok=10 bad=0")
        lines.append(f"RESULT load=ok frames={roster * budget}")
        return log(lines)

    def run_with(self, text: str, stems: list[str], argv: list[str]) -> tuple[int, list[str]]:
        said: list[str] = []
        code = tour.main(
            argv,
            images=[tour.IMAGES / f"{stem}.sfc" for stem in stems],
            tour=lambda *_a: text,
            say=said.append,
        )
        return code, said

    def test_an_image_where_every_fighter_moved_passes(self) -> None:
        code, said = self.run_with(
            self.healthy(2, 100), ["jp-both-cart"], ["tour_audio.py", "both-cart", "2", "100"]
        )

        self.assertEqual((code, "0 failing" in said[-1]), (0, True))

    def test_an_image_where_nothing_moved_fails(self) -> None:
        code, said = self.run_with(
            "RESULT load=ok frames=200\n",
            ["jp-both-cart"],
            ["tour_audio.py", "both-cart", "2", "100"],
        )

        self.assertEqual((code, "FAIL jp-both-cart" in "\n".join(said)), (1, True))

    def test_a_bypass_image_is_never_toured(self) -> None:
        code, said = self.run_with(
            self.healthy(2, 100), ["jp-both-bypass"], ["tour_audio.py", "both", "2", "100"]
        )

        self.assertEqual((code, "0 failing" in said[-1]), (0, True))

    def test_an_image_whose_name_does_not_match_is_skipped(self) -> None:
        _, said = self.run_with(
            self.healthy(2, 100), ["usa-base-free"], ["tour_audio.py", "both-cart", "2", "100"]
        )

        self.assertEqual(said[-1], "  0 failing")

    def recorder(self, seen: list[str], text: str) -> Callable[..., str]:
        def _tour(_image: Any, mapping: str, *_rest: Any) -> str:
            seen.append(mapping)
            return text

        return _tour

    def test_a_free_image_is_read_through_the_windowed_map(self) -> None:
        seen: list[str] = []

        tour.main(
            ["tour_audio.py", "both-free", "2", "100"],
            images=[tour.IMAGES / "jp-both-free.sfc"],
            tour=self.recorder(seen, self.healthy(2, 100)),
            say=lambda _l: None,
        )

        self.assertEqual(seen, ["-2"])

    def test_a_cartridge_image_is_read_through_the_cartridge_map(self) -> None:
        seen: list[str] = []

        tour.main(
            ["tour_audio.py", "both-cart", "2", "100"],
            images=[tour.IMAGES / "jp-both-cart.sfc"],
            tour=self.recorder(seen, self.healthy(2, 100)),
            say=lambda _l: None,
        )

        self.assertEqual(seen, ["-1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
