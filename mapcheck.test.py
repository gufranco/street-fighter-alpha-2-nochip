import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mapcheck = load_module("mapcheck")
jpstreams = load_module("jpstreams")

JP_ROM = ROOT / "roms" / "sfz2-jp-final.sfc"


class LoadTest(unittest.TestCase):
    def test_a_table_loads_as_sorted_pairs(self) -> None:
        self.assertEqual(mapcheck.load([(512, 64), (256, 32)]), [(256, 32), (512, 64)])

    def test_a_table_with_a_non_positive_length_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mapcheck.load([(256, 0)])

    def test_the_shipped_table_is_the_default(self) -> None:
        self.assertEqual(len(mapcheck.load()), len(jpstreams.STREAMS))


class DuplicateTest(unittest.TestCase):
    def test_distinct_sources_report_no_duplicates(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources([(1, 2), (3, 4)]), [])

    def test_a_repeated_source_is_reported(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources([(1, 2), (1, 4)]), [1])


class KeyTest(unittest.TestCase):
    def test_a_source_maps_to_its_window_bank_and_offset(self) -> None:
        self.assertEqual(mapcheck.window_key(0x1A86EC), (0xDA, 0x86EC))

    def test_the_first_window_bank_is_c0(self) -> None:
        self.assertEqual(mapcheck.window_key(0x000000), (0xC0, 0x0000))


class ScanCostTest(unittest.TestCase):
    def test_an_empty_map_costs_nothing(self) -> None:
        self.assertEqual(mapcheck.scan_cost([]), (0, 0))

    def test_a_single_stream_is_found_immediately(self) -> None:
        median, worst = mapcheck.scan_cost([(0x1A86EC, 3936)])

        self.assertEqual(worst, 0)
        self.assertEqual(median, 0)

    def test_colliding_addresses_push_a_key_further_out(self) -> None:
        entries = [(0x000100 + (bank << 16), 32) for bank in range(4)]

        _, worst = mapcheck.scan_cost(entries)

        self.assertGreater(worst, 0)


@unittest.skipUnless(JP_ROM.exists(), "the Japanese ROM is absent")  # pragma: no cover
class JapaneseMapTest(unittest.TestCase):
    entries: ClassVar[Any]
    rom: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.rom = dump.read(JP_ROM)
        cls.entries = mapcheck.load()

    def test_the_map_holds_the_streams_the_build_needs(self) -> None:
        self.assertGreaterEqual(len(self.entries), 2816)

    def test_no_source_appears_twice(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources(self.entries), [])

    def test_every_stream_decompresses(self) -> None:
        self.assertEqual(mapcheck.undecodable(self.rom, self.entries), [])

    def test_every_stream_stays_inside_the_rom(self) -> None:
        for source, _ in self.entries:
            self.assertLess(source, len(self.rom))

    def test_the_lookup_stays_cheap_to_scan(self) -> None:
        _, worst = mapcheck.scan_cost(self.entries)

        self.assertLessEqual(worst, mapcheck.SCAN_BUDGET)

    def test_the_streams_recovered_by_harvesting_are_present(self) -> None:
        sources = {source for source, _ in self.entries}

        for recovered in mapcheck.RECOVERED_JP:
            self.assertIn(recovered, sources)


class RegionTest(unittest.TestCase):
    """Telling which table a cartridge name belongs to."""

    def test_a_japanese_name_selects_the_japanese_table(self) -> None:
        self.assertIs(mapcheck.table_for("sfz2-jp-final.sfc"), mapcheck.jpstreams.STREAMS)

    def test_a_built_japanese_image_selects_it_too(self) -> None:
        self.assertIs(mapcheck.table_for("jp-base-free.sfc"), mapcheck.jpstreams.STREAMS)

    def test_an_american_name_selects_the_american_table(self) -> None:
        self.assertIs(mapcheck.table_for("sfa2-usa-final.sfc"), mapcheck.usastreams.STREAMS)

    def test_a_built_american_image_selects_it_too(self) -> None:
        self.assertIs(mapcheck.table_for("usa-base-free.sfc"), mapcheck.usastreams.STREAMS)

    def test_a_name_belonging_to_neither_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            mapcheck.table_for("mystery.sfc")


