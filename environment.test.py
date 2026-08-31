"""That the environment checks look at this machine rather than describe one.

Every check here has to work on Windows, macOS and Linux, and none of them may
assume which one it is running on. So the tests drive each check twice: once
against a machine that is fine and once against one that is not, with the
platform, the filesystem and the tools all supplied rather than discovered. A
check that cannot be made to fail is a check nobody has seen work.

The one thing not faked is the current machine, which every check is also run
against at the end. That run asserts shape rather than outcome: it must produce
an observation for everything, and it must not raise, whatever it finds.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_module(name: str, where: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, where)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


environment = load_module("environment", Path(__file__).resolve().parent / "environment.py")


class ObservationTest(unittest.TestCase):
    def test_an_observation_carries_what_was_looked_at(self) -> None:
        one = environment.Observation("thing", True, "found", None)

        self.assertEqual(one.name, "thing")

    def test_a_failing_one_may_carry_what_to_do_about_it(self) -> None:
        one = environment.Observation("thing", False, "missing", "install it")

        self.assertEqual(one.advice, "install it")


class InterpreterTest(unittest.TestCase):
    def test_the_command_that_runs_is_the_one_reported(self) -> None:
        found = environment.interpreter(look=lambda name: name == "python3")

        self.assertIn("python3", found.detail)

    def test_a_machine_with_only_python_says_to_use_python(self) -> None:
        found = environment.interpreter(look=lambda name: name == "python")

        self.assertIn("python", found.detail)
        self.assertNotIn("python3", found.detail)

    def test_windows_py_launcher_is_reported_when_it_is_all_there_is(self) -> None:
        found = environment.interpreter(look=lambda name: name == "py")

        self.assertIn("py -3", found.detail)

    def test_a_machine_where_none_of_them_resolve_is_not_ok(self) -> None:
        found = environment.interpreter(look=lambda _name: False)

        self.assertFalse(found.ok)

    def test_and_says_what_to_do_about_it(self) -> None:
        found = environment.interpreter(look=lambda _name: False)

        self.assertTrue(found.advice)


class EncodingTest(unittest.TestCase):
    def test_utf8_output_is_fine(self) -> None:
        found = environment.output_encoding(encoding="utf-8")

        self.assertTrue(found.ok)

    def test_a_legacy_windows_codepage_is_not(self) -> None:
        found = environment.output_encoding(encoding="cp1252")

        self.assertFalse(found.ok)

    def test_and_the_advice_names_the_switch_that_fixes_it(self) -> None:
        found = environment.output_encoding(encoding="cp1252")

        self.assertIn("PYTHONUTF8", found.advice)

    def test_an_unknown_encoding_is_reported_rather_than_guessed(self) -> None:
        found = environment.output_encoding(encoding=None)

        self.assertFalse(found.ok)


class LineEndingTest(unittest.TestCase):
    def test_a_tree_whose_text_files_use_line_feeds_is_fine(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            (Path(where) / "a.md").write_bytes(b"one\ntwo\n")

            found = environment.line_endings(Path(where))

            self.assertTrue(found.ok)

    def test_a_tree_that_git_converted_to_carriage_returns_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            (Path(where) / "a.md").write_bytes(b"one\r\ntwo\r\n")

            found = environment.line_endings(Path(where))

            self.assertFalse(found.ok)

    def test_and_the_advice_names_the_setting_that_caused_it(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            (Path(where) / "a.md").write_bytes(b"one\r\n")

            found = environment.line_endings(Path(where))

            self.assertIn("autocrlf", found.advice)

    def test_a_tree_with_nothing_to_read_says_so_rather_than_passing(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            found = environment.line_endings(Path(where))

            self.assertIn("nothing", found.detail)


class CaseTest(unittest.TestCase):
    def test_a_case_sensitive_filesystem_is_reported_as_such(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            found = environment.filesystem_case(Path(where))

            self.assertIn("sensitive", found.detail)

    def test_the_check_never_fails_a_machine_for_its_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            found = environment.filesystem_case(Path(where))

            self.assertTrue(found.ok)


class PathBudgetTest(unittest.TestCase):
    def test_a_short_path_on_windows_is_fine(self) -> None:
        found = environment.path_budget(Path("C:/a"), windows=True, longest=80)

        self.assertTrue(found.ok)

    def test_a_path_past_the_windows_limit_is_not(self) -> None:
        found = environment.path_budget(Path("C:/a"), windows=True, longest=300)

        self.assertFalse(found.ok)

    def test_and_the_advice_names_the_setting_that_lifts_it(self) -> None:
        found = environment.path_budget(Path("C:/a"), windows=True, longest=300)

        self.assertIn("LongPathsEnabled", found.advice)

    def test_the_same_length_elsewhere_is_still_reported(self) -> None:
        found = environment.path_budget(Path("/a"), windows=False, longest=300)

        self.assertFalse(found.ok)

    def test_because_the_tree_is_shared_rather_than_local_to_one_machine(self) -> None:
        here = environment.path_budget(Path("/a"), windows=False, longest=300)
        there = environment.path_budget(Path("C:/a"), windows=True, longest=300)

        self.assertEqual((here.ok, there.ok), (False, False))

    def test_the_headroom_a_windows_checkout_would_have_is_reported(self) -> None:
        found = environment.path_budget(Path("/a"), windows=False, longest=100)

        self.assertIn("160", found.detail)

    def test_a_tree_that_leaves_no_room_for_a_checkout_path_is_flagged_anywhere(self) -> None:
        found = environment.path_budget(Path("/a"), windows=False, longest=250)

        self.assertFalse(found.ok)

    def test_and_the_advice_says_it_is_about_windows_rather_than_here(self) -> None:
        found = environment.path_budget(Path("/a"), windows=False, longest=250)

        self.assertIn("Windows", found.advice)

    def test_a_tree_with_room_to_spare_passes_on_every_system(self) -> None:
        for windows in (True, False):
            found = environment.path_budget(Path("/a"), windows=windows, longest=100)

            self.assertTrue(found.ok)

    def test_a_generated_directory_is_reported_without_failing_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            deep = Path(where) / "node_modules" / ("a" * 120) / ("b" * 120)
            deep.mkdir(parents=True)
            (deep / "c.js").write_bytes(b"")

            found = environment.path_budget(Path(where))

            self.assertTrue(found.ok)

    def test_but_the_same_depth_in_tracked_content_does_fail_it(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            deep = Path(where) / ("a" * 120) / ("b" * 120)
            deep.mkdir(parents=True)
            (deep / "c.py").write_bytes(b"")

            found = environment.path_budget(Path(where))

            self.assertFalse(found.ok)

    def test_and_a_generated_one_is_still_named_so_it_is_not_a_surprise(self) -> None:
        with tempfile.TemporaryDirectory() as where:
            deep = Path(where) / "node_modules" / ("a" * 120) / ("b" * 120)
            deep.mkdir(parents=True)
            (deep / "c.js").write_bytes(b"")

            found = environment.path_budget(Path(where))

            self.assertIn("node_modules", found.detail)


class ToolTest(unittest.TestCase):
    def test_a_tool_that_is_present_is_reported_with_where(self) -> None:
        found = environment.tool("git", look=lambda _n: "/usr/bin/git")

        self.assertTrue(found.ok)

    def test_one_that_is_absent_is_not_ok(self) -> None:
        found = environment.tool("git", look=lambda _n: None)

        self.assertFalse(found.ok)

    def test_an_optional_tool_that_is_absent_is_still_ok(self) -> None:
        found = environment.tool("docker", look=lambda _n: None, required=False)

        self.assertTrue(found.ok)

    def test_but_says_it_was_not_found(self) -> None:
        found = environment.tool("docker", look=lambda _n: None, required=False)

        self.assertIn("not found", found.detail)


class SpaceTest(unittest.TestCase):
    def test_plenty_of_room_is_fine(self) -> None:
        found = environment.free_space(ROOT, measure=lambda _p: 40 * 1024**3)

        self.assertTrue(found.ok)

    def test_a_nearly_full_disk_is_not(self) -> None:
        found = environment.free_space(ROOT, measure=lambda _p: 100 * 1024**2)

        self.assertFalse(found.ok)

    def test_a_disk_it_cannot_measure_is_reported_rather_than_assumed(self) -> None:
        def _refuse(_path: Path) -> int:
            raise OSError("no")

        found = environment.free_space(ROOT, measure=_refuse)

        self.assertFalse(found.ok)


class SurveyTest(unittest.TestCase):
    def test_every_check_produces_an_observation_on_this_machine(self) -> None:
        found = environment.observations(ROOT)

        self.assertGreaterEqual(len(found), 8)

    def test_none_of_them_raise_whatever_they_find(self) -> None:
        found = environment.observations(ROOT)

        self.assertTrue(all(isinstance(one.detail, str) for one in found))

    def test_every_one_that_did_not_pass_says_what_to_do(self) -> None:
        silent = [
            one.name for one in environment.observations(ROOT) if not one.ok and not one.advice
        ]

        self.assertEqual(silent, [])

    def test_every_observation_has_a_name_of_its_own(self) -> None:
        names = [one.name for one in environment.observations(ROOT)]

        self.assertEqual(len(names), len(set(names)))

    def test_a_check_that_throws_is_caught_and_reported_rather_than_lost(self) -> None:
        def _explode(_root: Path) -> Any:
            raise RuntimeError("boom")

        found = environment.guarded("thing", _explode, ROOT)

        self.assertEqual((found.ok, "RuntimeError" in found.detail), (False, True))

    def test_and_a_check_that_works_is_passed_through_untouched(self) -> None:
        def _fine(_root: Path) -> Any:
            return environment.Observation("thing", True, "fine", None)

        found = environment.guarded("thing", _fine, ROOT)

        self.assertEqual(found.detail, "fine")


if __name__ == "__main__":
    unittest.main()
