import importlib.util
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


validate_all = load_module("validate_all", ROOT / "tools" / "validate_all.py")


class BurstTest(unittest.TestCase):
    def test_no_frames_is_no_burst(self) -> None:
        self.assertEqual(validate_all.longest_burst([]), 0)

    def test_one_frame_is_a_burst_of_one(self) -> None:
        self.assertEqual(validate_all.longest_burst([10]), 1)

    def test_consecutive_frames_are_one_burst(self) -> None:
        self.assertEqual(validate_all.longest_burst([10, 11, 12]), 3)

    def test_a_gap_ends_a_burst(self) -> None:
        self.assertEqual(validate_all.longest_burst([10, 11, 20, 21, 22]), 3)

    def test_the_longest_burst_wins_even_when_it_comes_first(self) -> None:
        self.assertEqual(validate_all.longest_burst([1, 2, 3, 4, 10]), 4)

    def test_a_repeated_frame_number_does_not_extend_a_burst(self) -> None:
        self.assertEqual(validate_all.longest_burst([10, 10, 10]), 1)


class SummariseTest(unittest.TestCase):
    def _log(self, folder: Path | str, text: str) -> Path:
        path = Path(folder) / "run.txt"
        path.write_text(text)
        return path

    def test_a_clean_run_reports_what_it_loaded_and_how_far_it_got(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = validate_all.summarise(self._log(folder, "RESULT load=ok frames=12000\n"))

            self.assertEqual(found["load"], "ok")
            self.assertEqual(found["frames"], 12000)

    def test_a_log_with_nothing_in_it_says_it_does_not_know(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = validate_all.summarise(self._log(folder, ""))

            self.assertEqual(found["load"], "?")
            self.assertEqual(found["frames"], 0)

    def test_a_bright_sample_above_the_threshold_counts_as_lit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = validate_all.summarise(
                self._log(folder, "BRIGHT frame=1 value=9.0\nBRIGHT frame=2 value=1.0\n")
            )

            self.assertEqual(found["lit"], "1/2")

    def test_a_scan_within_the_budget_is_not_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = validate_all.summarise(self._log(folder, "SCANLEN addr=C0 steps=3\n"))

            self.assertEqual(found["scans"], 1)
            self.assertEqual(found["misses"], 0)

    def test_a_scan_past_the_budget_is_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            steps = validate_all.SCAN_BUDGET + 1
            found = validate_all.summarise(self._log(folder, f"SCANLEN addr=C0 steps={steps}\n"))

            self.assertEqual(found["misses"], 1)

    def test_a_run_of_audio_frames_becomes_a_pause_in_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            lines = "".join(f"APU frame={frame} writes=40\n" for frame in range(60))

            found = validate_all.summarise(self._log(folder, lines))

            self.assertEqual(found["pause"], "1.00s")

    def test_a_log_with_no_audio_frames_reports_no_pause(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = validate_all.summarise(self._log(folder, "RESULT load=ok frames=1\n"))

            self.assertEqual(found["pause"], "0.00s")

    def test_bytes_it_cannot_decode_do_not_stop_the_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.txt"
            path.write_bytes(b"\xff\xfe\nRESULT load=ok frames=7\n")

            self.assertEqual(validate_all.summarise(path)["frames"], 7)


class MappingTest(unittest.TestCase):
    def test_a_converted_image_is_read_through_the_windowed_map(self) -> None:
        self.assertEqual(validate_all.mapping_for("jp-both-free"), validate_all.FREE_MAPPING)

    def test_one_still_in_cartridge_form_is_not(self) -> None:
        self.assertEqual(validate_all.mapping_for("jp-both-cart"), validate_all.CART_MAPPING)

    def test_the_two_forms_are_read_through_different_maps(self) -> None:
        self.assertNotEqual(
            validate_all.mapping_for("jp-both-free"), validate_all.mapping_for("jp-both-cart")
        )

    def test_the_comparison_tool_reads_cartridge_form_the_same_way(self) -> None:
        compare_audio = load_module("compare_audio", ROOT / "tools" / "compare_audio.py")

        self.assertEqual(compare_audio.CART_MAPPING, validate_all.CART_MAPPING)


class ShellOutTest(unittest.TestCase):
    """The one step that reaches for a container, with the reaching passed in."""

    def test_it_names_the_image_and_the_mapping(self) -> None:
        asked: list[Any] = []

        validate_all.run(
            validate_all.ROOT / "build" / "all" / "probe.sfc",
            "-2",
            execute=lambda command, **_rest: asked.append(command),
        )

        self.assertEqual(asked[0][-1], "-2")

    def test_it_returns_the_log_it_wrote(self) -> None:
        found = validate_all.run(
            validate_all.ROOT / "build" / "all" / "probe.sfc",
            "-2",
            execute=lambda *_a, **_k: None,
        )

        self.assertEqual(found.name, "probe-2.txt")


class CommandTest(unittest.TestCase):
    """The verdict on a set of images, driven against recorded logs."""

    @staticmethod
    def log(load: str = "ok", frames: int = validate_all.FRAMES, misses: int = 0) -> str:
        lines = [f"RESULT load={load} frames={frames}", "BRIGHT frame=1 value=9.0"]
        lines += [f"SCANLEN addr=104C steps={validate_all.SCAN_BUDGET + 1}"] * misses
        return "\n".join(lines) + "\n"

    def run_with(self, logs: dict[str, str], argv: str = "") -> tuple[int, list[str]]:
        where = Path(tempfile.mkdtemp())
        said: list[str] = []

        def _drive(image: Path, mapping: str) -> Path:
            written = where / f"{image.stem}{mapping}.txt"
            written.write_text(logs[image.stem])
            return written

        code = validate_all.main(
            ["validate_all.py", argv] if argv else ["validate_all.py"],
            images=[where / f"{stem}.sfc" for stem in logs],
            drive=_drive,
            say=said.append,
        )
        return code, said

    def test_an_image_that_loads_and_never_misses_passes(self) -> None:
        code, said = self.run_with({"jp-base-free": self.log()})

        self.assertEqual((code, "1 images, 0 failing" in "\n".join(said)), (0, True))

    def test_an_image_that_did_not_load_fails(self) -> None:
        code, said = self.run_with({"jp-base-free": self.log(load="no")})

        self.assertEqual((code, "FAIL jp-base-free" in "\n".join(said)), (1, True))

    def test_an_image_that_missed_a_lookup_fails(self) -> None:
        code, _ = self.run_with({"jp-base-free": self.log(misses=1)})

        self.assertEqual(code, 1)

    def test_an_image_that_stopped_early_fails(self) -> None:
        code, _ = self.run_with({"jp-base-free": self.log(frames=10)})

        self.assertEqual(code, 1)

    def test_a_named_image_is_the_only_one_driven(self) -> None:
        _, said = self.run_with(
            {"jp-base-free": self.log(), "usa-base-free": self.log()}, argv="jp"
        )

        self.assertIn("1 images", "\n".join(said))

    def test_a_bypass_image_is_never_driven(self) -> None:
        _, said = self.run_with({"jp-base-bypass": self.log()})

        self.assertIn("0 images", "\n".join(said))

    def test_the_report_names_what_it_measured(self) -> None:
        _, said = self.run_with({"jp-base-free": self.log()})

        self.assertIn("load=ok", said[0])


if __name__ == "__main__":
    unittest.main()