class UndecodableTest(unittest.TestCase):
    """Entries the decompressor will not reproduce."""

    ROM = bytes(0x400000)

    def test_a_table_that_decodes_reports_nothing(self) -> None:
        self.assertEqual(mapcheck.undecodable(self.ROM, [(0x100000, 16)]), [])

    def test_an_entry_running_past_the_cartridge_is_named(self) -> None:
        self.assertEqual(mapcheck.undecodable(self.ROM, [(0x3FFFFF, 8192)]), [0x3FFFFF])


class ReportTest(unittest.TestCase):
    """The verdict on one cartridge, driven without a dump."""

    ROM = bytes(0x400000)

    def run_with(self, entries: list[tuple[int, int]]) -> tuple[int, list[str]]:
        said: list[str] = []
        code = mapcheck.report(
            "sfz2-jp-final.sfc", say=said.append, read=lambda _p: self.ROM, entries=entries
        )
        return code, said

    def test_a_table_with_nothing_wrong_passes(self) -> None:
        code, said = self.run_with([(0x100000, 16)])

        self.assertEqual((code, "OK" in said[-1]), (0, True))

    def test_a_repeated_source_fails(self) -> None:
        code, said = self.run_with([(0x100000, 16), (0x100000, 32)])

        self.assertEqual((code, "FAIL" in said[-1]), (1, True))

    def test_a_repeated_source_is_reported_rather_than_raising(self) -> None:
        _, said = self.run_with([(0x100000, 16), (0x100000, 32)])

        self.assertIn("duplicates     1", "\n".join(said))

    def test_an_entry_that_does_not_decode_fails(self) -> None:
        code, said = self.run_with([(0x3FFFFF, 8192)])

        self.assertEqual((code, "undecodable    1" in "\n".join(said)), (1, True))

    def test_a_scan_past_the_budget_fails(self) -> None:
        crowded = [(0x10000 * bank + 0x1000, 16) for bank in range(mapcheck.SCAN_BUDGET + 2)]

        code, said = self.run_with(crowded)

        self.assertEqual((code, "FAIL" in said[-1]), (1, True))

    def test_the_report_counts_the_streams_it_checked(self) -> None:
        _, said = self.run_with([(0x100000, 16), (0x110000, 16)])

        self.assertIn("streams        2", said[0])


class CommandTest(unittest.TestCase):
    """The command line."""

    def test_the_wrong_number_of_arguments_prints_the_usage(self) -> None:
        said: list[str] = []

        code = mapcheck.main(["mapcheck.py"], say=said.append)

        self.assertEqual((code, "usage" in said[0]), (2, True))

    def test_a_named_cartridge_is_examined_and_its_verdict_returned(self) -> None:
        looked: list[str] = []

        def _record(where: str, _say: Any) -> int:
            looked.append(where)
            return 0

        code = mapcheck.main(
            ["mapcheck.py", "sfz2-jp-final.sfc"], say=lambda _l: None, examine=_record
        )

        self.assertEqual((code, looked), (0, ["sfz2-jp-final.sfc"]))

    def test_the_complaint_can_be_sent_somewhere_other_than_the_report(self) -> None:
        said: list[str] = []
        complained: list[str] = []

        mapcheck.main(["mapcheck.py"], say=said.append, complain=complained.append)

        self.assertEqual((said, len(complained)), ([], 1))


class EmptyScanTest(unittest.TestCase):
    """A table with nothing in it has no scan to measure."""

    def test_an_empty_table_costs_nothing(self) -> None:
        self.assertEqual(mapcheck.scan_cost([]), (0, 0))


class LoadRefusalTest(unittest.TestCase):
    """A length that cannot describe a stream."""

    def test_a_non_positive_length_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            mapcheck.load([(0x100000, 0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
