import importlib.util
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path = ROOT) -> Any:
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converge = load_module("converge_jp", ROOT / "tools")


class ScanPatternTest(unittest.TestCase):
    LINE = "SCAN addr=104C ch0=D9:104C:8192:fixed1 ch1=C0:D4FE:0:fixed0 ch7=4E:AA28:0:fixed0"

    def test_a_scan_line_is_recognised(self) -> None:
        self.assertIsNotNone(converge.SCAN.match(self.LINE))

    def test_the_requested_address_is_the_first_field(self) -> None:
        self.assertEqual(converge.SCAN.match(self.LINE).group(1), "104C")

    def test_a_line_that_is_not_a_scan_is_ignored(self) -> None:
        self.assertIsNone(converge.SCAN.match("SCANLEN addr=104C steps=12"))


class WindowTest(unittest.TestCase):
    def test_the_window_starts_at_bank_c0(self) -> None:
        self.assertEqual(converge.WINDOW_BASE, 0xC0)

    def test_the_scan_budget_matches_the_gate(self) -> None:
        gate = load_module("gate")

        self.assertEqual(converge.SCAN_BUDGET, gate.SCAN_BUDGET)


class PassTest(unittest.TestCase):
    def test_every_pass_names_a_driver_and_a_frame_count(self) -> None:
        for name, extra, frames in converge.PASSES:
            self.assertTrue(name)
            self.assertTrue(any(argument.startswith("SF") for argument in extra))
            self.assertGreater(frames, 0)

    def test_the_passes_are_not_all_the_same_driver(self) -> None:
        drivers = {tuple(extra) for _, extra, _ in converge.PASSES}

        self.assertGreater(len(drivers), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
