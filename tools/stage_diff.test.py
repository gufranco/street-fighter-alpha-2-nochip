import importlib.util
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage_diff = load_module("stage_diff")


class HashesTest(unittest.TestCase):
    def write(self, text: str) -> Path:
        path = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "h.txt"
        path.write_text(text)
        return path

    def test_a_missing_file_reads_as_no_frames(self) -> None:
        self.assertEqual(stage_diff.hashes(ROOT / "no-such-file.txt"), {})

    def test_each_line_becomes_a_frame_and_its_hash(self) -> None:
        path = self.write("0 aaaa\n1 bbbb\n")

        self.assertEqual(stage_diff.hashes(path), {0: "aaaa", 1: "bbbb"})

    def test_a_short_line_is_skipped(self) -> None:
        path = self.write("0 aaaa\ngarbage\n2 cccc\n")

        self.assertEqual(stage_diff.hashes(path), {0: "aaaa", 2: "cccc"})


class CompareTest(unittest.TestCase):
    def test_identical_runs_report_nothing_differing(self) -> None:
        both = {0: "a", 1: "b"}

        shared, differing = stage_diff.compare(both, dict(both))

        self.assertEqual(shared, [0, 1])
        self.assertEqual(differing, [])

    def test_a_changed_frame_is_reported(self) -> None:
        _, differing = stage_diff.compare({0: "a", 1: "b"}, {0: "a", 1: "z"})

        self.assertEqual(differing, [1])

    def test_only_frames_present_in_both_are_compared(self) -> None:
        shared, differing = stage_diff.compare({0: "a", 1: "b"}, {0: "z"})

        self.assertEqual(shared, [0])
        self.assertEqual(differing, [0])

    def test_the_frames_are_reported_in_order(self) -> None:
        before = {5: "a", 1: "a", 3: "a"}
        after = {5: "z", 1: "z", 3: "z"}

        _, differing = stage_diff.compare(before, after)

        self.assertEqual(differing, [1, 3, 5])


class ShellOutTest(unittest.TestCase):
    """The one step that reaches for a container, with the reaching passed in."""

    def test_it_names_the_matchup_and_where_to_write_the_hashes(self) -> None:
        asked: list[Any] = []
        out = stage_diff.LOGS / "probe-hashes.txt"

        stage_diff.run(
            stage_diff.ROOT / "image.sfc",
            "00,05",
            out,
            execute=lambda command, **_rest: asked.append(command),
        )

        self.assertIn("SFSCENE=00,05", asked[0])

    def test_it_returns_the_log_it_was_asked_to_write(self) -> None:
        out = stage_diff.LOGS / "probe-hashes.txt"

        found = stage_diff.run(
            stage_diff.ROOT / "image.sfc", "00,05", out, execute=lambda *_a, **_k: None
        )

        self.assertEqual(found, out)


class CommandTest(unittest.TestCase):
    """The per-opponent report, driven against recorded logs."""

    def logs(self, before: dict[int, str], after: dict[int, str]) -> Callable[..., Path]:
        where = Path(tempfile.mkdtemp())

        def _play(image: Path, _matchup: str, out: Path) -> Path:
            rows = before if "before" in image.name else after
            written = where / out.name
            written.write_text("\n".join(f"{frame} {value}" for frame, value in rows.items()))
            return written

        return _play

    def run_with(self, before: dict[int, str], after: dict[int, str]) -> list[str]:
        said: list[str] = []
        stage_diff.main(
            ["stage_diff.py", "before.sfc", "after.sfc"],
            play=self.logs(before, after),
            say=said.append,
            roster=1,
        )
        return said

    def test_two_images_that_render_the_same_report_no_differing_frames(self) -> None:
        same = {1: "aa", 2: "bb"}

        said = self.run_with(same, same)

        self.assertIn("    0 of 2 frames differ", "\n".join(said))

    def test_a_differing_frame_is_counted_and_the_first_one_named(self) -> None:
        said = self.run_with({1: "aa", 2: "bb"}, {1: "aa", 2: "cc"})

        self.assertIn("first 2", "\n".join(said))

    def test_a_matchup_that_captured_nothing_says_so(self) -> None:
        said = self.run_with({}, {})

        self.assertIn("no frames captured", "\n".join(said))

    def test_a_difference_after_the_menu_counts_as_in_the_fight(self) -> None:
        frame = stage_diff.MENU + 1

        said = self.run_with({frame: "aa"}, {frame: "bb"})

        self.assertIn("in the fight 1", "\n".join(said))

    def test_a_difference_during_the_menu_does_not(self) -> None:
        said = self.run_with({1: "aa"}, {1: "bb"})

        self.assertIn("in the fight 0", "\n".join(said))

    def test_the_report_names_both_images(self) -> None:
        said = self.run_with({1: "aa"}, {1: "aa"})

        self.assertEqual((said[0], said[1]), ("before before.sfc", "after  after.sfc"))


if __name__ == "__main__":
    unittest.main()
