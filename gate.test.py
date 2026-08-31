import importlib.util
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


gate = load_module("gate")
jpstreams = load_module("jpstreams")

JP_ROM = ROOT / "roms" / "sfz2-jp-final.sfc"


class DuplicateTest(unittest.TestCase):
    def test_a_clean_table_reports_nothing(self) -> None:
        self.assertEqual(gate.duplicates([(0x10, 32), (0x20, 32)]), [])

    def test_a_repeated_source_is_reported(self) -> None:
        self.assertEqual(gate.duplicates([(0x10, 32), (0x10, 64)]), [0x10])


class CoverageTest(unittest.TestCase):
    def test_a_table_that_covers_every_request_passes(self) -> None:
        self.assertEqual(gate.uncovered([(0x10, 64)], {0x10: 64}), [])

    def test_an_absent_address_is_reported(self) -> None:
        missing = gate.uncovered([(0x10, 64)], {0x20: 32})

        self.assertEqual(missing, [(0x20, 32, None)])

    def test_a_length_below_the_request_is_reported(self) -> None:
        short = gate.uncovered([(0x10, 32)], {0x10: 64})

        self.assertEqual(short, [(0x10, 64, 32)])

    def test_a_length_above_the_request_is_fine(self) -> None:
        self.assertEqual(gate.uncovered([(0x10, 128)], {0x10: 64}), [])


class ScanTest(unittest.TestCase):
    def test_a_small_table_scans_cheaply(self) -> None:
        worst = gate.worst_scan([(0x10000, 32), (0x20000, 32)])

        self.assertLessEqual(worst, gate.SCAN_BUDGET)


@unittest.skipUnless(JP_ROM.exists(), "the Japanese ROM is absent")  # pragma: no cover
class ShippedTableTest(unittest.TestCase):
    def test_the_shipped_table_passes_every_gate(self) -> None:
        findings = gate.check("jp")

        self.assertEqual(findings, [])

    def test_the_recorded_requests_are_a_subset_of_the_table(self) -> None:
        sources = {source for source, _ in jpstreams.STREAMS}

        for address in gate.requests("jp"):
            self.assertIn(address, sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
