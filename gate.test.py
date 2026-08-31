import importlib.util
import tempfile
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


class UndecodableTest(unittest.TestCase):
    """The two ways an entry can fail to reproduce what the table claims."""

    ROM = bytes(0x400000)

    def test_a_table_every_entry_of_which_decodes_reports_nothing(self) -> None:
        self.assertEqual(gate.undecodable(self.ROM, [(0x100000, 16)]), [])

    def test_an_entry_that_raises_is_named_as_raised(self) -> None:
        def _raise(*_args: Any) -> Any:
            raise gate.sdd1.TruncatedStream("nope")

        self.assertEqual(gate.undecodable(self.ROM, [(0x100000, 16)], _raise)[0][2], "raised")

    def test_an_entry_that_decodes_short_is_named_with_what_it_produced(self) -> None:
        def _short(rom: Any, source: int, length: int) -> Any:
            return gate.sdd1.decompress(rom, source, length // 2)

        self.assertEqual(gate.undecodable(self.ROM, [(0x100000, 16)], _short)[0][2], "produced 8")

    def test_an_empty_table_reports_nothing(self) -> None:
        self.assertEqual(gate.undecodable(self.ROM, []), [])


class CheckTest(unittest.TestCase):
    """Each finding on its own, driven without a cartridge."""

    ABSENT = Path("/nonexistent/cartridge.sfc")

    def findings(self, **rest: Any) -> list[str]:
        found: list[str] = gate.check("jp", retail=self.ABSENT, **rest)
        return found

    def test_a_table_with_nothing_wrong_reports_nothing(self) -> None:
        self.assertEqual(self.findings(entries=[(0x100000, 16)], wanted={}), [])

    def test_a_repeated_source_is_reported(self) -> None:
        found = self.findings(entries=[(0x100000, 16), (0x100000, 32)], wanted={})

        self.assertIn("repeated sources", found[0])

    def test_a_repeated_source_is_reported_rather_than_raising(self) -> None:
        found = self.findings(entries=[(0x100000, 16), (0x100000, 32)], wanted={})

        self.assertEqual(len(found), 1)

    def test_a_request_the_table_does_not_cover_is_reported(self) -> None:
        found = self.findings(entries=[(0x100000, 16)], wanted={0x200000: 8})

        self.assertIn("not covered", found[0])

    def test_a_request_the_table_covers_too_short_is_reported(self) -> None:
        found = self.findings(entries=[(0x100000, 16)], wanted={0x100000: 64})

        self.assertIn("table has 16", found[0])

    def test_an_absent_cartridge_is_not_itself_a_finding(self) -> None:
        self.assertEqual(self.findings(entries=[(0x100000, 16)], wanted={}), [])

    def test_a_cartridge_that_is_there_has_its_entries_decoded(self) -> None:
        rom = Path(tempfile.mkdtemp()) / "probe.sfc"
        rom.write_bytes(bytes(0x400000))

        def _raise(*_args: Any) -> Any:
            raise gate.sdd1.TruncatedStream("nope")

        found = gate.check("jp", entries=[(0x100000, 16)], wanted={}, retail=rom, decode=_raise)

        self.assertIn("do not decode", found[0])

    def test_an_empty_table_has_no_scan_to_measure(self) -> None:
        self.assertEqual(gate.worst_scan([]), 0)

    def test_a_scan_past_the_budget_is_reported(self) -> None:
        crowded = [(0x10000 * bank + 0x1000, 16) for bank in range(gate.SCAN_BUDGET + 2)]
        found = self.findings(entries=crowded, wanted={})

        self.assertTrue(any("key scan" in one for one in found))


class CommandTest(unittest.TestCase):
    """The command line, with the region check passed in."""

    def run_with(self, argv: list[str], findings: list[str]) -> tuple[int, list[str]]:
        said: list[str] = []
        code = gate.main(
            argv,
            say=said.append,
            examine=lambda _r: findings,
            listing=lambda _r: [(0x100000, 16)],
        )
        return code, said

    def test_a_region_with_no_findings_passes(self) -> None:
        code, said = self.run_with(["gate", "jp"], [])

        self.assertEqual((code, "ok" in said[0]), (0, True))

    def test_a_region_with_a_finding_fails_and_names_it(self) -> None:
        code, said = self.run_with(["gate", "jp"], ["something is wrong"])

        self.assertEqual((code, "something is wrong" in "\n".join(said)), (1, True))

    def test_no_region_named_means_every_region(self) -> None:
        _, said = self.run_with(["gate"], [])

        self.assertEqual(len(said), len(gate.RETAIL))

    def test_an_unknown_region_is_refused(self) -> None:
        said: list[str] = []

        code = gate.main(["gate", "mars"], say=said.append)

        self.assertEqual((code, "unknown region" in said[0]), (2, True))

    def test_the_complaint_can_be_sent_somewhere_other_than_the_report(self) -> None:
        said: list[str] = []
        complained: list[str] = []

        gate.main(["gate", "mars"], say=said.append, complain=complained.append)

        self.assertEqual((said, len(complained)), ([], 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
